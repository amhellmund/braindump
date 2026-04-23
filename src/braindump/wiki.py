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

"""LLM-managed wiki layer — index, connections, hierarchy, and metadata cache.

The wiki/ directory contains:
- SCHEMA.md      — LLM operational guidelines (written once by braindump init)
- index.md       — LLM-authored catalog: one entry per spike with a rich summary
- connections.md — LLM-derived explicit links between related spikes
- hierarchy.md   — LLM-managed thematic community groupings (replaces Louvain)
- meta.json      — Fast metadata cache: spike_id → {title, tags, created_at, modified_at}
- log.md         — Append-only event log

All file content is authoritative human-readable markdown; meta.json is a derived cache
rebuilt automatically on every create/update/delete without LLM involvement.
"""

import asyncio
import re
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import NamedTuple

from pydantic import TypeAdapter

from braindump import txlog
from braindump.dirs import (
    connections_path,
    hierarchy_path,
    index_path,
    log_dir,
    meta_json_path,
    schema_path,
    versions_path,
    wiki_dir,
)
from braindump.llm import ChatBackend
from braindump.migrations import CURRENT_VERSIONS
from braindump.streams import init_streams
from braindump.types import (
    LogDetail,
    LogEntry,
    SpikeMeta,
    SpikeMetaEntry,
    SpikeResponse,
    WikiRemoveLogDetail,
    WikiUpdateLogDetail,
)


class WikiUsage(NamedTuple):
    """Accumulated LLM usage across a single wiki update operation."""

    cost_usd: float
    total_tokens: int


########################################################################################################################
# Constants                                                                                                            #
########################################################################################################################

_TEMPORAL_WINDOW_DAYS = 7

# UUID pattern used when parsing hierarchy.md and connections.md
_UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

CONNECTION_RE = re.compile(rf"^-\s*({_UUID_RE})\s*<->\s*({_UUID_RE})(?:\s*:\s*(.*))?$")

_SCHEMA_CONTENT = """\
# Braindump Wiki Manager Schema

You are the wiki manager for **braindump**, a personal knowledge base made of Markdown notes called "spikes".
You maintain three files that form an evolving knowledge layer derived from the raw spikes.

## Files You Manage

### index.md
A catalog of every spike. Each spike occupies one section:

```
## {spike-uuid}
**Title:** {title}
**Tags:** {tag1}, {tag2}
**Created:** {ISO-8601 timestamp}
**Summary:** 2-3 sentences describing the spike's key ideas, techniques, and insights.
**Code:** One sentence describing what the code does and which language(s) are used. Omit if no fenced code blocks.
**Related:** {uuid-a}, {uuid-b}   ← omit this line if no related spikes
```

### connections.md
Explicit semantic connections between spikes. One connection per line:

```
- {uuid-a} <-> {uuid-b}: {one-sentence reason explaining the connection}
```

### hierarchy.md
Thematic communities that cluster spikes by topic:

```
## Community: {Descriptive 2-4 Word Name}
- {uuid} ({short title or topic phrase})
- {uuid} ({short title or topic phrase})
```

## Rules
1. When asked to update a file, output **only** the complete updated file —
   no preamble, no explanation, no markdown code fences around the whole file.
2. Preserve all existing entries exactly as they are, unless you are updating the specific spike you were given.
3. Spike IDs are UUIDs — copy them character-for-character, no abbreviation.
4. Summaries in index.md must be rich enough that a reader can answer questions
   about the spike without reading the original.
5. Assign every spike to exactly one community in hierarchy.md. Create a new community when no existing one fits well.
6. Only record a connection in connections.md when there is a clear semantic relationship:
   shared concepts, complementary techniques, contradictions, or dependency.
7. The **Related:** line in index.md should list UUIDs of spikes that share
   a meaningful connection — keep it to the 3 most relevant.
8. If the spike contains fenced code blocks, add a **Code:** line after **Summary:**
   that describes in one sentence what the code does and which language(s) are used.
   Omit the field entirely when the spike has no code blocks.
"""

########################################################################################################################
# Initialisation                                                                                                       #
########################################################################################################################


