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

"""Unit tests for braindump.wiki."""

from __future__ import annotations

import json
from pathlib import Path

from braindump.types import SpikeResponse
from braindump.wiki import (
    _remove_from_connections,
    _remove_from_hierarchy,
    _remove_from_index,
    _within_days,
    append_log,
    connections_path,
    get_graph,
    hierarchy_path,
    index_path,
    init_wiki,
    list_all_meta,
    log_dir,
    meta_json_path,
    parse_connections,
    parse_hierarchy,
    read_meta,
    remove_from_meta_json,
    schema_path,
    update_meta_json,
    wiki_dir,
)

########################################################################################################################
# Helpers
########################################################################################################################


def _make_spike(
    spike_id: str = "aaaaaaaa-0000-0000-0000-000000000001",
    title: str = "Test Spike",
    tags: list[str] | None = None,
    created_at: str = "2025-01-01T10:00:00+00:00",
    modified_at: str = "2025-01-01T10:00:00+00:00",
) -> SpikeResponse:
    return SpikeResponse(
        id=spike_id,
        title=title,
        tags=tags or ["tag-a"],
        createdAt=created_at,
        modifiedAt=modified_at,
        raw=f"---\ntags: {tags or ['tag-a']}\n---\n\n# {title}\n",
        sections=[],
    )


########################################################################################################################
# init_wiki
########################################################################################################################


