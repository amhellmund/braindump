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

"""Unit tests for braindump.health."""

from __future__ import annotations

from pathlib import Path

import pytest

from braindump import health, txlog, wiki
from braindump.storage import write_spike


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    wiki.init_wiki(tmp_path)
    return tmp_path


_UUID_A = "aaaaaaaa-0000-0000-0000-000000000001"
_UUID_B = "aaaaaaaa-0000-0000-0000-000000000002"
_SAMPLE_RAW = "---\ntags: []\n---\n\n# Test\n"


def test_health_check_clean_state(workspace: Path) -> None:
    report = health.run_health_check(workspace)
    assert report.issues == []
    assert report.missing_index_entries == []
    assert report.stale_index_entries == []
    assert report.broken_links == []
    assert report.orphaned_wiki_pages == []


def test_health_check_detects_missing_index_entry(workspace: Path) -> None:
    # Spike exists on disk but has no meta.json entry.
    write_spike(workspace, _UUID_A, _SAMPLE_RAW)
    report = health.run_health_check(workspace)
    assert _UUID_A in report.missing_index_entries


def test_health_check_detects_stale_index_entry(workspace: Path) -> None:
    # meta.json has an entry but the file is gone.
    from braindump.types import SpikeResponse

    spike = SpikeResponse(
        id=_UUID_A,
        title="Ghost",
        tags=[],
        createdAt="2025-01-01T00:00:00+00:00",
        modifiedAt="2025-01-01T00:00:00+00:00",
        raw="",
        sections=[],
    )
    wiki.update_meta_json(workspace, spike)
    # Do NOT write the file — simulating a stale entry.
    report = health.run_health_check(workspace)
    assert _UUID_A in report.stale_index_entries


def test_health_check_detects_broken_connection_link(workspace: Path) -> None:
    # connections.md references a UUID that does not exist on disk.
    wiki.connections_path(workspace).write_text(
        f"# Connections\n\n- {_UUID_A} <-> {_UUID_B}: test\n",
        encoding="utf-8",
    )
    report = health.run_health_check(workspace)
    assert _UUID_A in report.broken_links or _UUID_B in report.broken_links


def test_health_check_detects_orphaned_hierarchy_entry(workspace: Path) -> None:
    # hierarchy.md references a UUID with no file on disk.
    wiki.hierarchy_path(workspace).write_text(
        f"## Community: Ghost\n- {_UUID_A} (missing spike)\n",
        encoding="utf-8",
    )
    report = health.run_health_check(workspace)
    assert _UUID_A in report.orphaned_wiki_pages


def test_health_check_no_issues_for_consistent_state(workspace: Path) -> None:
    from braindump.types import SpikeResponse

    spike = SpikeResponse(
        id=_UUID_A,
        title="Good",
        tags=["test"],
        createdAt="2025-01-01T00:00:00+00:00",
        modifiedAt="2025-01-01T00:00:00+00:00",
        raw=_SAMPLE_RAW,
        sections=[],
    )
    write_spike(workspace, _UUID_A, _SAMPLE_RAW)
    wiki.update_meta_json(workspace, spike)
    wiki.hierarchy_path(workspace).write_text(
        f"## Community: Test\n- {_UUID_A} (Good)\n",
        encoding="utf-8",
    )
    report = health.run_health_check(workspace)
    assert report.issues == []


def test_health_check_writes_to_log(workspace: Path) -> None:
    health.run_health_check(workspace)
    log_files = list(wiki.log_dir(workspace).glob("*.json"))
    assert any("Health check" in f.read_text(encoding="utf-8") for f in log_files)


def test_health_check_clean_state_has_no_incomplete_transactions(workspace: Path) -> None:
    report = health.run_health_check(workspace)
    assert report.incomplete_transactions == []


def test_health_check_detects_incomplete_transaction(workspace: Path) -> None:
    # Begin a transaction but never commit — simulates a crash mid-update.
    txlog.begin_transaction(workspace, txlog.TxOp.UPDATE_SPIKE, _UUID_A)
    report = health.run_health_check(workspace)
    assert _UUID_A in report.incomplete_transactions
    assert any("incomplete wiki transaction" in issue for issue in report.issues)


def test_health_check_ignores_committed_transaction(workspace: Path) -> None:
    txid = txlog.begin_transaction(workspace, txlog.TxOp.UPDATE_SPIKE, _UUID_A)
    txlog.record_step(workspace, txid, txlog.TxEvent.STEP_INDEX)
    txlog.record_step(workspace, txid, txlog.TxEvent.STEP_CONNECTIONS)
    txlog.record_step(workspace, txid, txlog.TxEvent.STEP_HIERARCHY)
    txlog.commit_transaction(workspace, txid)
    report = health.run_health_check(workspace)
    assert _UUID_A not in report.incomplete_transactions
