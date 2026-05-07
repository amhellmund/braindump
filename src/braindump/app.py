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
import re
import time
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

from braindump import chats, daily_summary, dirs, health, query, storage, stream_summary, txlog, wiki
from braindump import dailies as dailies_module
from braindump import streams as streams_module
from braindump.llm import load_backend
from braindump.types import (
    ChatSessionResponse,
    ChatSessionSummary,
    DailyInfo,
    DailySummaryResponse,
    HealthReport,
    ImageUploadResponse,
    InfoResponse,
    LLMConfig,
    LoginRequest,
    QueryRequest,
    QueryResponse,
    SpikePayload,
    SpikeResponse,
    StatusResponse,
    StreamInfo,
    StreamSummaryResponse,
    UsageData,
    WhoAmIResponse,
    WorkspaceVersions,
)
from braindump.users import UserRegistry

_logger = logging.getLogger(__name__)

# Path parameter type that enforces lowercase UUID v4 format.
_UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
SpikeId = Annotated[str, PathParam(pattern=_UUID_RE)]

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################

_DEV: bool = os.getenv("BRAINDUMP_DEV", "0") == "1"
_SESSION_COOKIE_NAME = "bd_session"
_SESSION_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days
# When installed from a wheel the frontend is bundled inside the package
# at braindump/frontend/dist/.  In an editable / source checkout it lives at
# the repo root under frontend/dist/.
_PKG_DIST: Path = Path(__file__).parent / "frontend" / "dist"
_DEV_DIST: Path = Path(__file__).parent.parent.parent / "frontend" / "dist"
_DIST: Path = _PKG_DIST if _PKG_DIST.exists() else _DEV_DIST

_DEFAULT_HEALTH_CHECK_INTERVAL_MINUTES = 60
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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
    app.state.login_rate_limiter = _LoginRateLimiter(max_attempts=10, window_seconds=60)

    users_file = dirs.users_path(workspace)
    if users_file.exists():
        registry = UserRegistry(users_file)
        registry.load()
        app.state.user_registry = registry
        app.state.multi_user = True
    else:
        app.state.user_registry = None
        app.state.multi_user = False

    health_task = asyncio.create_task(_health_check_loop(workspace, braindump_data_dir, interval_minutes))
    try:
        yield
    finally:
        health_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await health_task


app = FastAPI(
    title="braindump",
    version=importlib.metadata.version("braindump-ai"),
    lifespan=_lifespan,
    docs_url="/api/docs" if _DEV else None,
    redoc_url="/api/redoc" if _DEV else None,
)


@app.middleware("http")
async def _auth_middleware(request: Request, call_next: object) -> object:
    """Validate session cookies in multi-user mode; pass through in single-user mode."""
    if not request.app.state.multi_user:
        return await call_next(request)  # type: ignore[operator]

    # Public auth endpoints: mode detection and login itself need no cookie.
    if request.url.path in ("/api/v1/auth/mode", "/api/v1/auth/login"):
        return await call_next(request)  # type: ignore[operator]

    # Static assets and SPA fallback need no auth.
    if not request.url.path.startswith("/api/"):
        return await call_next(request)  # type: ignore[operator]

    token = request.cookies.get(_SESSION_COOKIE_NAME)
    user = request.app.state.user_registry.lookup(token or "")
    if user is None:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    request.state.user = user
    return await call_next(request)  # type: ignore[operator]


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
        WorkspaceVersions.model_validate_json(path.read_text(encoding="utf-8"))
        if path.exists()
        else WorkspaceVersions()
    )
    return InfoResponse(
        version=importlib.metadata.version("braindump-ai"),
        wiki_schema=versions.wiki_schema,
        meta=versions.meta,
        streams=versions.streams,
        dailies=versions.dailies,
    )


@api.get("/health", summary="Health check")
async def health_status(request: Request) -> JSONResponse:
    """Return service health status and the active workspace path."""
    return JSONResponse({"status": "ok", "dev": _DEV, "workspace": str(request.app.state.workspace)})


@api.get("/auth/mode", summary="Auth mode", include_in_schema=False)
async def auth_mode(request: Request) -> JSONResponse:
    """Return whether multi-user auth is enabled. No cookie required."""
    return JSONResponse({"multi_user": request.app.state.multi_user})