def init_wiki(workspace: Path) -> None:
    """Create the wiki directory and seed empty files if they do not yet exist.

    Safe to call on every server startup — existing files are never overwritten.

    Args:
        workspace: Root workspace directory.
    """
    wdir = wiki_dir(workspace)
    wdir.mkdir(exist_ok=True)

    _write_if_missing(schema_path(workspace), _SCHEMA_CONTENT)
    _write_if_missing(index_path(workspace), "# Braindump Index\n\nNo spikes yet.\n")
    _write_if_missing(connections_path(workspace), "# Spike Connections\n\n")
    _write_if_missing(hierarchy_path(workspace), "# Spike Hierarchy\n\n")
    _write_if_missing(meta_json_path(workspace), "{}\n")
    log_dir(workspace).mkdir(exist_ok=True)
    init_streams(workspace)


def init_versions(workspace: Path) -> None:
    """Write ``versions.json`` to the workspace root if it does not yet exist.

    Safe to call on every ``braindump init`` — an existing file is never overwritten.

    Args:
        workspace: Root workspace directory.
    """
    path = versions_path(workspace)
    if not path.exists():
        path.write_text(CURRENT_VERSIONS.model_dump_json(indent=2), encoding="utf-8")


########################################################################################################################
# Metadata Cache (no LLM)                                                                                              #
########################################################################################################################


def read_meta(workspace: Path) -> dict[str, SpikeMeta]:
    """Read ``braindump/meta.json`` and return the full metadata mapping.

    Args:
        workspace: Root workspace directory.

    Returns:
        Mapping of ``spike_id → :class:`~braindump.models.SpikeMeta```.
    """
    return _read_meta_json(meta_json_path(workspace))


def update_meta_json(workspace: Path, spike: SpikeResponse) -> None:
    """Add or replace a spike's metadata entry in ``braindump/meta.json``.

    This is a pure filesystem operation — no LLM involved.

    Args:
        workspace: Root workspace directory.
        spike: The spike whose metadata should be synced.
    """
    path = meta_json_path(workspace)
    meta = _read_meta_json(path)
    meta[spike.id] = SpikeMeta(
        title=spike.title,
        tags=spike.tags,
        created_at=spike.createdAt,
        modified_at=spike.modifiedAt,
        languages=spike.languages,
        image_count=spike.image_count,
    )
    _write_meta_json(path, meta)


def remove_from_meta_json(workspace: Path, spike_id: str) -> None:
    """Remove a spike's entry from ``braindump/meta.json``.

    Args:
        workspace: Root workspace directory.
        spike_id: UUID of the spike to remove.
    """
    path = meta_json_path(workspace)
    meta = _read_meta_json(path)
    meta.pop(spike_id, None)
    _write_meta_json(path, meta)


def list_all_meta(workspace: Path) -> list[SpikeMetaEntry]:
    """Return all spike metadata entries sorted by ``modified_at`` descending.

    Args:
        workspace: Root workspace directory.

    Returns:
        List of :class:`~braindump.models.SpikeMetaEntry` objects, newest first.
    """
    meta = _read_meta_json(meta_json_path(workspace))
    entries = [SpikeMetaEntry(id=sid, **data.model_dump()) for sid, data in meta.items()]
    entries.sort(key=lambda e: e.modified_at, reverse=True)
    return entries


########################################################################################################################
# LLM-Driven Wiki Updates                                                                                              #
########################################################################################################################


