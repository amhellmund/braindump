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

"""Unit tests for braindump.migrations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest

import braindump.migrations as mig_mod
from braindump.dirs import meta_json_path, versions_path
from braindump.migrations import (
    CURRENT_VERSIONS,
    Migration,
    check_migration_needed,
    needs_migration,
    run_migrations,
)
from braindump.types import WorkspaceVersions

########################################################################################################################
# Helpers
########################################################################################################################


def _write_versions(workspace: Path, wiki_schema: int, meta: int, streams: int = 1, dailies: int = 0) -> None:
    versions_path(workspace).write_text(
        WorkspaceVersions(wiki_schema=wiki_schema, meta=meta, streams=streams, dailies=dailies).model_dump_json(
            indent=2
        ),
        encoding="utf-8",
    )


def _read_versions(workspace: Path) -> WorkspaceVersions:
    return WorkspaceVersions.model_validate_json(versions_path(workspace).read_text(encoding="utf-8"))


class _StubMigration(Migration):
    aspect: Literal["wiki_schema", "meta", "streams"] = "wiki_schema"
    from_version: int = 1
    to_version: int = 2
    description: str = "Stub: wiki_schema 1 → 2"

    def __init__(self, called: list[Path]) -> None:
        self._called = called

    def migrate(self, workspace: Path) -> None:
        self._called.append(workspace)


########################################################################################################################
# needs_migration
########################################################################################################################


def test_needs_migration_returns_false_when_versions_match(tmp_path: Path) -> None:
    _write_versions(
        tmp_path,
        CURRENT_VERSIONS.wiki_schema,
        CURRENT_VERSIONS.meta,
        CURRENT_VERSIONS.streams,
        CURRENT_VERSIONS.dailies,
    )
    assert needs_migration(tmp_path) is False


def test_needs_migration_returns_true_when_wiki_schema_outdated(tmp_path: Path) -> None:
    _write_versions(tmp_path, CURRENT_VERSIONS.wiki_schema - 1, CURRENT_VERSIONS.meta)
    assert needs_migration(tmp_path) is True


def test_needs_migration_returns_true_when_meta_outdated(tmp_path: Path) -> None:
    _write_versions(tmp_path, CURRENT_VERSIONS.wiki_schema, CURRENT_VERSIONS.meta - 1)
    assert needs_migration(tmp_path) is True


def test_needs_migration_returns_false_when_file_missing(tmp_path: Path) -> None:
    assert needs_migration(tmp_path) is False


########################################################################################################################
# run_migrations
########################################################################################################################


def test_run_migrations_noop_when_up_to_date(tmp_path: Path) -> None:
    _write_versions(
        tmp_path,
        CURRENT_VERSIONS.wiki_schema,
        CURRENT_VERSIONS.meta,
        CURRENT_VERSIONS.streams,
        CURRENT_VERSIONS.dailies,
    )
    assert run_migrations(tmp_path) == []


def test_run_migrations_returns_empty_when_file_missing(tmp_path: Path) -> None:
    assert run_migrations(tmp_path) == []


def test_run_migrations_applies_stub_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_versions(tmp_path, 1, 1)
    called: list[Path] = []
    stub = _StubMigration(called)
    monkeypatch.setattr(mig_mod, "CURRENT_VERSIONS", WorkspaceVersions(wiki_schema=2, meta=1))
    monkeypatch.setattr(mig_mod, "_MIGRATIONS", [stub])

    applied = run_migrations(tmp_path)

    assert applied == ["Stub: wiki_schema 1 → 2"]
    assert called == [tmp_path]
    stored = _read_versions(tmp_path)
    assert stored.wiki_schema == 2
    assert stored.meta == 1


def test_run_migrations_raises_when_migration_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_versions(tmp_path, 1, 1)
    monkeypatch.setattr(mig_mod, "CURRENT_VERSIONS", WorkspaceVersions(wiki_schema=2, meta=1))
    monkeypatch.setattr(mig_mod, "_MIGRATIONS", [])

    with pytest.raises(RuntimeError, match="wiki_schema"):
        run_migrations(tmp_path)


def test_run_migrations_does_not_update_versions_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_versions(tmp_path, 1, 1)
    monkeypatch.setattr(mig_mod, "CURRENT_VERSIONS", WorkspaceVersions(wiki_schema=2, meta=1))
    monkeypatch.setattr(mig_mod, "_MIGRATIONS", [])

    with pytest.raises(RuntimeError):
        run_migrations(tmp_path)

    stored = _read_versions(tmp_path)
    assert stored.wiki_schema == 1


########################################################################################################################
# check_migration_needed
########################################################################################################################


def test_check_migration_needed_empty_when_up_to_date(tmp_path: Path) -> None:
    _write_versions(
        tmp_path,
        CURRENT_VERSIONS.wiki_schema,
        CURRENT_VERSIONS.meta,
        CURRENT_VERSIONS.streams,
        CURRENT_VERSIONS.dailies,
    )
    assert check_migration_needed(tmp_path) == []


def test_check_migration_needed_missing_file(tmp_path: Path) -> None:
    messages = check_migration_needed(tmp_path)
    assert len(messages) == 1
    assert "braindump init" in messages[0]


def test_check_migration_needed_outdated_wiki_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_versions(tmp_path, 1, 1)
    monkeypatch.setattr(mig_mod, "CURRENT_VERSIONS", WorkspaceVersions(wiki_schema=2, meta=1))

    messages = check_migration_needed(tmp_path)
    assert len(messages) == 1
    assert "braindump update" in messages[0]
    assert "wiki" in messages[0].lower() or "SCHEMA" in messages[0]


def test_check_migration_needed_outdated_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_versions(tmp_path, 1, 1)
    monkeypatch.setattr(mig_mod, "CURRENT_VERSIONS", WorkspaceVersions(wiki_schema=1, meta=2))

    messages = check_migration_needed(tmp_path)
    assert len(messages) == 1
    assert "braindump update" in messages[0]
    assert "meta" in messages[0]


def test_check_migration_needed_both_outdated_returns_two_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_versions(tmp_path, 1, 1)
    monkeypatch.setattr(mig_mod, "CURRENT_VERSIONS", WorkspaceVersions(wiki_schema=2, meta=2))

    messages = check_migration_needed(tmp_path)
    assert len(messages) == 2


########################################################################################################################
# _MetaWikiPendingMigration (meta 1 → 2)
########################################################################################################################


def test_meta_wiki_pending_migration_adds_field_to_existing_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta_path = meta_json_path(tmp_path)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(
            {
                "spike-1": {"title": "Spike 1", "tags": [], "created_at": "", "modified_at": ""},
                "spike-2": {"title": "Spike 2", "tags": ["a"], "created_at": "", "modified_at": ""},
            }
        ),
        encoding="utf-8",
    )
    _write_versions(tmp_path, CURRENT_VERSIONS.wiki_schema, 1, CURRENT_VERSIONS.streams)

    run_migrations(tmp_path)

    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["spike-1"]["wiki_pending"] is False
    assert data["spike-2"]["wiki_pending"] is False


def test_meta_wiki_pending_migration_preserves_true_when_already_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta_path = meta_json_path(tmp_path)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps({"spike-1": {"title": "S", "tags": [], "created_at": "", "modified_at": "", "wiki_pending": True}}),
        encoding="utf-8",
    )
    _write_versions(tmp_path, CURRENT_VERSIONS.wiki_schema, 1, CURRENT_VERSIONS.streams)

    run_migrations(tmp_path)

    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["spike-1"]["wiki_pending"] is True


def test_meta_wiki_pending_migration_noop_when_meta_json_missing(tmp_path: Path) -> None:
    _write_versions(tmp_path, CURRENT_VERSIONS.wiki_schema, 1, CURRENT_VERSIONS.streams)

    applied = run_migrations(tmp_path)

    assert "Add wiki_pending field to meta.json entries" in applied