@api.post("/auth/login", summary="Exchange token for session cookie", include_in_schema=False)
async def auth_login(request: Request, body: LoginRequest) -> JSONResponse:
    """Validate a bearer token and issue an HttpOnly session cookie."""
    if not request.app.state.multi_user:
        return JSONResponse({"detail": "Not in multi-user mode"}, status_code=400)
    client_ip = request.client.host if request.client else "unknown"
    if not request.app.state.login_rate_limiter.is_allowed(client_ip):
        return JSONResponse({"detail": "Too many attempts"}, status_code=429)
    user = request.app.state.user_registry.lookup(body.token)
    if user is None:
        return JSONResponse({"detail": "Invalid token"}, status_code=401)
    is_secure = request.url.scheme == "https"
    response = JSONResponse(WhoAmIResponse(username=user.username).model_dump())
    response.set_cookie(
        key=_SESSION_COOKIE_NAME,
        value=body.token,
        httponly=True,
        samesite="strict",
        secure=is_secure,
        max_age=_SESSION_COOKIE_MAX_AGE,
        path="/",
    )
    return response


@api.post("/auth/logout", summary="Invalidate session cookie", include_in_schema=False)
async def auth_logout(request: Request) -> JSONResponse:
    """Clear the session cookie."""
    is_secure = request.url.scheme == "https"
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(
        key=_SESSION_COOKIE_NAME,
        path="/",
        samesite="strict",
        secure=is_secure,
        httponly=True,
    )
    return response


@api.get("/auth/whoami", summary="Return current user from session cookie", include_in_schema=False)
async def auth_whoami(request: Request) -> JSONResponse:
    """Return the username for the current session; 401 if not authenticated."""
    if not request.app.state.multi_user:
        return JSONResponse({"detail": "Not in multi-user mode"}, status_code=400)
    return JSONResponse(WhoAmIResponse(username=request.state.user.username).model_dump())


# ---------------------------------------------------------------------------
# Spike routes
# ---------------------------------------------------------------------------


@api.get("/spikes", summary="List all spikes")
async def list_spikes(request: Request) -> list[SpikeResponse]:
    """Return all spikes from the metadata cache, most-recently modified first."""
    workspace: Path = request.app.state.workspace

    entries = wiki.list_all_meta(workspace)
    assignments = streams_module.read_assignments(workspace)
    result: list[SpikeResponse] = []
    for entry in entries:
        try:
            raw = storage.read_spike_raw(workspace, entry.id)
        except FileNotFoundError:
            continue  # skip entries whose files were removed outside the app
        spike = storage.parse_spike(raw, entry.id)
        spike.stream = assignments.assignments.get(entry.id)
        spike.wikiPending = entry.wiki_pending
        result.append(spike)
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

    if body.stream:
        streams_module.set_spike_stream(workspace, spike_id, body.stream)
    spike.stream = body.stream or None

    wiki.update_meta_json(workspace, spike, wiki_pending=not body.update_wiki)
    spike.wikiPending = not body.update_wiki

    if body.update_wiki:
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
    spike = storage.parse_spike(raw, spike_id)
    spike.stream = streams_module.get_spike_stream(workspace, spike_id)
    return spike


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
    if body.expected_modified_at is not None and existing.modifiedAt != body.expected_modified_at:
        raise HTTPException(
            status_code=409,
            detail=f"Spike was modified at {existing.modifiedAt}; client expected {body.expected_modified_at}",
        )
    now = datetime.now(UTC).isoformat()
    raw = storage.enrich_spike(body.raw, existing.createdAt, now)
    storage.write_spike(workspace, spike_id, raw)
    spike = storage.parse_spike(raw, spike_id)

    if body.stream:
        streams_module.set_spike_stream(workspace, spike_id, body.stream)
        spike.stream = body.stream
    elif body.stream is None and "stream" in body.model_fields_set:
        streams_module.remove_spike_stream(workspace, spike_id)
        spike.stream = None
    else:
        spike.stream = streams_module.get_spike_stream(workspace, spike_id)

    wiki.update_meta_json(workspace, spike, wiki_pending=not body.update_wiki)
    spike.wikiPending = not body.update_wiki

    if body.update_wiki:
        bg.add_task(_wiki_update_and_notify, workspace, spike, braindump_data_dir)
    return spike