async def update_wiki_for_spike(workspace: Path, spike: SpikeResponse, backend: ChatBackend) -> WikiUsage:
    """Update the full wiki layer for a created or modified spike.

    Immediately updates ``braindump/meta.json`` (no LLM), then calls the LLM to update
    ``braindump/index.md``, ``braindump/connections.md``, and ``braindump/hierarchy.md`` in sequence.

    Args:
        workspace: Root workspace directory.
        spike: The spike that was created or modified.
        backend: Active LLM backend.

    Returns:
        :class:`WikiUsage` with the accumulated cost and token count across all LLM calls.
    """
    update_meta_json(workspace, spike)

    schema = schema_path(workspace).read_text(encoding="utf-8")
    total_cost = 0.0
    total_tokens = 0
    total_prompt_chars = 0

    txid = txlog.begin_transaction(workspace, txlog.TxOp.UPDATE_SPIKE, spike.id)

    # 1. Update index.md
    current_index = index_path(workspace).read_text(encoding="utf-8")
    index_prompt = _index_update_prompt(current_index, spike)
    total_prompt_chars += len(index_prompt)
    result = await asyncio.to_thread(
        backend.complete_with_usage,
        schema,
        [],
        index_prompt,
    )
    new_index_text = result.text.strip() + "\n"
    index_path(workspace).write_text(new_index_text, encoding="utf-8")
    total_cost += result.cost_usd
    total_tokens += result.total_tokens
    txlog.record_step(workspace, txid, txlog.TxEvent.STEP_INDEX)

    # 2. Update connections.md (gets index.md as context about other spikes)
    updated_index = index_path(workspace).read_text(encoding="utf-8")
    current_connections = connections_path(workspace).read_text(encoding="utf-8")
    connections_prompt = _connections_update_prompt(current_connections, updated_index, spike)
    total_prompt_chars += len(connections_prompt)
    result = await asyncio.to_thread(
        backend.complete_with_usage,
        schema,
        [],
        connections_prompt,
    )
    new_connections_text = result.text.strip() + "\n"
    connections_path(workspace).write_text(new_connections_text, encoding="utf-8")
    total_cost += result.cost_usd
    total_tokens += result.total_tokens
    txlog.record_step(workspace, txid, txlog.TxEvent.STEP_CONNECTIONS)

    # 3. Update hierarchy.md
    current_hierarchy = hierarchy_path(workspace).read_text(encoding="utf-8")
    hierarchy_prompt = _hierarchy_update_prompt(
        current_hierarchy, spike, _extract_index_section(new_index_text, spike.id)
    )
    total_prompt_chars += len(hierarchy_prompt)
    result = await asyncio.to_thread(
        backend.complete_with_usage,
        schema,
        [],
        hierarchy_prompt,
    )
    new_hierarchy_text = result.text.strip() + "\n"
    hierarchy_path(workspace).write_text(new_hierarchy_text, encoding="utf-8")
    total_cost += result.cost_usd
    total_tokens += result.total_tokens
    txlog.record_step(workspace, txid, txlog.TxEvent.STEP_HIERARCHY)

    txlog.commit_transaction(workspace, txid)
    detail = WikiUpdateLogDetail(
        spike_id=spike.id,
        spike_title=spike.title,
        index_section=_extract_index_section(new_index_text, spike.id),
        connections_lines=_extract_connection_lines(new_connections_text, spike.id),
        hierarchy_section=_extract_hierarchy_section(new_hierarchy_text, spike.id),
        cost_usd=total_cost,
        total_tokens=total_tokens,
        system_prompt_chars=len(schema),
        prompt_chars=total_prompt_chars,
    )
    append_log(workspace, f"Updated wiki for spike {spike.id} ({spike.title!r})", detail)
    return WikiUsage(cost_usd=total_cost, total_tokens=total_tokens)


