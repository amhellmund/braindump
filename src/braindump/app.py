# Copyright 2026 Andi Hellmund
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""FastAPI application — API routes and static frontend serving."""

import asyncio
import contextlib
import dataclasses
import importlib.metadata
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from braindump import chats, dirs, health, query, storage, txlog, wiki
from braindump.llm import load_backend
from braindump.types import (
    ChatSessionResponse,
    ChatSessionSummary,
    HealthReport,
    ImageUploadResponse,
    InfoResponse,
    LLMConfig,
    QueryRequest,
    QueryResponse,
    SpikePayload,
    SpikeResponse,
    StatusResponse,
    UsageData,
)

_logger = logging.getLogger(__name__)

# Path parameter type that enforces lowercase UUID v4 format.
_UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
SpikeId = Annotated[str, PathParam(pattern=_UUID_RE)]

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################

_DEV: bool = os.getenv("BRAINDUMP_DEV", "0") == "1"
# When installed from a wheel the frontend is bundled inside the package
# at braindump/frontend/dist/.  In an editable / source checkout it lives at
# the repo root under frontend/dist/.
_PKG_DIST: Path = Path(__file__).parent / "frontend" / "dist"
_DEV_DIST: Path = Path(__file__).parent.parent.parent / "frontend" / "dist"
_DIST: Path = _PKG_DIST if _PKG_DIST.exists() else _DEV_DIST

_DEFAULT_HEALTH_CHECK_INTERVAL_MINUTES = 60


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Resolve the workspace directory, initialise the wiki layer, and start background tasks."""
    raw = os.getenv("BRAINDUMP_WORKSPACE")
    if not raw:
        _logger.error("BRAINDUMP_WORKSPACE is not set — start via `braindump run <workspace>`.")
        raise RuntimeError("BRAINDUMP_WORKSPACE environment variable is required")

    workspace = Path(raw).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    braindump_data_dir = dirs.config_dir(workspace)
    braindump_data_dir.mkdir(exist_ok=True)

    wiki.init_wiki(workspace)

    # Read health-check interval from llm.json (falls back to default if not configured yet)
    interval_minutes = _DEFAULT_HEALTH_CHECK_INTERVAL_MINUTES
    llm_config_path = braindump_data_dir / "llm.json"
    if llm_config_path.exists():
        with contextlib.suppress(Exception):
            cfg = LLMConfig.model_validate_json(llm_config_path.read_text(encoding="utf-8"))
            interval_minutes = cfg.health_check_interval_minutes

    # Load persisted usage counters so totals survive restarts.
    usage_file = dirs.usage_path(workspace)
    if usage_file.exists():
        with contextlib.suppress(Exception):
            saved = UsageData.model_validate_json(usage_file.read_text(encoding="utf-8"))
            _state.total_cost_usd = saved.total_cost_usd
            _state.total_tokens = saved.total_tokens

    app.state.workspace = workspace
    app.state.braindump_data_dir = braindump_data_dir
    app.state.llm_backend = None  # loaded lazily on first query

    health_task = asyncio.create_task(_health_check_loop(workspace, braindump_data_dir, interval_minutes))
    try:
        yield
    finally:
        health_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await health_task


app = FastAPI(
    title="braindump",
    version="0.1.0",
    lifespan=_lifespan,
    docs_url="/api/docs" if _DEV else None,
    redoc_url="/api/redoc" if _DEV else None,
)

# ---------------------------------------------------------------------------
# API router — all routes live under /api/v1
# ---------------------------------------------------------------------------

api = APIRouter(prefix="/api/v1")


@api.get("/info", summary="App and schema version info")
async def get_info(request: Request) -> InfoResponse:
    """Return the braindump app version and workspace schema version numbers."""
    workspace: Path = request.app.state.workspace
    path = dirs.versions_path(workspace)
    versions = (
        wiki.WorkspaceVersions.model_validate_json(path.read_text(encoding="utf-8"))
        if path.exists()
        else wiki.WorkspaceVersions()
    )
    return InfoResponse(
        version=importlib.metadata.version("braindump"),
        wiki_schema=versions.wiki_schema,
        meta=versions.meta,
    )