@api.delete("/spikes/{spike_id}", summary="Delete a spike", status_code=204)
async def delete_spike(request: Request, spike_id: SpikeId, bg: BackgroundTasks) -> None:
    """Remove a spike from disk and schedule its removal from the wiki layer."""
    workspace: Path = request.app.state.workspace

    try:
        storage.read_spike_raw(workspace, spike_id)  # existence check
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Spike not found") from exc

    storage.delete_spike_file(workspace, spike_id)
    # Remove from meta.json immediately so the spike disappears from listings at once.
    wiki.remove_from_meta_json(workspace, spike_id)
    streams_module.remove_spike_stream(workspace, spike_id)

    bg.add_task(_wiki_remove_and_notify, workspace, spike_id)


@api.post("/spikes/{spike_id}/update-wiki", summary="Trigger wiki update for one spike", status_code=202)
async def trigger_spike_wiki_update(request: Request, spike_id: SpikeId, bg: BackgroundTasks) -> dict[str, int]:
    """Queue a wiki update for a single spike that has a pending wiki update."""
    workspace: Path = request.app.state.workspace
    braindump_data_dir: Path = request.app.state.braindump_data_dir

    try:
        raw = storage.read_spike_raw(workspace, spike_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Spike not found") from exc

    spike = storage.parse_spike(raw, spike_id)
    spike.stream = streams_module.get_spike_stream(workspace, spike_id)
    bg.add_task(_wiki_update_and_notify, workspace, spike, braindump_data_dir)
    return {"queued": 1}


@api.post("/wiki/trigger-pending", summary="Trigger wiki updates for all pending spikes", status_code=202)
async def trigger_pending_wiki_updates(request: Request, bg: BackgroundTasks) -> dict[str, int]:
    """Queue wiki updates for all spikes saved without a wiki update."""
    workspace: Path = request.app.state.workspace
    braindump_data_dir: Path = request.app.state.braindump_data_dir

    pending_ids = wiki.list_pending_spike_ids(workspace)
    for spike_id in pending_ids:
        try:
            raw = storage.read_spike_raw(workspace, spike_id)
        except FileNotFoundError:
            continue
        spike = storage.parse_spike(raw, spike_id)
        spike.stream = streams_module.get_spike_stream(workspace, spike_id)
        bg.add_task(_wiki_update_and_notify, workspace, spike, braindump_data_dir)
    return {"queued": len(pending_ids)}


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


# ---------------------------------------------------------------------------
# Stream routes
# ---------------------------------------------------------------------------


@api.get("/streams", summary="List all named streams with metadata")
async def list_streams(request: Request) -> list[StreamInfo]:
    """Return all named streams with spike counts and summary state."""
    workspace: Path = request.app.state.workspace
    streams_data = streams_module.read_streams(workspace)
    assignments = streams_module.read_assignments(workspace)

    spike_counts: dict[str, int] = {}
    for sname in assignments.assignments.values():
        spike_counts[sname] = spike_counts.get(sname, 0) + 1

    result: list[StreamInfo] = []
    for name, meta in streams_data.streams.items():
        pending = meta.summary_at is None or meta.modified_at > meta.summary_at
        result.append(
            StreamInfo(
                name=name,
                created_at=meta.created_at,
                modified_at=meta.modified_at,
                summary_at=meta.summary_at,
                spike_count=spike_counts.get(name, 0),
                summary_pending=pending,
            )
        )
    result.sort(key=lambda s: s.modified_at, reverse=True)
    return result


@api.get("/streams/{stream_name}/summary", summary="Get stored summary for a stream")
async def get_stream_summary(request: Request, stream_name: str) -> StreamSummaryResponse:
    """Return the stored summary markdown for a named stream.

    Returns 404 if the stream does not exist or no summary has been generated yet.
    """
    workspace: Path = request.app.state.workspace
    streams_data = streams_module.read_streams(workspace)
    if stream_name not in streams_data.streams:
        raise HTTPException(status_code=404, detail="Stream not found")
    content = streams_module.read_summary(workspace, stream_name)
    if content is None:
        raise HTTPException(status_code=404, detail="No summary generated yet")
    meta = streams_data.streams[stream_name]
    return StreamSummaryResponse(
        stream_name=stream_name,
        content=content,
        generated_at=meta.summary_at or "",
    )


@api.post("/streams/{stream_name}/summarize", summary="Trigger background AI summary for a stream", status_code=202)
async def summarize_stream(request: Request, stream_name: str, bg: BackgroundTasks) -> dict[str, int]:
    """Queue a background AI summary generation for the named stream.

    Returns 404 if the stream does not exist, 422 if it has no spikes.
    """
    workspace: Path = request.app.state.workspace
    braindump_data_dir: Path = request.app.state.braindump_data_dir

    streams_data = streams_module.read_streams(workspace)
    if stream_name not in streams_data.streams:
        raise HTTPException(status_code=404, detail="Stream not found")

    assignments = streams_module.read_assignments(workspace)
    spike_ids = [sid for sid, sname in assignments.assignments.items() if sname == stream_name]
    if not spike_ids:
        raise HTTPException(status_code=422, detail=f"Stream '{stream_name}' has no spikes")

    bg.add_task(_stream_summary_and_notify, workspace, stream_name, braindump_data_dir)
    return {"queued": 1}


# ---------------------------------------------------------------------------
# Dailies routes
# ---------------------------------------------------------------------------


@api.get("/dailies", summary="List all days with spike activity")
async def list_dailies(request: Request) -> list[DailyInfo]:
    """Return all days that have spikes, with spike counts and summary state."""
    workspace: Path = request.app.state.workspace
    all_meta = wiki.list_all_meta(workspace)

    day_spikes: dict[str, list[str]] = {}
    day_max_modified: dict[str, str] = {}
    for entry in all_meta:
        date = _spike_date(entry.created_at)
        if not date:
            continue
        day_spikes.setdefault(date, []).append(entry.id)
        prev = day_max_modified.get(date, "")
        if entry.modified_at > prev:
            day_max_modified[date] = entry.modified_at

    dailies_data = dailies_module.read_dailies(workspace)

    result: list[DailyInfo] = []
    for date, spike_ids in day_spikes.items():
        meta = dailies_data.dailies.get(date)
        summary_at = meta.summary_at if meta else None
        max_modified = day_max_modified.get(date, "")
        pending = summary_at is None or max_modified > summary_at
        result.append(
            DailyInfo(
                date=date,
                spike_count=len(spike_ids),
                summary_at=summary_at,
                summary_pending=pending,
            )
        )

    result.sort(key=lambda d: d.date, reverse=True)
    return result


@api.get("/dailies/{date}/summary", summary="Get stored summary for a day")
async def get_daily_summary(request: Request, date: str) -> DailySummaryResponse:
    """Return the stored summary markdown for a given day.

    Returns 404 if no summary has been generated yet for that date.
    """
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="Invalid date format")
    workspace: Path = request.app.state.workspace
    content = dailies_module.read_daily_summary(workspace, date)
    if content is None:
        raise HTTPException(status_code=404, detail="No summary generated yet")
    dailies_data = dailies_module.read_dailies(workspace)
    meta = dailies_data.dailies.get(date)
    return DailySummaryResponse(
        date=date,
        content=content,
        generated_at=meta.summary_at or "" if meta else "",
    )