async def remove_spike_from_wiki(workspace: Path, spike_id: str, backend: ChatBackend) -> WikiUsage:
    """Remove a spike from the wiki layer.

    Immediately removes the entry from ``braindump/meta.json``, then calls the LLM to
    clean up ``braindump/index.md``, ``braindump/connections.md``, and ``braindump/hierarchy.md``.

    Args:
        workspace: Root workspace directory.
        spike_id: UUID of the spike to remove.
        backend: Active LLM backend.

    Returns:
        :class:`WikiUsage` with the accumulated cost and token count across all LLM calls.
    """
    remove_from_meta_json(workspace, spike_id)

    schema = schema_path(workspace).read_text(encoding="utf-8")
    removal_prompt = (
        f"Remove all references to spike ID `{spike_id}` from the file below. "
        "Output only the complete updated file — no preamble, no explanation.\n\n"
    )
    total_cost = 0.0
    total_tokens = 0
    total_prompt_chars = 0

    txid = txlog.begin_transaction(workspace, txlog.TxOp.REMOVE_SPIKE, spike_id)

    for wiki_file_path, step in (
        (index_path(workspace), txlog.TxEvent.STEP_INDEX),
        (connections_path(workspace), txlog.TxEvent.STEP_CONNECTIONS),
        (hierarchy_path(workspace), txlog.TxEvent.STEP_HIERARCHY),
    ):
        current = wiki_file_path.read_text(encoding="utf-8")
        prompt = removal_prompt + current
        total_prompt_chars += len(prompt)
        result = await asyncio.to_thread(
            backend.complete_with_usage,
            schema,
            [],
            prompt,
        )
        wiki_file_path.write_text(result.text.strip() + "\n", encoding="utf-8")
        total_cost += result.cost_usd
        total_tokens += result.total_tokens
        txlog.record_step(workspace, txid, step)

    txlog.commit_transaction(workspace, txid)
    append_log(
        workspace,
        f"Removed spike {spike_id} from wiki",
        WikiRemoveLogDetail(
            spike_id=spike_id,
            cost_usd=total_cost,
            total_tokens=total_tokens,
            system_prompt_chars=len(schema),
            prompt_chars=total_prompt_chars,
        ),
    )
    return WikiUsage(cost_usd=total_cost, total_tokens=total_tokens)


########################################################################################################################
# Graph Derivation                                                                                                     #
########################################################################################################################


def get_graph(workspace: Path, zoom: int) -> dict[str, list[dict]]:
    """Derive Cytoscape-compatible graph data from the wiki markdown files.

    Zoom levels:
    - 0: Cluster/macro view — one node per community in ``braindump/hierarchy.md``
    - 1: Mid view — cluster nodes + spike nodes with cluster membership edges
    - 2: Spike view — spike nodes + tag, semantic, and temporal edges (default)

    Args:
        workspace: Root workspace directory.
        zoom: Requested zoom level (0-2).

    Returns:
        Dict with ``nodes`` and ``edges`` lists ready for the Cytoscape frontend.
    """
    meta = _read_meta_json(meta_json_path(workspace))
    communities = parse_hierarchy(hierarchy_path(workspace))
    connections = parse_connections(connections_path(workspace), set(meta))

    if zoom <= 1:
        return _build_cluster_graph(meta, communities, zoom)
    return _build_spike_graph(meta, communities, connections)


########################################################################################################################
# Log                                                                                                                  #
########################################################################################################################


def append_log(workspace: Path, summary: str, detail: LogDetail | None = None) -> None:
    """Write a structured log entry to an individual JSON file in ``wiki/logs/``.

    Each call creates one ``YYYY-MM-DDTHH-MM-SS-ffffff.json`` file so that log
    entries are individually addressable and the directory can be sorted
    chronologically by filename.

    Args:
        workspace: Root workspace directory.
        summary: Human-readable description of the event.
        detail: Optional structured detail payload for the entry.
    """
    now = datetime.now(UTC)
    ts = now.isoformat()
    filename = now.strftime("%Y-%m-%dT%H-%M-%S-") + f"{now.microsecond:06d}.json"
    ldir = log_dir(workspace)
    ldir.mkdir(exist_ok=True)
    entry = LogEntry(ts=ts, summary=summary, detail=detail)
    (ldir / filename).write_text(entry.model_dump_json(), encoding="utf-8")


def _extract_index_section(text: str, spike_id: str) -> str:
    """Extract the ``## {spike_id}`` section from an index.md file text."""
    lines = text.splitlines()
    heading = f"## {spike_id}"
    inside = False
    section: list[str] = []
    for line in lines:
        if line.strip() == heading:
            inside = True
            section.append(line)
        elif inside:
            if line.startswith("## ") and line.strip() != heading:
                break
            section.append(line)
    return "\n".join(section).strip()


def _extract_connection_lines(text: str, spike_id: str) -> list[str]:
    """Return all non-empty lines in a connections.md text that mention *spike_id*."""
    return [line for line in text.splitlines() if spike_id in line and line.strip()]


