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

"""Shared pytest fixtures for braindump backend tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _stub_wiki_llm_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub out LLM-dependent wiki updates so tests never call the Claude CLI.

    The meta.json cache is updated synchronously by the routes themselves,
    so the stubs only suppress the LLM-driven index/connections/hierarchy
    rewrites that run in background tasks.
    """
    from braindump import wiki

    async def _noop_update(workspace: object, spike: object, backend: object) -> None:
        pass

    async def _noop_remove(workspace: object, spike_id: object, backend: object) -> None:
        pass

    monkeypatch.setattr(wiki, "update_wiki_for_spike", _noop_update)
    monkeypatch.setattr(wiki, "remove_spike_from_wiki", _noop_remove)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Provide a temporary workspace directory."""
    return tmp_path


@pytest.fixture
def client(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Provide a TestClient backed by a fresh temporary workspace."""
    monkeypatch.setenv("BRAINDUMP_WORKSPACE", str(workspace))
    from braindump.app import app

    with TestClient(app) as c:
        yield c