@api.get("/health", summary="Health check")
async def health_status(request: Request) -> JSONResponse:
    """Return service health status and the active workspace path."""
    return JSONResponse({"status": "ok", "dev": _DEV, "workspace": str(request.app.state.workspace)})


# ---------------------------------------------------------------------------
# Spike routes
# ---------------------------------------------------------------------------


@api.get("/spikes", summary="List all spikes")
async def list_spikes(request: Request) -> list[SpikeResponse]:
    """Return all spikes from the metadata cache, most-recently modified first."""
    workspace: Path = request.app.state.workspace

    entries = wiki.list_all_meta(workspace)
    result: list[SpikeResponse] = []
    for entry in entries:
        try:
            raw = storage.read_spike_raw(workspace, entry.id)
        except FileNotFoundError:
            continue  # skip entries whose files were removed outside the app
        result.append(storage.parse_spike(raw, entry.id))
    return result


@api.post("/spikes", summary="Create a spike", status_code=201)
async def create_spike(request: Request, body: SpikePayload, bg: BackgroundTasks) -> SpikeResponse:
    """Persist a new spike to disk and schedule a wiki update."""
    workspace: Path = request.app.state.workspace
    braindump_data_dir: Path = request.app.state.braindump_data_dir

    spike_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    raw = storage.enrich_spike(body.raw, now, now)
    storage.write_spike(workspace, spike_id, raw)
    spike = storage.parse_spike(raw, spike_id)

    # Update meta.json immediately (no LLM) so the spike appears in listings at once.
    wiki.update_meta_json(workspace, spike)

    bg.add_task(_wiki_update_and_notify, workspace, spike, braindump_data_dir)
    return spike