def _extract_hierarchy_section(text: str, spike_id: str) -> str:
    """Return the full ``## Community: …`` block that contains *spike_id*.

    Collects the community heading and all its bullet lines.  Returns an empty
    string if the spike is not found in any community.
    """
    lines = text.splitlines()
    current_heading: str = ""
    current_section: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Community:"):
            current_heading = line
            current_section = [line]
        elif stripped.startswith("## "):
            current_heading = ""
            current_section = []
        elif current_heading:
            current_section.append(line)
            if stripped.lstrip("- ").strip().startswith(spike_id):
                return "\n".join(current_section).strip()
    return ""


########################################################################################################################
# Implementation                                                                                                       #
########################################################################################################################


_META_ADAPTER: TypeAdapter[dict[str, SpikeMeta]] = TypeAdapter(dict[str, SpikeMeta])


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _read_meta_json(path: Path) -> dict[str, SpikeMeta]:
    if not path.exists():
        return {}
    try:
        return _META_ADAPTER.validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _write_meta_json(path: Path, meta: dict[str, SpikeMeta]) -> None:
    path.write_text(_META_ADAPTER.dump_json(meta, indent=2).decode(), encoding="utf-8")


def parse_hierarchy(path: Path) -> dict[str, tuple[int, str]]:
    """Parse ``hierarchy.md`` into a spike_id → (community_index, community_name) mapping."""
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    result: dict[str, tuple[int, str]] = {}
    community_index = -1
    current_name = ""
    uuid_re = re.compile(rf"^-\s*({_UUID_RE})")
    for line in content.splitlines():
        if line.startswith("## Community:"):
            community_index += 1
            current_name = line.removeprefix("## Community:").strip()
        elif current_name and line.strip().startswith("-"):
            m = uuid_re.match(line.strip())
            if m:
                result[m.group(1)] = (community_index, current_name)
    return result


def parse_connections(path: Path, valid_ids: set[str]) -> list[tuple[str, str]]:
    """Parse ``connections.md`` and return valid (source, target) UUID pairs."""
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    result: list[tuple[str, str]] = []
    for line in content.splitlines():
        m = CONNECTION_RE.match(line.strip())
        if m:
            a, b = m.group(1), m.group(2)
            if a in valid_ids and b in valid_ids and a != b:
                result.append((a, b))
    return result


def _build_spike_graph(
    meta: dict[str, SpikeMeta],
    communities: dict[str, tuple[int, str]],
    connections: list[tuple[str, str]],
) -> dict:
    """Build the spike-level graph (zoom 2)."""
    nodes = []
    for spike_id, data in meta.items():
        nodes.append(
            {
                "id": spike_id,
                "label": data.title or spike_id,
                "type": "spike",
                "tags": data.tags,
                "zoomLevel": 2,
            }
        )

    edges: list[dict] = []
    edge_id = 0
    spike_ids = list(meta)

    # Tag edges — spikes sharing at least one tag
    for a, b in combinations(spike_ids, 2):
        if set(meta[a].tags) & set(meta[b].tags):
            edges.append({"id": f"e{edge_id}", "source": a, "target": b, "type": "tag"})
            edge_id += 1

    # Semantic edges — explicit LLM connections from connections.md
    seen_semantic: set[frozenset[str]] = set()
    for a, b in connections:
        key = frozenset({a, b})
        if key not in seen_semantic:
            seen_semantic.add(key)
            edges.append({"id": f"e{edge_id}", "source": a, "target": b, "type": "semantic"})
            edge_id += 1

    # Temporal edges — spikes created within the configured window
    for a, b in combinations(spike_ids, 2):
        ca = meta[a].created_at
        cb = meta[b].created_at
        if ca and cb and _within_days(ca, cb, _TEMPORAL_WINDOW_DAYS):
            edges.append({"id": f"e{edge_id}", "source": a, "target": b, "type": "temporal"})
            edge_id += 1

    return {"nodes": nodes, "edges": edges}


