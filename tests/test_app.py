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

"""Tests for the spike CRUD API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from braindump import storage

_SAMPLE_RAW = "---\ntags: [test, sample]\n---\n\n# Test Spike\n\nIntro paragraph.\n\n## Details\n\nSome detail content."

_UPDATED_RAW = "---\ntags: [updated]\n---\n\n# Updated Title\n\nNew content."

# A well-formed UUID that is guaranteed not to exist in the test workspace.
_NONEXISTENT_UUID = "00000000-0000-0000-0000-000000000000"


def test_list_spikes_empty(client: TestClient) -> None:
    resp = client.get("/api/v1/spikes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_spike_returns_parsed_fields(client: TestClient) -> None:
    resp = client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Test Spike"
    assert data["tags"] == ["test", "sample"]
    assert "# Test Spike" in data["raw"]
    assert "created:" in data["raw"]
    assert "modified:" in data["raw"]
    assert "id" in data
    assert "createdAt" in data
    assert "modifiedAt" in data
    assert len(data["sections"]) == 1
    assert data["sections"][0]["heading"] == "Details"
    assert data["sections"][0]["content"] == "Some detail content."


def test_list_spikes_after_create(client: TestClient) -> None:
    client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW})
    resp = client.get("/api/v1/spikes")
    assert resp.status_code == 200
    spikes = resp.json()
    assert len(spikes) == 1
    assert spikes[0]["title"] == "Test Spike"


def test_list_spikes_ordered_by_modified_desc(client: TestClient) -> None:
    client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW})
    client.post("/api/v1/spikes", json={"raw": _UPDATED_RAW})
    spikes = client.get("/api/v1/spikes").json()
    assert spikes[0]["title"] == "Updated Title"
    assert spikes[1]["title"] == "Test Spike"


def test_get_spike(client: TestClient) -> None:
    spike_id = client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW}).json()["id"]
    resp = client.get(f"/api/v1/spikes/{spike_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == spike_id
    assert resp.json()["title"] == "Test Spike"


def test_get_spike_not_found(client: TestClient) -> None:
    resp = client.get(f"/api/v1/spikes/{_NONEXISTENT_UUID}")
    assert resp.status_code == 404


def test_get_spike_invalid_id_format(client: TestClient) -> None:
    resp = client.get("/api/v1/spikes/not-a-uuid")
    assert resp.status_code == 422


def test_update_spike(client: TestClient) -> None:
    created = client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW}).json()
    spike_id = created["id"]
    created_at = created["createdAt"]

    resp = client.put(f"/api/v1/spikes/{spike_id}", json={"raw": _UPDATED_RAW})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated Title"
    assert data["tags"] == ["updated"]
    assert data["createdAt"] == created_at
    assert data["modifiedAt"] != created_at


def test_update_spike_not_found(client: TestClient) -> None:
    resp = client.put(f"/api/v1/spikes/{_NONEXISTENT_UUID}", json={"raw": _SAMPLE_RAW})
    assert resp.status_code == 404


def test_update_spike_invalid_id_format(client: TestClient) -> None:
    resp = client.put("/api/v1/spikes/not-a-uuid", json={"raw": _SAMPLE_RAW})
    assert resp.status_code == 422


def test_delete_spike(client: TestClient) -> None:
    spike_id = client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW}).json()["id"]
    assert client.delete(f"/api/v1/spikes/{spike_id}").status_code == 204
    assert client.get(f"/api/v1/spikes/{spike_id}").status_code == 404


def test_delete_spike_not_found(client: TestClient) -> None:
    resp = client.delete(f"/api/v1/spikes/{_NONEXISTENT_UUID}")
    assert resp.status_code == 404


def test_delete_spike_invalid_id_format(client: TestClient) -> None:
    resp = client.delete("/api/v1/spikes/not-a-uuid")
    assert resp.status_code == 422


def test_delete_removes_list_entry(client: TestClient) -> None:
    spike_id = client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW}).json()["id"]
    client.delete(f"/api/v1/spikes/{spike_id}")
    assert client.get("/api/v1/spikes").json() == []


def test_spike_file_persisted(client: TestClient, workspace: Path) -> None:
    spike_id = client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW}).json()["id"]
    content = storage.read_spike_raw(workspace, spike_id)
    assert "# Test Spike" in content
    assert "created:" in content
    assert "modified:" in content


def test_spike_file_updated_on_put(client: TestClient, workspace: Path) -> None:
    spike_id = client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW}).json()["id"]
    client.put(f"/api/v1/spikes/{spike_id}", json={"raw": _UPDATED_RAW})
    content = storage.read_spike_raw(workspace, spike_id)
    assert "# Updated Title" in content
    assert "created:" in content
    assert "modified:" in content


def test_timestamps_in_frontmatter(client: TestClient, workspace: Path) -> None:
    data = client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW}).json()
    content = storage.read_spike_raw(workspace, data["id"])
    assert data["createdAt"] != ""
    assert data["modifiedAt"] != ""
    # Both timestamps must be embedded in the file so the DB can be rebuilt from it
    assert "created:" in content
    assert "modified:" in content


def test_created_preserved_after_update(client: TestClient, workspace: Path) -> None:
    created_data = client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW}).json()
    spike_id = created_data["id"]
    original_created = created_data["createdAt"]

    updated_data = client.put(f"/api/v1/spikes/{spike_id}", json={"raw": _UPDATED_RAW}).json()
    content = storage.read_spike_raw(workspace, spike_id)

    assert updated_data["createdAt"] == original_created
    assert updated_data["modifiedAt"] != original_created
    assert "created:" in content
    assert "modified:" in content


def test_spike_file_deleted_on_delete(client: TestClient, workspace: Path) -> None:
    spike_id = client.post("/api/v1/spikes", json={"raw": _SAMPLE_RAW}).json()["id"]
    client.delete(f"/api/v1/spikes/{spike_id}")
    assert storage._find_spike_file(workspace, spike_id) is None


def test_spike_without_title_defaults_to_untitled(client: TestClient) -> None:
    raw = "---\ntags: []\n---\n\nNo heading here."
    data = client.post("/api/v1/spikes", json={"raw": raw}).json()
    assert data["title"] == "Untitled"


def test_spike_sections_empty_when_no_h2(client: TestClient) -> None:
    raw = "---\ntags: []\n---\n\n# Title Only\n\nJust a paragraph."
    data = client.post("/api/v1/spikes", json={"raw": raw}).json()
    assert data["sections"] == []


def test_h2_inside_fenced_code_not_treated_as_section(client: TestClient) -> None:
    raw = "---\ntags: []\n---\n\n# Title\n\n```python\n## not a section\nx = 1\n```"
    data = client.post("/api/v1/spikes", json={"raw": raw}).json()
    assert data["sections"] == []


def test_title_with_inline_markup_strips_markup(client: TestClient) -> None:
    raw = "---\ntags: []\n---\n\n# Title with `code`\n\nBody."
    data = client.post("/api/v1/spikes", json={"raw": raw}).json()
    assert data["title"] == "Title with code"


def test_workspace_created_if_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    new_workspace = tmp_path / "new" / "workspace"
    assert not new_workspace.exists()
    monkeypatch.setenv("BRAINDUMP_WORKSPACE", str(new_workspace))
    from braindump.app import app

    with TestClient(app) as client:
        assert new_workspace.is_dir()
        assert client.get("/api/v1/spikes").status_code == 200


# ---------------------------------------------------------------------------
# Image upload security tests
# ---------------------------------------------------------------------------

# Minimal valid magic-byte headers for each allowed type.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
_JPEG_MAGIC = b"\xff\xd8\xff" + b"\x00" * 8
_GIF_MAGIC = b"GIF89a" + b"\x00" * 8
_WEBP_MAGIC = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 8


def test_image_upload_accepts_valid_png(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/images",
        files={"file": ("img.png", _PNG_MAGIC, "image/png")},
    )
    assert resp.status_code == 201


def test_image_upload_rejects_mismatched_magic(client: TestClient) -> None:
    """Claiming image/png but sending JPEG bytes must be rejected."""
    resp = client.post(
        "/api/v1/images",
        files={"file": ("img.png", _JPEG_MAGIC, "image/png")},
    )
    assert resp.status_code == 415


def test_image_upload_rejects_plain_text_as_image(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/images",
        files={"file": ("evil.png", b"not an image at all", "image/png")},
    )
    assert resp.status_code == 415


def test_spike_payload_too_large_rejected(client: TestClient) -> None:
    oversized = "x" * 200_001
    resp = client.post("/api/v1/spikes", json={"raw": oversized})
    assert resp.status_code == 422


def test_query_too_large_rejected(client: TestClient) -> None:
    oversized = "x" * 10_001
    resp = client.post("/api/v1/query", json={"query": oversized})
    assert resp.status_code == 422
