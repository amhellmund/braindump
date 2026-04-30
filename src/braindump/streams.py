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

"""Stream management — init, read/write streams.json and assignments.json."""

import re
from datetime import UTC, datetime
from pathlib import Path

from braindump.dirs import assignments_path, stream_summaries_dir, stream_summary_path, streams_path
from braindump.types import StreamMeta, StreamsAssignments, StreamsData

_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\s]')


def _safe_name(stream_name: str) -> str:
    slug = _UNSAFE_RE.sub("_", stream_name)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:128] or "stream"


########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################


def init_streams(workspace: Path) -> None:
    """Create the streams directory and seed empty JSON files if they do not yet exist.

    Args:
        workspace: Root workspace directory.
    """
    sp = streams_path(workspace)
    ap = assignments_path(workspace)
    if not sp.exists():
        sp.write_text(StreamsData().model_dump_json(indent=2), encoding="utf-8")
    if not ap.exists():
        ap.write_text(StreamsAssignments().model_dump_json(indent=2), encoding="utf-8")
    stream_summaries_dir(workspace)


def read_streams(workspace: Path) -> StreamsData:
    """Read streams/streams.json, returning empty StreamsData when the file is missing.

    Args:
        workspace: Root workspace directory.
    """
    path = streams_path(workspace)
    if not path.exists():
        return StreamsData()
    return StreamsData.model_validate_json(path.read_text(encoding="utf-8"))


def write_streams(workspace: Path, data: StreamsData) -> None:
    """Overwrite streams/streams.json with the given data.

    Args:
        workspace: Root workspace directory.
        data: The streams data to persist.
    """
    streams_path(workspace).write_text(data.model_dump_json(indent=2), encoding="utf-8")


def read_assignments(workspace: Path) -> StreamsAssignments:
    """Read streams/assignments.json, returning empty StreamsAssignments when the file is missing.

    Args:
        workspace: Root workspace directory.
    """
    path = assignments_path(workspace)
    if not path.exists():
        return StreamsAssignments()
    return StreamsAssignments.model_validate_json(path.read_text(encoding="utf-8"))


def write_assignments(workspace: Path, data: StreamsAssignments) -> None:
    """Overwrite streams/assignments.json with the given data.

    Args:
        workspace: Root workspace directory.
        data: The assignments data to persist.
    """
    assignments_path(workspace).write_text(data.model_dump_json(indent=2), encoding="utf-8")


def get_spike_stream(workspace: Path, spike_id: str) -> str | None:
    """Return the stream name assigned to spike_id, or None if unassigned.

    Args:
        workspace: Root workspace directory.
        spike_id: UUID of the spike to look up.
    """
    return read_assignments(workspace).assignments.get(spike_id)


def set_spike_stream(workspace: Path, spike_id: str, stream_name: str) -> None:
    """Assign spike_id to stream_name, creating the stream entry if it does not exist.

    Updates the stream's modified_at timestamp on every call.

    Args:
        workspace: Root workspace directory.
        spike_id: UUID of the spike to assign.
        stream_name: Name of the target stream.
    """
    now = datetime.now(UTC).isoformat()

    assignments = read_assignments(workspace)
    assignments.assignments[spike_id] = stream_name
    write_assignments(workspace, assignments)

    streams = read_streams(workspace)
    if stream_name not in streams.streams:
        streams.streams[stream_name] = StreamMeta(created_at=now, modified_at=now)
    else:
        existing = streams.streams[stream_name]
        streams.streams[stream_name] = StreamMeta(created_at=existing.created_at, modified_at=now)
    write_streams(workspace, streams)


def read_summary(workspace: Path, stream_name: str) -> str | None:
    """Read the stored summary for a stream, or None if it does not exist.

    Args:
        workspace: Root workspace directory.
        stream_name: Name of the stream.
    """
    path = stream_summary_path(workspace, _safe_name(stream_name))
    return path.read_text(encoding="utf-8") if path.exists() else None


def write_summary(workspace: Path, stream_name: str, content: str, generated_at: str) -> None:
    """Write summary content and update summary_at in streams.json.

    Args:
        workspace: Root workspace directory.
        stream_name: Name of the stream.
        content: Markdown content of the summary.
        generated_at: ISO-8601 timestamp of when the summary was generated.
    """
    stream_summary_path(workspace, _safe_name(stream_name)).write_text(content, encoding="utf-8")
    streams = read_streams(workspace)
    if stream_name in streams.streams:
        m = streams.streams[stream_name]
        streams.streams[stream_name] = StreamMeta(
            created_at=m.created_at,
            modified_at=m.modified_at,
            summary_at=generated_at,
        )
        write_streams(workspace, streams)


def remove_spike_stream(workspace: Path, spike_id: str) -> None:
    """Remove the stream assignment for spike_id.

    The stream entry in streams.json is kept for future autocomplete use.
    This is a no-op if spike_id has no current assignment.

    Args:
        workspace: Root workspace directory.
        spike_id: UUID of the spike to unassign.
    """
    assignments = read_assignments(workspace)
    if spike_id in assignments.assignments:
        del assignments.assignments[spike_id]
        write_assignments(workspace, assignments)