def test_init_wiki_creates_directory(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    assert wiki_dir(tmp_path).is_dir()


def test_init_wiki_creates_all_files(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    for path_fn in (index_path, connections_path, hierarchy_path, meta_json_path, schema_path):
        assert path_fn(tmp_path).exists(), f"{path_fn.__name__} missing"
    assert log_dir(tmp_path).is_dir(), "log_dir missing"


def test_init_wiki_idempotent(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    # Write something to schema so we can verify it is not overwritten.
    schema_path(tmp_path).write_text("custom content", encoding="utf-8")
    init_wiki(tmp_path)
    assert schema_path(tmp_path).read_text(encoding="utf-8") == "custom content"


def test_init_wiki_meta_json_is_empty_object(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    data = json.loads(meta_json_path(tmp_path).read_text(encoding="utf-8"))
    assert data == {}


########################################################################################################################
# update_meta_json / remove_from_meta_json / read_meta
########################################################################################################################


def test_update_meta_json_adds_entry(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    spike = _make_spike()
    update_meta_json(tmp_path, spike)
    meta = read_meta(tmp_path)
    assert spike.id in meta
    assert meta[spike.id].title == "Test Spike"
    assert meta[spike.id].tags == ["tag-a"]


def test_update_meta_json_stores_languages_and_image_count(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    spike = SpikeResponse(
        id="aaaaaaaa-0000-0000-0000-000000000001",
        title="Code Spike",
        tags=["python"],
        createdAt="2025-01-01T10:00:00+00:00",
        modifiedAt="2025-01-01T10:00:00+00:00",
        raw="# Code Spike\n\n```python\npass\n```\n",
        sections=[],
        languages=["python"],
        image_count=2,
    )
    update_meta_json(tmp_path, spike)
    meta = read_meta(tmp_path)
    assert meta[spike.id].languages == ["python"]
    assert meta[spike.id].image_count == 2


def test_update_meta_json_overwrites_existing(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    spike = _make_spike()
    update_meta_json(tmp_path, spike)
    updated = _make_spike(title="New Title", tags=["tag-b"])
    update_meta_json(tmp_path, updated)
    meta = read_meta(tmp_path)
    assert meta[spike.id].title == "New Title"
    assert meta[spike.id].tags == ["tag-b"]


def test_remove_from_meta_json_deletes_entry(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    spike = _make_spike()
    update_meta_json(tmp_path, spike)
    remove_from_meta_json(tmp_path, spike.id)
    meta = read_meta(tmp_path)
    assert spike.id not in meta


def test_remove_from_meta_json_noop_when_missing(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    remove_from_meta_json(tmp_path, "does-not-exist")  # must not raise


########################################################################################################################
# list_all_meta
########################################################################################################################


def test_list_all_meta_empty(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    assert list_all_meta(tmp_path) == []


def test_list_all_meta_sorted_by_modified_at_desc(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    older = _make_spike(
        "aaaaaaaa-0000-0000-0000-000000000001",
        modified_at="2025-01-01T09:00:00+00:00",
    )
    newer = _make_spike(
        "aaaaaaaa-0000-0000-0000-000000000002",
        modified_at="2025-06-01T12:00:00+00:00",
    )
    update_meta_json(tmp_path, older)
    update_meta_json(tmp_path, newer)
    entries = list_all_meta(tmp_path)
    assert entries[0].id == newer.id
    assert entries[1].id == older.id


########################################################################################################################
# append_log
########################################################################################################################


def test_append_log_creates_entries(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    append_log(tmp_path, "first event")
    append_log(tmp_path, "second event")
    log_files = sorted(log_dir(tmp_path).glob("*.json"))
    assert len(log_files) == 2
    combined = " ".join(f.read_text(encoding="utf-8") for f in log_files)
    assert "first event" in combined
    assert "second event" in combined


########################################################################################################################
# _parse_hierarchy
########################################################################################################################


def test_parse_hierarchy_empty_file(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    assert parse_hierarchy(hierarchy_path(tmp_path)) == {}


def test_parse_hierarchy_assigns_community_indices(tmp_path: Path) -> None:
    content = (
        "# Hierarchy\n\n"
        "## Community: Machine Learning\n"
        "- aaaaaaaa-0000-0000-0000-000000000001 (Neural nets)\n"
        "- aaaaaaaa-0000-0000-0000-000000000002 (Backprop)\n\n"
        "## Community: Systems\n"
        "- aaaaaaaa-0000-0000-0000-000000000003 (Kubernetes)\n"
    )
    p = tmp_path / "hierarchy.md"
    p.write_text(content, encoding="utf-8")
    result = parse_hierarchy(p)
    assert result["aaaaaaaa-0000-0000-0000-000000000001"] == (0, "Machine Learning")
    assert result["aaaaaaaa-0000-0000-0000-000000000002"] == (0, "Machine Learning")
    assert result["aaaaaaaa-0000-0000-0000-000000000003"] == (1, "Systems")


########################################################################################################################
# _parse_connections
########################################################################################################################

_UUID_A = "aaaaaaaa-0000-0000-0000-000000000001"
_UUID_B = "aaaaaaaa-0000-0000-0000-000000000002"
_UUID_C = "aaaaaaaa-0000-0000-0000-000000000003"


def test_parse_connections_empty_file(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    assert parse_connections(connections_path(tmp_path), {_UUID_A}) == []


def test_parse_connections_returns_valid_pairs(tmp_path: Path) -> None:
    content = f"# Connections\n\n- {_UUID_A} <-> {_UUID_B}: both cover RAG\n"
    p = tmp_path / "connections.md"
    p.write_text(content, encoding="utf-8")
    result = parse_connections(p, {_UUID_A, _UUID_B})
    assert (_UUID_A, _UUID_B) in result


def test_parse_connections_excludes_unknown_ids(tmp_path: Path) -> None:
    content = f"# Connections\n\n- {_UUID_A} <-> {_UUID_C}: test\n"
    p = tmp_path / "connections.md"
    p.write_text(content, encoding="utf-8")
    # _UUID_C is not in the valid set
    result = parse_connections(p, {_UUID_A, _UUID_B})
    assert result == []


def test_parse_connections_no_self_loops(tmp_path: Path) -> None:
    content = f"# Connections\n\n- {_UUID_A} <-> {_UUID_A}: self\n"
    p = tmp_path / "connections.md"
    p.write_text(content, encoding="utf-8")
    result = parse_connections(p, {_UUID_A})
    assert result == []


########################################################################################################################
# _within_days
########################################################################################################################


def test_within_days_true_for_same_day() -> None:
    assert _within_days("2025-01-01T00:00:00+00:00", "2025-01-01T12:00:00+00:00", 7)


def test_within_days_true_at_boundary() -> None:
    assert _within_days("2025-01-01T00:00:00+00:00", "2025-01-08T00:00:00+00:00", 7)


def test_within_days_false_beyond_boundary() -> None:
    assert not _within_days("2025-01-01T00:00:00+00:00", "2025-01-09T00:00:00+00:00", 7)


def test_within_days_false_on_invalid_ts() -> None:
    assert not _within_days("not-a-date", "2025-01-01T00:00:00+00:00", 7)


########################################################################################################################
# get_graph
########################################################################################################################


def test_get_graph_empty_workspace(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    data = get_graph(tmp_path, zoom=2)
    assert data == {"nodes": [], "edges": []}


def test_get_graph_spike_nodes_present(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    spike = _make_spike()
    update_meta_json(tmp_path, spike)
    data = get_graph(tmp_path, zoom=2)
    node_ids = [n["id"] for n in data["nodes"]]
    assert spike.id in node_ids


def test_get_graph_tag_edge_between_shared_tags(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    a = _make_spike("aaaaaaaa-0000-0000-0000-000000000001", tags=["ml", "rag"])
    b = _make_spike("aaaaaaaa-0000-0000-0000-000000000002", tags=["rag"])
    update_meta_json(tmp_path, a)
    update_meta_json(tmp_path, b)
    data = get_graph(tmp_path, zoom=2)
    tag_edges = [e for e in data["edges"] if e["type"] == "tag"]
    sources = {frozenset({e["source"], e["target"]}) for e in tag_edges}
    assert frozenset({a.id, b.id}) in sources


def test_get_graph_no_tag_edge_between_disjoint_tags(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    a = _make_spike("aaaaaaaa-0000-0000-0000-000000000001", tags=["ml"])
    b = _make_spike("aaaaaaaa-0000-0000-0000-000000000002", tags=["rag"])
    update_meta_json(tmp_path, a)
    update_meta_json(tmp_path, b)
    data = get_graph(tmp_path, zoom=2)
    tag_edges = [e for e in data["edges"] if e["type"] == "tag"]
    assert tag_edges == []


def test_get_graph_zoom0_returns_cluster_nodes(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    spike = _make_spike()
    update_meta_json(tmp_path, spike)
    hierarchy_path(tmp_path).write_text(
        f"## Community: Testing\n- {spike.id} (Test Spike)\n",
        encoding="utf-8",
    )
    data = get_graph(tmp_path, zoom=0)
    cluster_nodes = [n for n in data["nodes"] if n["type"] == "cluster"]
    assert len(cluster_nodes) == 1
    assert cluster_nodes[0]["label"] == "Testing"


def test_get_graph_zoom1_returns_cluster_and_spike_nodes(tmp_path: Path) -> None:
    init_wiki(tmp_path)
    spike = _make_spike()
    update_meta_json(tmp_path, spike)
    hierarchy_path(tmp_path).write_text(
        f"## Community: Testing\n- {spike.id} (Test Spike)\n",
        encoding="utf-8",
    )
    data = get_graph(tmp_path, zoom=1)
    types = {n["type"] for n in data["nodes"]}
    assert "cluster" in types
    assert "spike" in types
    cluster_edges = [e for e in data["edges"] if e["type"] == "cluster"]
    assert len(cluster_edges) == 1


########################################################################################################################
# _remove_from_index
########################################################################################################################

_ID_A = "aaaaaaaa-0000-0000-0000-000000000001"
_ID_B = "bbbbbbbb-0000-0000-0000-000000000002"


def test_remove_from_index_removes_target_section() -> None:
    text = f"# Braindump Index\n\n## {_ID_A}\n**Title:** Spike A\n\n## {_ID_B}\n**Title:** Spike B\n"
    result = _remove_from_index(text, _ID_A)
    assert _ID_A not in result
    assert _ID_B in result


def test_remove_from_index_last_section() -> None:
    text = f"## {_ID_A}\n**Title:** Spike A\n\n## {_ID_B}\n**Title:** Spike B\n"
    result = _remove_from_index(text, _ID_B)
    assert _ID_B not in result
    assert _ID_A in result


def test_remove_from_index_noop_when_absent() -> None:
    text = f"## {_ID_B}\n**Title:** Spike B\n"
    result = _remove_from_index(text, _ID_A)
    assert result == text


def test_remove_from_index_no_double_blank_lines() -> None:
    text = f"## {_ID_A}\n**Title:** A\n\n\n## {_ID_B}\n**Title:** B\n"
    result = _remove_from_index(text, _ID_A)
    assert "\n\n\n" not in result


########################################################################################################################
# _remove_from_connections
########################################################################################################################


def test_remove_from_connections_removes_lines_mentioning_id() -> None:
    text = f"- {_ID_A} <-> {_ID_B}: shared concept\n- {_ID_B} <-> {_ID_A}: another link\n"
    result = _remove_from_connections(text, _ID_A)
    assert _ID_A not in result


def test_remove_from_connections_keeps_unrelated_lines() -> None:
    id_c = "cccccccc-0000-0000-0000-000000000003"
    text = f"- {_ID_A} <-> {_ID_B}: shared concept\n- {_ID_B} <-> {id_c}: other link\n"
    result = _remove_from_connections(text, _ID_A)
    assert id_c in result
    assert _ID_B in result


def test_remove_from_connections_noop_when_absent() -> None:
    text = f"- {_ID_B} <-> {_ID_B}: self\n"
    result = _remove_from_connections(text, _ID_A)
    assert _ID_B in result


########################################################################################################################
# _remove_from_hierarchy
########################################################################################################################


def test_remove_from_hierarchy_removes_spike_bullet() -> None:
    text = f"## Community: Testing\n- {_ID_A} (Spike A)\n- {_ID_B} (Spike B)\n"
    result = _remove_from_hierarchy(text, _ID_A)
    assert _ID_A not in result
    assert _ID_B in result


def test_remove_from_hierarchy_drops_empty_community() -> None:
    text = f"## Community: Solo\n- {_ID_A} (Only Spike)\n"
    result = _remove_from_hierarchy(text, _ID_A)
    assert "Community: Solo" not in result


def test_remove_from_hierarchy_keeps_other_communities() -> None:
    text = f"## Community: Alpha\n- {_ID_A} (Spike A)\n\n## Community: Beta\n- {_ID_B} (Spike B)\n"
    result = _remove_from_hierarchy(text, _ID_A)
    assert "Community: Alpha" not in result
    assert "Community: Beta" in result
    assert _ID_B in result


def test_remove_from_hierarchy_noop_when_absent() -> None:
    text = f"## Community: Beta\n- {_ID_B} (Spike B)\n"
    result = _remove_from_hierarchy(text, _ID_A)
    assert "Community: Beta" in result
    assert _ID_B in result
