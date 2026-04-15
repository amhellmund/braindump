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

"""Unit tests for braindump.storage."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from braindump.storage import (
    _count_images,
    _extract_languages,
    _find_spike_file,
    _title_to_slug,
    _validate_image_magic,
    delete_spike_file,
    enrich_spike,
    list_spike_ids,
    parse_spike,
    read_image,
    read_spike_raw,
    spikes_dir,
    write_image,
    write_spike,
)

# Fixed UUID strings used across tests
_ID_1 = "aaaaaaaa-0000-0000-0000-000000000001"
_ID_2 = "bbbbbbbb-0000-0000-0000-000000000002"
_ID_3 = "cccccccc-0000-0000-0000-000000000003"

########################################################################################################################
# enrich_spike
########################################################################################################################


def _fm(raw: str) -> dict:
    return frontmatter.loads(raw).metadata


def test_enrich_spike_adds_timestamps_when_absent() -> None:
    raw = "---\ntags: [a]\n---\n\n# Hello\n"
    result = enrich_spike(raw, "2025-01-01T00:00:00", "2025-06-01T12:00:00")
    meta = _fm(result)
    assert meta["created"] == "2025-01-01T00:00:00"
    assert meta["modified"] == "2025-06-01T12:00:00"


def test_enrich_spike_updates_existing_timestamps() -> None:
    raw = "---\ncreated: 2020-01-01T00:00:00\nmodified: 2020-01-01T00:00:00\n---\n\n# Hello\n"
    result = enrich_spike(raw, "2025-01-01T00:00:00", "2025-06-01T12:00:00")
    meta = _fm(result)
    assert meta["created"] == "2025-01-01T00:00:00"
    assert meta["modified"] == "2025-06-01T12:00:00"


def test_enrich_spike_preserves_other_frontmatter() -> None:
    raw = "---\ntags: [rag, python]\ndate: 2024-03-15\n---\n\n# Hello\n"
    result = enrich_spike(raw, "2025-01-01T00:00:00", "2025-06-01T12:00:00")
    meta = _fm(result)
    assert meta["tags"] == ["rag", "python"]
    assert str(meta["date"]) == "2024-03-15"


def test_enrich_spike_works_without_frontmatter() -> None:
    raw = "# Hello\n\nNo frontmatter here.\n"
    result = enrich_spike(raw, "2025-01-01T00:00:00", "2025-06-01T12:00:00")
    meta = _fm(result)
    assert meta["created"] == "2025-01-01T00:00:00"
    assert meta["modified"] == "2025-06-01T12:00:00"


########################################################################################################################
# _title_to_slug
########################################################################################################################


def test_title_to_slug_replaces_spaces() -> None:
    assert _title_to_slug("Hello World") == "Hello_World"


def test_title_to_slug_collapses_multiple_spaces() -> None:
    assert _title_to_slug("Hello   World") == "Hello_World"


def test_title_to_slug_strips_unsafe_chars() -> None:
    assert _title_to_slug('My "Spike": A/B') == "My_Spike_AB"


def test_title_to_slug_caps_at_64_chars() -> None:
    long_title = "A" * 100
    assert len(_title_to_slug(long_title)) == 64


def test_title_to_slug_empty_after_stripping() -> None:
    assert _title_to_slug(':"<>') == ""


########################################################################################################################
# write_spike / read_spike_raw
########################################################################################################################


def test_write_spike_creates_file_with_title_slug(tmp_path: Path) -> None:
    write_spike(tmp_path, _ID_1, "# Hello World\n")
    assert (tmp_path / "spikes" / f"{_ID_1}_Hello_World.md").exists()


def test_write_spike_content_matches(tmp_path: Path) -> None:
    content = "---\ntags: []\n---\n\n# Hello\n"
    write_spike(tmp_path, _ID_1, content)
    assert read_spike_raw(tmp_path, _ID_1) == content


def test_write_spike_untitled_when_no_heading(tmp_path: Path) -> None:
    write_spike(tmp_path, _ID_1, "---\ntags: []\n---\n\nNo heading.\n")
    assert (tmp_path / "spikes" / f"{_ID_1}_Untitled.md").exists()


def test_write_spike_renames_file_on_title_change(tmp_path: Path) -> None:
    write_spike(tmp_path, _ID_1, "# Original Title\n")
    old_path = tmp_path / "spikes" / f"{_ID_1}_Original_Title.md"
    assert old_path.exists()

    write_spike(tmp_path, _ID_1, "# New Title\n")
    assert not old_path.exists()
    assert (tmp_path / "spikes" / f"{_ID_1}_New_Title.md").exists()


def test_write_spike_overwrites_same_title(tmp_path: Path) -> None:
    write_spike(tmp_path, _ID_1, "# Same\n\nFirst.\n")
    write_spike(tmp_path, _ID_1, "# Same\n\nUpdated.\n")
    assert read_spike_raw(tmp_path, _ID_1) == "# Same\n\nUpdated.\n"
    # Only one file should exist for this spike
    assert len(list((tmp_path / "spikes").glob(f"{_ID_1}_*.md"))) == 1


def test_read_spike_raw_returns_content(tmp_path: Path) -> None:
    content = "---\ntags: []\n---\n\n# Hello\n"
    write_spike(tmp_path, _ID_1, content)
    assert read_spike_raw(tmp_path, _ID_1) == content


def test_read_spike_raw_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Spike file not found"):
        read_spike_raw(tmp_path, _ID_1)


########################################################################################################################
# _find_spike_file
########################################################################################################################


def test_find_spike_file_finds_new_format(tmp_path: Path) -> None:
    write_spike(tmp_path, _ID_1, "# My Spike\n")
    path = _find_spike_file(tmp_path, _ID_1)
    assert path is not None
    assert path.name == f"{_ID_1}_My_Spike.md"


def test_find_spike_file_returns_none_when_missing(tmp_path: Path) -> None:
    assert _find_spike_file(tmp_path, _ID_1) is None


########################################################################################################################
# delete_spike_file
########################################################################################################################


def test_delete_spike_file_removes_file(tmp_path: Path) -> None:
    write_spike(tmp_path, _ID_1, "# Hello\n")
    delete_spike_file(tmp_path, _ID_1)
    assert _find_spike_file(tmp_path, _ID_1) is None


def test_delete_spike_file_noop_when_missing(tmp_path: Path) -> None:
    # Should not raise even when the file does not exist.
    delete_spike_file(tmp_path, _ID_1)


########################################################################################################################
# spikes_dir
########################################################################################################################


def test_spikes_dir_creates_directory(tmp_path: Path) -> None:
    d = spikes_dir(tmp_path)
    assert d.is_dir()
    assert d == tmp_path / "spikes"


def test_spikes_dir_idempotent(tmp_path: Path) -> None:
    spikes_dir(tmp_path)
    spikes_dir(tmp_path)  # calling twice must not raise
    assert (tmp_path / "spikes").is_dir()


########################################################################################################################
# parse_spike
########################################################################################################################


_FULL_SPIKE = (
    "---\n"
    "tags: [rag, retrieval]\n"
    "created: 2025-01-01T09:00:00\n"
    "modified: 2025-06-01T12:00:00\n"
    "---\n\n"
    "# My Spike\n\n"
    "Intro paragraph.\n\n"
    "## Section One\n\n"
    "First section content.\n\n"
    "## Section Two\n\n"
    "Second section content.\n"
)


def test_parse_spike_title() -> None:
    result = parse_spike(_FULL_SPIKE, "spike-1")
    assert result.title == "My Spike"


def test_parse_spike_id() -> None:
    result = parse_spike(_FULL_SPIKE, "spike-1")
    assert result.id == "spike-1"


def test_parse_spike_tags() -> None:
    result = parse_spike(_FULL_SPIKE, "spike-1")
    assert result.tags == ["rag", "retrieval"]


def test_parse_spike_timestamps() -> None:
    result = parse_spike(_FULL_SPIKE, "spike-1")
    assert "2025-01-01" in result.createdAt
    assert "2025-06-01" in result.modifiedAt


def test_parse_spike_raw_preserved() -> None:
    result = parse_spike(_FULL_SPIKE, "spike-1")
    assert result.raw == _FULL_SPIKE


def test_parse_spike_sections() -> None:
    result = parse_spike(_FULL_SPIKE, "spike-1")
    assert len(result.sections) == 3
    assert result.sections[0].heading is None
    assert result.sections[0].content == "Intro paragraph."
    assert result.sections[1].heading == "Section One"
    assert result.sections[1].content == "First section content."
    assert result.sections[2].heading == "Section Two"
    assert result.sections[2].content == "Second section content."


def test_parse_spike_no_title_defaults_to_untitled() -> None:
    raw = "---\ntags: []\n---\n\nNo heading here.\n"
    result = parse_spike(raw, "spike-x")
    assert result.title == "Untitled"


def test_parse_spike_no_h2_sections() -> None:
    raw = "---\ntags: []\n---\n\n# Only Title\n\nSome paragraph.\n"
    result = parse_spike(raw, "spike-x")
    assert len(result.sections) == 1
    assert result.sections[0].heading is None
    assert result.sections[0].content == "Some paragraph."


def test_parse_spike_empty_tags() -> None:
    raw = "---\ntags: []\n---\n\n# Title\n"
    result = parse_spike(raw, "spike-x")
    assert result.tags == []


def test_parse_spike_missing_tags_field() -> None:
    raw = "---\n---\n\n# Title\n"
    result = parse_spike(raw, "spike-x")
    assert result.tags == []


def test_parse_spike_non_list_tags_ignored() -> None:
    raw = "---\ntags: just-a-string\n---\n\n# Title\n"
    result = parse_spike(raw, "spike-x")
    assert result.tags == []


def test_parse_spike_languages_extracted() -> None:
    raw = "# Title\n\n```python\nprint('hi')\n```\n\n```bash\necho hi\n```\n"
    result = parse_spike(raw, "spike-x")
    assert result.languages == ["python", "bash"]


def test_parse_spike_languages_deduplicated() -> None:
    raw = "# Title\n\n```python\nx = 1\n```\n\n```python\ny = 2\n```\n"
    result = parse_spike(raw, "spike-x")
    assert result.languages == ["python"]


def test_parse_spike_languages_empty_when_no_code_blocks() -> None:
    raw = "# Title\n\nJust prose.\n"
    result = parse_spike(raw, "spike-x")
    assert result.languages == []


def test_parse_spike_languages_omits_unlabelled_blocks() -> None:
    raw = "# Title\n\n```\nsome code\n```\n"
    result = parse_spike(raw, "spike-x")
    assert result.languages == []


def test_parse_spike_image_count() -> None:
    raw = "# Title\n\n![diagram](images/a.png)\n\n![chart](images/b.png)\n"
    result = parse_spike(raw, "spike-x")
    assert result.image_count == 2


def test_parse_spike_image_count_zero_when_no_images() -> None:
    raw = "# Title\n\nNo images here.\n"
    result = parse_spike(raw, "spike-x")
    assert result.image_count == 0


########################################################################################################################
# _extract_languages / _count_images
########################################################################################################################


def test_extract_languages_returns_ordered_unique() -> None:
    tokens = [
        {"type": "block_code", "attrs": {"info": "python"}, "raw": "x=1"},
        {"type": "block_code", "attrs": {"info": "bash"}, "raw": "echo hi"},
        {"type": "block_code", "attrs": {"info": "python"}, "raw": "y=2"},
    ]
    assert _extract_languages(tokens) == ["python", "bash"]


def test_extract_languages_strips_extra_info() -> None:
    # e.g. ```python filename.py
    tokens = [{"type": "block_code", "attrs": {"info": "python filename.py"}, "raw": "pass"}]
    assert _extract_languages(tokens) == ["python"]


def test_extract_languages_ignores_non_code_tokens() -> None:
    tokens = [{"type": "paragraph", "children": [{"type": "text", "raw": "hello"}]}]
    assert _extract_languages(tokens) == []


def test_count_images_top_level() -> None:
    tokens = [
        {
            "type": "paragraph",
            "children": [
                {"type": "image", "attrs": {"url": "a.png"}, "children": []},
                {"type": "image", "attrs": {"url": "b.png"}, "children": []},
            ],
        },
    ]
    assert _count_images(tokens) == 2


def test_count_images_none() -> None:
    tokens = [{"type": "paragraph", "children": [{"type": "text", "raw": "hi"}]}]
    assert _count_images(tokens) == 0


########################################################################################################################
# list_spike_ids
########################################################################################################################


def test_list_spike_ids_empty_when_no_spikes(tmp_path: Path) -> None:
    assert list_spike_ids(tmp_path) == []


def test_list_spike_ids_returns_uuids(tmp_path: Path) -> None:
    write_spike(tmp_path, _ID_1, "# Alpha\n")
    write_spike(tmp_path, _ID_2, "# Beta\n")
    ids = list_spike_ids(tmp_path)
    assert sorted(ids) == sorted([_ID_1, _ID_2])


def test_list_spike_ids_ignores_non_uuid_files(tmp_path: Path) -> None:
    spikes_dir(tmp_path)  # ensure directory exists
    (tmp_path / "spikes" / "readme.txt").write_text("not a spike", encoding="utf-8")
    (tmp_path / "spikes" / "notes.md").write_text("not a spike", encoding="utf-8")
    write_spike(tmp_path, _ID_1, "# Real\n")
    assert list_spike_ids(tmp_path) == [_ID_1]


########################################################################################################################
# _validate_image_magic
########################################################################################################################

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
_JPEG_MAGIC = b"\xff\xd8\xff" + b"\x00" * 8
_GIF87_MAGIC = b"GIF87a" + b"\x00" * 8
_GIF89_MAGIC = b"GIF89a" + b"\x00" * 8
_WEBP_MAGIC = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 8


def test_validate_image_magic_png_valid() -> None:
    assert _validate_image_magic(_PNG_MAGIC, "image/png") is True


def test_validate_image_magic_png_rejects_jpeg_bytes() -> None:
    assert _validate_image_magic(_JPEG_MAGIC, "image/png") is False


def test_validate_image_magic_jpeg_valid() -> None:
    assert _validate_image_magic(_JPEG_MAGIC, "image/jpeg") is True


def test_validate_image_magic_jpeg_rejects_png_bytes() -> None:
    assert _validate_image_magic(_PNG_MAGIC, "image/jpeg") is False


def test_validate_image_magic_gif87_valid() -> None:
    assert _validate_image_magic(_GIF87_MAGIC, "image/gif") is True


def test_validate_image_magic_gif89_valid() -> None:
    assert _validate_image_magic(_GIF89_MAGIC, "image/gif") is True


def test_validate_image_magic_gif_rejects_random_bytes() -> None:
    assert _validate_image_magic(b"notgif" + b"\x00" * 8, "image/gif") is False


def test_validate_image_magic_webp_valid() -> None:
    assert _validate_image_magic(_WEBP_MAGIC, "image/webp") is True


def test_validate_image_magic_webp_requires_riff_and_webp_marker() -> None:
    # RIFF present but no WEBP marker at offset 8
    bad = b"RIFF\x00\x00\x00\x00AVI " + b"\x00" * 8
    assert _validate_image_magic(bad, "image/webp") is False


def test_validate_image_magic_rejects_empty_data() -> None:
    assert _validate_image_magic(b"", "image/png") is False


########################################################################################################################
# write_image / read_image
########################################################################################################################


def test_write_image_rejects_wrong_magic_bytes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not match declared type"):
        write_image(tmp_path, b"this is not a png" + b"\x00" * 20, "image/png")


def test_write_image_accepts_valid_png(tmp_path: Path) -> None:
    filename = write_image(tmp_path, _PNG_MAGIC, "image/png")
    assert filename.endswith(".png")


def test_read_image_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid image path"):
        read_image(tmp_path, "../somefile.png")