@api.post("/dailies/{date}/summarize", summary="Trigger background AI summary for a day", status_code=202)
async def summarize_daily(request: Request, date: str, bg: BackgroundTasks) -> dict[str, int]:
    """Queue a background AI summary generation for the given day.

    Returns 422 if the day has no spikes.
    """
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="Invalid date format")
    workspace: Path = request.app.state.workspace
    braindump_data_dir: Path = request.app.state.braindump_data_dir

    all_meta = wiki.list_all_meta(workspace)
    spike_ids = [m.id for m in all_meta if _spike_date(m.created_at) == date]
    if not spike_ids:
        raise HTTPException(status_code=422, detail=f"No spikes found for date '{date}'")

    bg.add_task(_daily_summary_and_notify, workspace, date, braindump_data_dir)
    return {"queued": 1}


@api.get("/wiki/health", summary="Wiki consistency health check")
async def wiki_health_check(request: Request) -> HealthReport:
    """Run a consistency check between spikes on disk and the wiki layer."""
    workspace: Path = request.app.state.workspace
    return health.run_health_check(workspace)


@api.post("/wiki/repair", summary="Trigger immediate wiki health check and repair", status_code=202)
async def trigger_wiki_repair(request: Request, bg: BackgroundTasks) -> dict[str, str]:
    """Queue an immediate health-check and repair cycle for the wiki layer."""
    workspace: Path = request.app.state.workspace
    braindump_data_dir: Path = request.app.state.braindump_data_dir
    bg.add_task(_health_check_and_notify, workspace, braindump_data_dir)
    return {"status": "queued"}


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
    if ws.app.state.multi_user:
        token = ws.cookies.get(_SESSION_COOKIE_NAME)
        user = ws.app.state.user_registry.lookup(token or "")
        if user is None:
            await ws.close(code=1008)
            return
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


