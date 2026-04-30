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

"""Workspace directory and path helpers.

All workspace-relative path computations live here so that the directory
layout is defined in a single place and callers never construct paths inline.
"""

from pathlib import Path

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################

_CONFIG_DIR = ".config"
_SPIKES_DIR = "spikes"
_WIKI_DIR = "wiki"
_CHATS_DIR = "chats"
_STREAMS_DIR = "streams"
_TXLOG_FILE = "txlog.jsonl"


def config_dir(workspace: Path) -> Path:
    """Return the configuration directory (``<workspace>/.config/``), creating it if needed."""
    path = workspace / _CONFIG_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def spikes_dir(workspace: Path) -> Path:
    """Return the spikes directory (``<workspace>/spikes/``), creating it if needed.

    Args:
        workspace: Root workspace directory.

    Returns:
        Path to the spikes subdirectory.
    """
    path = workspace / _SPIKES_DIR
    path.mkdir(exist_ok=True)
    return path


def images_dir(workspace: Path) -> Path:
    """Return the images directory (``<workspace>/spikes/images/``), creating it if needed.

    Args:
        workspace: Root workspace directory.

    Returns:
        Path to the images subdirectory inside the spikes directory.
    """
    path = spikes_dir(workspace) / "images"
    path.mkdir(exist_ok=True)
    return path


def wiki_dir(workspace: Path) -> Path:
    """Return the wiki directory path (``<workspace>/wiki/``)."""
    return workspace / _WIKI_DIR


def index_path(workspace: Path) -> Path:
    """Return the path to ``<wiki>/index.md``."""
    return wiki_dir(workspace) / "index.md"


def connections_path(workspace: Path) -> Path:
    """Return the path to ``<wiki>/connections.md``."""
    return wiki_dir(workspace) / "connections.md"


def hierarchy_path(workspace: Path) -> Path:
    """Return the path to ``<wiki>/hierarchy.md``."""
    return wiki_dir(workspace) / "hierarchy.md"


def log_dir(workspace: Path) -> Path:
    """Return the path to the ``<wiki>/logs/`` directory."""
    return wiki_dir(workspace) / "logs"


def meta_json_path(workspace: Path) -> Path:
    """Return the path to ``<wiki>/meta.json``."""
    return wiki_dir(workspace) / "meta.json"


def schema_path(workspace: Path) -> Path:
    """Return the path to ``<wiki>/SCHEMA.md``."""
    return wiki_dir(workspace) / "SCHEMA.md"


def txlog_path(workspace: Path) -> Path:
    """Return the path to ``<wiki>/txlog.jsonl``."""
    return wiki_dir(workspace) / _TXLOG_FILE


def usage_path(workspace: Path) -> Path:
    """Return the path to ``<workspace>/.config/usage.json``."""
    return config_dir(workspace) / "usage.json"


def versions_path(workspace: Path) -> Path:
    """Return the path to ``<workspace>/versions.json``."""
    return workspace / "versions.json"


def chats_dir(workspace: Path) -> Path:
    """Return the chats directory (``<workspace>/chats/``), creating it if needed."""
    path = workspace / _CHATS_DIR
    path.mkdir(exist_ok=True)
    return path


def chat_session_path(workspace: Path, session_id: str) -> Path:
    """Return the path to ``<workspace>/chats/{session_id}.json``."""
    return chats_dir(workspace) / f"{session_id}.json"


def streams_dir(workspace: Path) -> Path:
    """Return the streams directory (``<workspace>/streams/``), creating it if needed."""
    path = workspace / _STREAMS_DIR
    path.mkdir(exist_ok=True)
    return path


def streams_path(workspace: Path) -> Path:
    """Return the path to ``<workspace>/streams/streams.json``."""
    return streams_dir(workspace) / "streams.json"


def assignments_path(workspace: Path) -> Path:
    """Return the path to ``<workspace>/streams/assignments.json``."""
    return streams_dir(workspace) / "assignments.json"


def stream_summaries_dir(workspace: Path) -> Path:
    """Return the stream summaries directory (``<workspace>/streams/summaries/``), creating it if needed."""
    path = streams_dir(workspace) / "summaries"
    path.mkdir(exist_ok=True)
    return path


def stream_summary_path(workspace: Path, safe_name: str) -> Path:
    """Return the path to ``<workspace>/streams/summaries/{safe_name}.md``."""
    return stream_summaries_dir(workspace) / f"{safe_name}.md"


_DAILIES_DIR = "dailies"


def dailies_dir(workspace: Path) -> Path:
    """Return the dailies directory (``<workspace>/dailies/``), creating it if needed."""
    path = workspace / _DAILIES_DIR
    path.mkdir(exist_ok=True)
    return path


def dailies_path(workspace: Path) -> Path:
    """Return the path to ``<workspace>/dailies/dailies.json``."""
    return dailies_dir(workspace) / "dailies.json"


def daily_summaries_dir(workspace: Path) -> Path:
    """Return the daily summaries directory (``<workspace>/dailies/summaries/``), creating it if needed."""
    path = dailies_dir(workspace) / "summaries"
    path.mkdir(exist_ok=True)
    return path


def daily_summary_path(workspace: Path, date: str) -> Path:
    """Return the path to ``<workspace>/dailies/summaries/{date}.md``."""
    return daily_summaries_dir(workspace) / f"{date}.md"