def _build_cluster_graph(
    meta: dict[str, SpikeMeta],
    communities: dict[str, tuple[int, str]],
    zoom: int,
) -> dict:
    """Build the cluster-level graph (zoom 0/1)."""
    # Collect distinct communities
    community_names: dict[int, str] = {}
    for spike_id, (comm_idx, comm_name) in communities.items():
        if spike_id in meta:
            community_names[comm_idx] = comm_name

    # Assign unclustered spikes to a default community
    unclustered = [sid for sid in meta if sid not in communities]
    if unclustered:
        default_idx = max(community_names, default=-1) + 1
        community_names[default_idx] = "Uncategorised"
        for sid in unclustered:
            communities = {**communities, sid: (default_idx, "Uncategorised")}

    nodes: list[dict] = []
    edges: list[dict] = []
    edge_id = 0

    # Cluster nodes (always present)
    for comm_idx, comm_name in community_names.items():
        nodes.append(
            {
                "id": f"cluster-{comm_idx}",
                "label": comm_name,
                "type": "cluster",
                "zoomLevel": 0,
            }
        )

    if zoom >= 1:
        # Add spike nodes + membership edges
        for spike_id, data in meta.items():
            nodes.append(
                {
                    "id": spike_id,
                    "label": data.title or spike_id,
                    "type": "spike",
                    "tags": data.tags,
                    "zoomLevel": 1,
                }
            )
            comm_idx = communities.get(spike_id, (0, ""))[0]
            edges.append(
                {
                    "id": f"e{edge_id}",
                    "source": spike_id,
                    "target": f"cluster-{comm_idx}",
                    "type": "cluster",
                }
            )
            edge_id += 1

    return {"nodes": nodes, "edges": edges}


def _within_days(ts_a: str, ts_b: str, days: int) -> bool:
    """Return True if two ISO-8601 timestamps are within *days* of each other."""
    try:
        a = datetime.fromisoformat(ts_a)
        b = datetime.fromisoformat(ts_b)
        return abs((a - b).total_seconds()) <= days * 86400
    except (ValueError, TypeError, AttributeError):
        return False


def _index_update_prompt(current_index: str, spike: SpikeResponse) -> str:
    tags_str = ", ".join(spike.tags) if spike.tags else "(none)"
    code_note = (
        "- This spike contains fenced code blocks. Add a **Code:** line after **Summary:** "
        "that describes in one sentence what the code does and which language(s) are used.\n"
        if spike.languages
        else "- This spike has no fenced code blocks — omit the **Code:** field.\n"
    )
    return (
        f"Update the index.md below to add or replace the entry for spike `{spike.id}`.\n\n"
        f"Spike details:\n"
        f"- ID: {spike.id}\n"
        f"- Title: {spike.title}\n"
        f"- Tags: {tags_str}\n"
        f"- Created: {spike.createdAt}\n"
        f"{code_note}"
        f"- Full content:\n<user_content>\n{spike.raw}\n</user_content>\n\n"
        f"Current index.md:\n{current_index}\n\n"
        f"Output only the complete updated index.md."
    )


def _connections_update_prompt(
    current_connections: str,
    current_index: str,
    spike: SpikeResponse,
) -> str:
    return (
        f"Update connections.md to reflect any new, changed, or removed connections "
        f"involving spike `{spike.id}` ({spike.title!r}).\n\n"
        f"Spike full content:\n<user_content>\n{spike.raw}\n</user_content>\n\n"
        f"Current index.md (summaries of all other spikes for context):\n{current_index}\n\n"
        f"Current connections.md:\n{current_connections}\n\n"
        f"Output only the complete updated connections.md."
    )


def _hierarchy_update_prompt(current_hierarchy: str, spike: SpikeResponse, index_section: str) -> str:
    tags_str = ", ".join(spike.tags) if spike.tags else "(none)"
    return (
        f"Update hierarchy.md to place spike `{spike.id}` (title: {spike.title!r}, "
        f"tags: {tags_str}) into the most fitting community. "
        f"Remove it from any community it currently belongs to first, "
        f"then add it to the right one. Create a new community if needed.\n\n"
        f"Spike summary from index.md:\n{index_section}\n\n"
        f"Current hierarchy.md:\n{current_hierarchy}\n\n"
        f"Output only the complete updated hierarchy.md."
    )
