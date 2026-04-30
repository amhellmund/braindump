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

"""Workspace schema migration registry and runner."""

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from braindump.dirs import meta_json_path, versions_path
from braindump.types import WorkspaceVersions

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################

CURRENT_VERSIONS = WorkspaceVersions(wiki_schema=1, meta=2, streams=3, dailies=1)


class Migration(ABC):
    """Abstract base for a single workspace schema migration step."""

    aspect: Literal["wiki_schema", "meta", "streams", "dailies"]
    from_version: int
    to_version: int
    description: str

    @abstractmethod
    def migrate(self, workspace: Path) -> None:
        """Apply the migration to the given workspace.

        Args:
            workspace: Root workspace directory.
        """


class _StreamsMigration(Migration):
    """Migration: create the streams/ directory and seed streams.json and assignments.json."""

    aspect: Literal["wiki_schema", "meta", "streams"] = "streams"
    from_version: int = 1
    to_version: int = 2
    description: str = "Create streams/ directory and seed streams.json and assignments.json"

    def migrate(self, workspace: Path) -> None:
        from braindump.streams import init_streams

        init_streams(workspace)


class _MetaWikiPendingMigration(Migration):
    """Migration: add wiki_pending field to every entry in meta.json."""

    aspect: Literal["wiki_schema", "meta", "streams"] = "meta"
    from_version: int = 1
    to_version: int = 2
    description: str = "Add wiki_pending field to meta.json entries"

    def migrate(self, workspace: Path) -> None:
        path = meta_json_path(workspace)
        if not path.exists():
            return
        raw = json.loads(path.read_text(encoding="utf-8"))
        for entry in raw.values():
            entry.setdefault("wiki_pending", False)
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")


class _StreamsSummariesMigration(Migration):
    """Migration: create the streams/summaries/ directory."""

    aspect: Literal["wiki_schema", "meta", "streams"] = "streams"
    from_version: int = 2
    to_version: int = 3
    description: str = "Create streams/summaries/ directory for AI-generated stream summaries"

    def migrate(self, workspace: Path) -> None:
        from braindump.dirs import stream_summaries_dir

        stream_summaries_dir(workspace)


class _DailiesMigration(Migration):
    """Migration: create the dailies/ directory and seed dailies.json."""

    aspect: Literal["wiki_schema", "meta", "streams", "dailies"] = "dailies"
    from_version: int = 0
    to_version: int = 1
    description: str = "Create dailies/ directory and seed dailies.json for daily summaries"

    def migrate(self, workspace: Path) -> None:
        from braindump.dailies import init_dailies

        init_dailies(workspace)


_MIGRATIONS: list[Migration] = [
    _StreamsMigration(),
    _MetaWikiPendingMigration(),
    _StreamsSummariesMigration(),
    _DailiesMigration(),
]


def needs_migration(workspace: Path) -> bool:
    """Return True if the workspace versions are behind CURRENT_VERSIONS.

    Returns False when versions.json is missing (init case, not migration case).

    Args:
        workspace: Root workspace directory.
    """
    path = versions_path(workspace)
    if not path.exists():
        return False
    stored = WorkspaceVersions.model_validate_json(path.read_text(encoding="utf-8"))
    return (
        stored.wiki_schema != CURRENT_VERSIONS.wiki_schema
        or stored.meta != CURRENT_VERSIONS.meta
        or stored.streams != CURRENT_VERSIONS.streams
        or stored.dailies != CURRENT_VERSIONS.dailies
    )


def check_migration_needed(workspace: Path) -> list[str]:
    """Return human-readable error messages when the workspace needs migration.

    Returns an empty list when the workspace is up-to-date.

    Args:
        workspace: Root workspace directory.

    Returns:
        List of error strings; empty when everything is current.
    """
    path = versions_path(workspace)
    if not path.exists():
        return ["versions.json not found — run `braindump init <workspace>` to create it."]
    stored = WorkspaceVersions.model_validate_json(path.read_text(encoding="utf-8"))
    messages: list[str] = []
    if stored.wiki_schema != CURRENT_VERSIONS.wiki_schema:
        messages.append(
            f"wiki/SCHEMA.md is at version {stored.wiki_schema}, "
            f"expected {CURRENT_VERSIONS.wiki_schema} "
            "— run `braindump update <workspace>` to migrate."
        )
    if stored.meta != CURRENT_VERSIONS.meta:
        messages.append(
            f"wiki/meta.json is at version {stored.meta}, "
            f"expected {CURRENT_VERSIONS.meta} "
            "— run `braindump update <workspace>` to migrate."
        )
    if stored.streams != CURRENT_VERSIONS.streams:
        messages.append(
            f"streams data is at version {stored.streams}, "
            f"expected {CURRENT_VERSIONS.streams} "
            "— run `braindump update <workspace>` to migrate."
        )
    if stored.dailies != CURRENT_VERSIONS.dailies:
        messages.append(
            f"dailies data is at version {stored.dailies}, "
            f"expected {CURRENT_VERSIONS.dailies} "
            "— run `braindump update <workspace>` to migrate."
        )
    return messages


def run_migrations(workspace: Path) -> list[str]:
    """Apply all pending migrations and update versions.json.

    Args:
        workspace: Root workspace directory.

    Returns:
        Descriptions of migrations that were applied; empty when already current.

    Raises:
        RuntimeError: When a required migration step is not registered.
    """
    path = versions_path(workspace)
    if not path.exists():
        return []
    stored = WorkspaceVersions.model_validate_json(path.read_text(encoding="utf-8"))
    applied: list[str] = []
    new_wiki_schema = stored.wiki_schema
    new_meta = stored.meta
    new_streams = stored.streams
    new_dailies = stored.dailies

    for aspect in ("wiki_schema", "meta", "streams", "dailies"):
        stored_v: int = getattr(stored, aspect)
        target_v: int = getattr(CURRENT_VERSIONS, aspect)
        v = stored_v
        while v < target_v:
            migration = next(
                (m for m in _MIGRATIONS if m.aspect == aspect and m.from_version == v and m.to_version == v + 1),
                None,
            )
            if migration is None:
                raise RuntimeError(f"No migration registered for aspect '{aspect}' from version {v} to {v + 1}.")
            migration.migrate(workspace)
            applied.append(migration.description)
            v += 1
        if aspect == "wiki_schema":
            new_wiki_schema = v
        elif aspect == "meta":
            new_meta = v
        elif aspect == "streams":
            new_streams = v
        else:
            new_dailies = v

    if applied:
        updated = stored.model_copy(
            update={"wiki_schema": new_wiki_schema, "meta": new_meta, "streams": new_streams, "dailies": new_dailies}
        )
        path.write_text(updated.model_dump_json(indent=2), encoding="utf-8")

    return applied