@api.get("/spikes/{spike_id}", summary="Get a single spike")
async def get_spike(request: Request, spike_id: SpikeId) -> SpikeResponse:
    """Return the full content and metadata for one spike."""
    workspace: Path = request.app.state.workspace
    try:
        raw = storage.read_spike_raw(workspace, spike_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Spike not found") from exc
    return storage.parse_spike(raw, spike_id)


@api.put("/spikes/{spike_id}", summary="Update a spike")
async def update_spike(request: Request, spike_id: SpikeId, body: SpikePayload, bg: BackgroundTasks) -> SpikeResponse:
    """Overwrite spike content on disk and schedule a wiki update."""
    workspace: Path = request.app.state.workspace
    braindump_data_dir: Path = request.app.state.braindump_data_dir

    # Read the existing spike to preserve its creation timestamp.
    try:
        existing_raw = storage.read_spike_raw(workspace, spike_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Spike not found") from exc

    existing = storage.parse_spike(existing_raw, spike_id)
    now = datetime.now(UTC).isoformat()
    raw = storage.enrich_spike(body.raw, existing.createdAt, now)
    storage.write_spike(workspace, spike_id, raw)
    spike = storage.parse_spike(raw, spike_id)

    # Update meta.json immediately so changes are visible in listings right away.
    wiki.update_meta_json(workspace, spike)

    bg.add_task(_wiki_update_and_notify, workspace, spike, braindump_data_dir)
    return spike


@api.delete("/spikes/{spike_id}", summary="Delete a spike", status_code=204)
async def delete_spike(request: Request, spike_id: SpikeId, bg: BackgroundTasks) -> None:
    """Remove a spike from disk and schedule its removal from the wiki layer."""
    workspace: Path = request.app.state.workspace
    braindump_data_dir: Path = request.app.state.braindump_data_dir

    try:
        storage.read_spike_raw(workspace, spike_id)  # existence check
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Spike not found") from exc

    storage.delete_spike_file(workspace, spike_id)
    # Remove from meta.json immediately so the spike disappears from listings at once.
    wiki.remove_from_meta_json(workspace, spike_id)

    bg.add_task(_wiki_remove_and_notify, workspace, spike_id, braindump_data_dir)


# ---------------------------------------------------------------------------
# Image routes
# ---------------------------------------------------------------------------


@api.post("/images", summary="Upload an image", status_code=201)
async def upload_image(request: Request, file: UploadFile = File(...)) -> ImageUploadResponse:  # noqa: B008
    """Accept a multipart image upload, store it on disk, and return its URL."""
    workspace: Path = request.app.state.workspace
    content_type = file.content_type or ""
    data = await file.read()
    try:
        filename = storage.write_image(workspace, data, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    url = f"/api/v1/images/{filename}"
    return ImageUploadResponse(filename=filename, url=url)


@api.get("/images/{filename}", summary="Serve an image")
async def serve_image(request: Request, filename: str) -> Response:
    """Serve a stored image with the correct content-type header."""
    workspace: Path = request.app.state.workspace
    try:
        data, mime = storage.read_image(workspace, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Image not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=data, media_type=mime)


# ---------------------------------------------------------------------------
# Graph route
# ---------------------------------------------------------------------------


@api.get("/graph", summary="Knowledge graph data")
async def get_graph(request: Request, zoom: int = Query(2, ge=0, le=2)) -> JSONResponse:
    """Return nodes and edges derived from the wiki layer for the requested zoom level."""
    workspace: Path = request.app.state.workspace
    data = wiki.get_graph(workspace, zoom)
    return JSONResponse(data)


# ---------------------------------------------------------------------------
# Query route
# ---------------------------------------------------------------------------


@api.post("/query", summary="Wiki-grounded query")
async def ask(request: Request, body: QueryRequest) -> QueryResponse:
    """Answer a question using the compiled wiki index."""
    workspace: Path = request.app.state.workspace
    braindump_data_dir: Path = request.app.state.braindump_data_dir

    if body.session_id is not None and not chats.session_exists(workspace, body.session_id):
        raise HTTPException(status_code=404, detail="Chat session not found")

    try:
        if request.app.state.llm_backend is None:
            request.app.state.llm_backend = load_backend(braindump_data_dir)
        result = await query.run_query(workspace, request.app.state.llm_backend, body.query, body.history)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _state.total_cost_usd += result.cost_usd
    _state.total_tokens += result.total_tokens
    _save_usage(workspace)
    await _ws_manager.broadcast(
        {
            "type": "usage_update",
            "total_cost_usd": _state.total_cost_usd,
            "total_tokens": _state.total_tokens,
        }
    )

    if body.session_id is None:
        session = chats.create_session(workspace, body.query)
        effective_session_id = session.id
    else:
        effective_session_id = body.session_id

    chats.append_turn(
        workspace,
        effective_session_id,
        body.query,
        result.response.answer,
        result.response.citations,
    )

    return QueryResponse(
        answer=result.response.answer,
        citations=result.response.citations,
        sessionId=effective_session_id,
    )


@api.get("/chats", summary="List recent chat sessions")
async def list_chats(request: Request) -> list[ChatSessionSummary]:
    """Return up to 20 recent chat sessions sorted by last-updated descending."""
    return chats.list_sessions(request.app.state.workspace)


@api.get("/chats/{session_id}", summary="Get a chat session")
async def get_chat(request: Request, session_id: SpikeId) -> ChatSessionResponse:
    """Return the full chat session with all stored turns."""
    try:
        return chats.get_session(request.app.state.workspace, session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Chat session not found") from exc


# ---------------------------------------------------------------------------
# Health check route
# ---------------------------------------------------------------------------


@api.get("/wiki/health", summary="Wiki consistency health check")
async def wiki_health_check(request: Request) -> HealthReport:
    """Run a consistency check between spikes on disk and the wiki layer."""
    workspace: Path = request.app.state.workspace
    return health.run_health_check(workspace)


@api.get("/status", summary="LLM sync state and cumulative usage")
async def get_status() -> StatusResponse:
    """Return the current sync state and accumulated token/cost totals since server start."""
    return StatusResponse(
        syncing=_state.active_syncs > 0,
        total_cost_usd=_state.total_cost_usd,
        total_tokens=_state.total_tokens,
    )


@api.get("/braindump/log", summary="Recent activity log entries")
async def get_log(request: Request, lines: int = Query(50, ge=1, le=1000)) -> JSONResponse:
    """Return the last N log entries from ``wiki/logs/``.

    Reads ``.json`` (structured) and legacy ``.md`` files, sorted chronologically
    by filename, and returns a list of ``LogEntry``-shaped dicts.
    """
    ldir = dirs.log_dir(request.app.state.workspace)
    if not ldir.exists():
        return JSONResponse({"entries": []})
    all_files = sorted(ldir.glob("*.json")) + sorted(ldir.glob("*.md"))
    all_files = sorted(all_files)
    entries: list[dict] = []
    for f in all_files:
        text = f.read_text(encoding="utf-8").strip()
        if f.suffix == ".json":
            with contextlib.suppress(json.JSONDecodeError):
                entries.append(json.loads(text))
        else:
            # Legacy .md format: "- {ts}: {summary}"
            if text.startswith("- "):
                parts = text[2:].split(": ", 1)
                if len(parts) == 2:
                    entries.append({"ts": parts[0], "summary": parts[1], "detail": None})
    return JSONResponse({"entries": entries[-lines:]})


# ---------------------------------------------------------------------------
# WebSocket — real-time sync status
# ---------------------------------------------------------------------------


_WS_PING_INTERVAL = 25.0  # seconds; keeps proxies and browsers from dropping idle connections


@api.websocket("/ws")
async def ws_sync_status(ws: WebSocket) -> None:
    """Push sync-status events to connected clients."""
    await _ws_manager.connect(ws)
    try:
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=_WS_PING_INTERVAL)
            except TimeoutError:
                await ws.send_json({"type": "ping"})
    except (WebSocketDisconnect, Exception):
        _ws_manager.disconnect(ws)


app.include_router(api)

# ---------------------------------------------------------------------------
# Static frontend — served only when the dist build is present
# ---------------------------------------------------------------------------


def _check_dist() -> None:
    if not _DIST.exists():
        raise RuntimeError(f"Frontend dist not found at {_DIST}. Run `cd frontend && npm run build` first.")


if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

########################################################################################################################
# Implementation                                                                                                       #
########################################################################################################################

_CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
_CACHE_NO_STORE = "no-cache, no-store, must-revalidate"


class _ConnectionManager:
    """Tracks active WebSocket connections and broadcasts messages to all of them."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        with contextlib.suppress(ValueError):
            self._connections.remove(ws)

    async def broadcast(self, data: dict) -> None:
        for ws in list(self._connections):
            try:
                await ws.send_json(data)
            except Exception:
                self._connections.remove(ws)


_ws_manager = _ConnectionManager()

# Serialises all wiki file writes so concurrent spike updates don't overwrite
# each other's LLM output.  Acquired only around the LLM call + file write;
# the sync_start broadcast and counter increment intentionally happen before it
# so the frontend knows an update is queued even while another is in progress.
_wiki_lock = asyncio.Lock()


@dataclasses.dataclass
class _SyncState:
    """LLM sync counters — loaded from disk at startup and persisted after every update.

    Safe to mutate without locks under asyncio's single-threaded event loop
    because all mutations happen between awaits, never inside threads.
    """

    active_syncs: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0


_state = _SyncState()


def _save_usage(workspace: Path) -> None:
    """Persist the current usage counters to ``<workspace>/.config/usage.json``."""
    dirs.usage_path(workspace).write_text(
        UsageData(total_cost_usd=_state.total_cost_usd, total_tokens=_state.total_tokens).model_dump_json(),
        encoding="utf-8",
    )


async def _wiki_update_and_notify(
    workspace: Path,
    spike: SpikeResponse,
    braindump_data_dir: Path,
) -> None:
    """Call the LLM to update the wiki layer, then broadcast sync_done."""
    _state.active_syncs += 1
    await _ws_manager.broadcast({"type": "sync_start", "spike_id": spike.id})
    usage = wiki.WikiUsage(cost_usd=0.0, total_tokens=0)
    try:
        backend = load_backend(braindump_data_dir)
        async with _wiki_lock:
            usage = await wiki.update_wiki_for_spike(workspace, spike, backend)
    except Exception as exc:
        error_msg = str(exc)
        wiki.append_log(workspace, f"Sync failed for spike {spike.id} ({spike.title!r}): {error_msg}")
        await _ws_manager.broadcast({"type": "sync_error", "spike_id": spike.id, "error": error_msg})
    _state.active_syncs -= 1
    _state.total_cost_usd += usage.cost_usd
    _state.total_tokens += usage.total_tokens
    _save_usage(workspace)
    await _ws_manager.broadcast(
        {
            "type": "sync_done",
            "spike_id": spike.id,
            "syncing": _state.active_syncs > 0,
            "total_cost_usd": _state.total_cost_usd,
            "total_tokens": _state.total_tokens,
        }
    )


async def _wiki_remove_and_notify(
    workspace: Path,
    spike_id: str,
    braindump_data_dir: Path,
) -> None:
    """Call the LLM to remove the spike from the wiki layer, then broadcast sync_done."""
    _state.active_syncs += 1
    await _ws_manager.broadcast({"type": "sync_start", "spike_id": spike_id})
    usage = wiki.WikiUsage(cost_usd=0.0, total_tokens=0)
    try:
        backend = load_backend(braindump_data_dir)
        async with _wiki_lock:
            usage = await wiki.remove_spike_from_wiki(workspace, spike_id, backend)
    except Exception as exc:
        error_msg = str(exc)
        wiki.append_log(workspace, f"Sync failed for spike removal {spike_id}: {error_msg}")
        await _ws_manager.broadcast({"type": "sync_error", "spike_id": spike_id, "error": error_msg})
    _state.active_syncs -= 1
    _state.total_cost_usd += usage.cost_usd
    _state.total_tokens += usage.total_tokens
    _save_usage(workspace)
    await _ws_manager.broadcast(
        {
            "type": "sync_done",
            "spike_id": spike_id,
            "syncing": _state.active_syncs > 0,
            "total_cost_usd": _state.total_cost_usd,
            "total_tokens": _state.total_tokens,
        }
    )


_MAX_HEALTH_REPAIR_ITERATIONS = 3


async def _health_check_and_notify(workspace: Path, braindump_data_dir: Path) -> None:
    """Run a full health-check + repair cycle and broadcast sync status via WebSocket."""
    _state.active_syncs += 1
    await _ws_manager.broadcast({"type": "sync_start", "spike_id": None, "health_check": True})
    try:
        report = await asyncio.to_thread(health.run_health_check, workspace)
        async with _wiki_lock:
            for _ in range(_MAX_HEALTH_REPAIR_ITERATIONS):
                if not report.issues:
                    break
                backend = load_backend(braindump_data_dir)
                usage = await health.repair_inconsistencies(workspace, report, backend)
                _state.total_cost_usd += usage.cost_usd
                _state.total_tokens += usage.total_tokens
                _save_usage(workspace)
                report = await asyncio.to_thread(health.run_health_check, workspace)
    except Exception as exc:
        error_msg = str(exc)
        wiki.append_log(workspace, f"Health check failed: {error_msg}")
        await _ws_manager.broadcast({"type": "sync_error", "spike_id": None, "error": error_msg})
    _state.active_syncs -= 1
    await asyncio.to_thread(txlog.compact_transaction_log, workspace)
    await _ws_manager.broadcast(
        {
            "type": "sync_done",
            "spike_id": None,
            "syncing": _state.active_syncs > 0,
            "total_cost_usd": _state.total_cost_usd,
            "total_tokens": _state.total_tokens,
        }
    )


async def _health_check_loop(workspace: Path, braindump_data_dir: Path, interval_minutes: int) -> None:
    """Run health checks on a fixed interval, using the LLM to repair any inconsistencies."""
    while True:
        await asyncio.sleep(interval_minutes * 60)
        await _health_check_and_notify(workspace, braindump_data_dir)


@app.get("/assets/{file_path:path}", include_in_schema=False)
async def _serve_asset(file_path: str) -> FileResponse:
    """Serve a hashed asset with a 1-year immutable cache header."""
    _check_dist()
    assets_root = (_DIST / "assets").resolve()
    resolved = (assets_root / file_path).resolve()
    if not resolved.is_relative_to(assets_root):
        raise HTTPException(status_code=400, detail="Invalid path")
    return FileResponse(
        resolved,
        headers={"Cache-Control": _CACHE_IMMUTABLE},
    )


@app.get("/{full_path:path}", include_in_schema=False)
async def _serve_spa(full_path: str) -> FileResponse:
    """Catch-all: serve index.html for every non-API path (SPA routing)."""
    _check_dist()
    return FileResponse(
        _DIST / "index.html",
        headers={"Cache-Control": _CACHE_NO_STORE},
    )