@dataclasses.dataclass
class _RateLimitEntry:
    attempts: int
    window_start: float


class _LoginRateLimiter:
    """In-memory rate limiter: max N login attempts per IP per sliding window."""

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._entries: dict[str, _RateLimitEntry] = {}

    def is_allowed(self, ip: str) -> bool:
        """Return True and record the attempt if the IP is within its quota."""
        now = time.monotonic()
        entry = self._entries.get(ip)
        if entry is None or (now - entry.window_start) >= self._window:
            self._entries[ip] = _RateLimitEntry(attempts=1, window_start=now)
            return True
        if entry.attempts < self._max:
            entry.attempts += 1
            return True
        return False


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


def _spike_date(created_at: str) -> str:
    """Extract the UTC date (YYYY-MM-DD) from an ISO-8601 timestamp, or '' on error."""
    try:
        return datetime.fromisoformat(created_at).date().isoformat()
    except (ValueError, AttributeError):
        return ""


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
        wiki.update_meta_json(workspace, spike, wiki_pending=True)
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


async def _stream_summary_and_notify(
    workspace: Path,
    stream_name: str,
    braindump_data_dir: Path,
) -> None:
    """Call the LLM to generate a stream summary, then broadcast stream_summary_done."""
    _state.active_syncs += 1
    await _ws_manager.broadcast({"type": "stream_summary_start", "stream_name": stream_name})
    try:
        backend = load_backend(braindump_data_dir)
        async with _wiki_lock:
            await stream_summary.generate_stream_summary(workspace, stream_name, backend)
    except Exception as exc:
        error_msg = str(exc)
        wiki.append_log(workspace, f"Stream summary failed for '{stream_name}': {error_msg}")
        await _ws_manager.broadcast({"type": "sync_error", "spike_id": None, "error": error_msg})
    _state.active_syncs -= 1
    await _ws_manager.broadcast(
        {
            "type": "stream_summary_done",
            "stream_name": stream_name,
            "syncing": _state.active_syncs > 0,
        }
    )


async def _daily_summary_and_notify(
    workspace: Path,
    date: str,
    braindump_data_dir: Path,
) -> None:
    """Call the LLM to generate a daily summary, then broadcast daily_summary_done."""
    _state.active_syncs += 1
    await _ws_manager.broadcast({"type": "daily_summary_start", "date": date})
    try:
        backend = load_backend(braindump_data_dir)
        async with _wiki_lock:
            await daily_summary.generate_daily_summary(workspace, date, backend)
    except Exception as exc:
        error_msg = str(exc)
        wiki.append_log(workspace, f"Daily summary failed for '{date}': {error_msg}")
        await _ws_manager.broadcast({"type": "sync_error", "spike_id": None, "error": error_msg})
    _state.active_syncs -= 1
    await _ws_manager.broadcast(
        {
            "type": "daily_summary_done",
            "date": date,
            "syncing": _state.active_syncs > 0,
        }
    )


async def _wiki_remove_and_notify(
    workspace: Path,
    spike_id: str,
) -> None:
    """Remove the spike from the wiki layer, then broadcast sync_done."""
    _state.active_syncs += 1
    await _ws_manager.broadcast({"type": "sync_start", "spike_id": spike_id})
    usage = wiki.WikiUsage(cost_usd=0.0, total_tokens=0)
    try:
        async with _wiki_lock:
            usage = await wiki.remove_spike_from_wiki(workspace, spike_id)
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
