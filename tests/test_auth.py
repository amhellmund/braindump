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

"""Tests for multi-user cookie-based authentication."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from braindump import dirs
from braindump.users import UserRegistry

_SAMPLE_RAW = "---\ntags: [test]\n---\n\n# Auth Test Spike\n\nContent."


@pytest.fixture
def multi_user_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str, str]]:
    """TestClient fixture with two users in multi-user mode.

    Yields (client, alice_token, bob_token).
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    users_file = dirs.users_path(workspace)
    users_file.parent.mkdir(parents=True, exist_ok=True)

    registry = UserRegistry(users_file)
    alice_token = registry.add_user("alice")
    bob_token = registry.add_user("bob")
    registry.save()

    monkeypatch.setenv("BRAINDUMP_WORKSPACE", str(workspace))
    from braindump.app import app

    with TestClient(app) as c:
        yield c, alice_token, bob_token


def _login(client: TestClient, token: str) -> None:
    """POST to /auth/login; the TestClient stores the returned cookie automatically."""
    resp = client.post("/api/v1/auth/login", json={"token": token})
    assert resp.status_code == 200


def _logout(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200


def test_auth_mode_single_user(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/mode")
    assert resp.status_code == 200
    assert resp.json() == {"multi_user": False}


def test_auth_mode_multi_user(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, _, _ = multi_user_client
    resp = c.get("/api/v1/auth/mode")
    assert resp.status_code == 200
    assert resp.json() == {"multi_user": True}


def test_no_cookie_returns_401(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, _, _ = multi_user_client
    resp = c.get("/api/v1/spikes")
    assert resp.status_code == 401


def test_wrong_token_login_returns_401(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, _, _ = multi_user_client
    resp = c.post("/api/v1/auth/login", json={"token": "bd_" + "x" * 64})
    assert resp.status_code == 401


def test_valid_token_returns_200(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, alice_token, _ = multi_user_client
    _login(c, alice_token)
    resp = c.get("/api/v1/spikes")
    assert resp.status_code == 200


def test_single_user_mode_no_auth_required(client: TestClient) -> None:
    resp = client.get("/api/v1/spikes")
    assert resp.status_code == 200


def test_shared_workspace_spikes_visible_to_all(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, alice_token, bob_token = multi_user_client
    _login(c, alice_token)
    c.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW})
    _logout(c)
    _login(c, bob_token)
    resp = c.get("/api/v1/spikes")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_auth_mode_endpoint_requires_no_cookie(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, _, _ = multi_user_client
    resp = c.get("/api/v1/auth/mode")
    assert resp.status_code == 200


def test_login_sets_cookie(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, alice_token, _ = multi_user_client
    resp = c.post("/api/v1/auth/login", json={"token": alice_token})
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"
    assert c.get("/api/v1/spikes").status_code == 200


def test_logout_clears_cookie(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, alice_token, _ = multi_user_client
    _login(c, alice_token)
    _logout(c)
    assert c.get("/api/v1/spikes").status_code == 401


def test_whoami_returns_username(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, alice_token, _ = multi_user_client
    _login(c, alice_token)
    resp = c.get("/api/v1/auth/whoami")
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_whoami_without_cookie_returns_401(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, _, _ = multi_user_client
    resp = c.get("/api/v1/auth/whoami")
    assert resp.status_code == 401


def test_login_rate_limit(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, _, _ = multi_user_client
    bad = {"token": "bd_" + "x" * 64}
    for _ in range(10):
        c.post("/api/v1/auth/login", json=bad)
    resp = c.post("/api/v1/auth/login", json=bad)
    assert resp.status_code == 429


def test_ws_authenticates_via_cookie(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, alice_token, _ = multi_user_client
    _login(c, alice_token)
    with c.websocket_connect("/api/v1/ws"):
        pass


def test_ws_rejected_without_cookie(multi_user_client: tuple[TestClient, str, str]) -> None:
    c, _, _ = multi_user_client
    with pytest.raises(WebSocketDisconnect), c.websocket_connect("/api/v1/ws"):
        pass
