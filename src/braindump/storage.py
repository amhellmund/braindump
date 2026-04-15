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

"""Markdown file I/O and parsing for spike persistence."""

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

import frontmatter
import mistune

from braindump.dirs import images_dir, spikes_dir
from braindump.types import Section, SpikeResponse

_logger = logging.getLogger(__name__)

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################


def enrich_spike(raw: str, created_at: str, modified_at: str) -> str:
    """Add or update ``created`` and ``modified`` timestamps in the frontmatter.

    The returned string is the canonical on-disk representation.  All other
    frontmatter fields (tags, date, …) are preserved unchanged.

    Args:
        raw: Full markdown content, may or may not already have timestamps.
        created_at: ISO-8601 creation timestamp to embed.
        modified_at: ISO-8601 last-modified timestamp to embed.

    Returns:
        Raw markdown with ``created`` and ``modified`` set in the frontmatter.
    """
    post = frontmatter.loads(raw)
    post.metadata["created"] = created_at
    post.metadata["modified"] = modified_at
    return frontmatter.dumps(post)


def write_spike(workspace: Path, spike_id: str, raw: str) -> None:
    """Write raw markdown content to a spike file.

    The file is named ``{spike_id}_{title_slug}.md`` where ``title_slug`` is
    the H1 title with spaces replaced by underscores. If the title changed
    since the last write the old file is removed before writing the new one.

    Args:
        workspace: Root workspace directory.
        spike_id: UUID string used as the filename prefix.
        raw: Full markdown content including frontmatter.
    """
    title = _extract_title_from_raw(raw)
    slug = _title_to_slug(title)
    new_name = f"{spike_id}_{slug}.md" if slug else f"{spike_id}.md"
    new_path = spikes_dir(workspace) / new_name

    existing = _find_spike_file(workspace, spike_id)
    if existing is not None and existing != new_path:
        existing.unlink()

    new_path.write_text(raw, encoding="utf-8")


def read_spike_raw(workspace: Path, spike_id: str) -> str:
    """Read raw markdown content from a spike file.

    Args:
        workspace: Root workspace directory.
        spike_id: UUID string used as the filename prefix.

    Returns:
        Full markdown content including frontmatter.

    Raises:
        FileNotFoundError: If the spike file does not exist.
    """
    path = _find_spike_file(workspace, spike_id)
    if path is None:
        raise FileNotFoundError(f"Spike file not found: {spike_id}")
    return path.read_text(encoding="utf-8")


def delete_spike_file(workspace: Path, spike_id: str) -> None:
    """Delete a spike's markdown file if it exists.

    Args:
        workspace: Root workspace directory.
        spike_id: UUID string used as the filename prefix.
    """
    path = _find_spike_file(workspace, spike_id)
    if path is not None:
        path.unlink()


def parse_spike(raw: str, spike_id: str) -> SpikeResponse:
    """Parse raw markdown into a SpikeResponse.

    Timestamps are read from the ``created`` and ``modified`` frontmatter
    fields so the file is the single source of truth.

    Args:
        raw: Full markdown content including frontmatter.
        spike_id: UUID string for the spike.

    Returns:
        Fully populated SpikeResponse.
    """
    post = frontmatter.loads(raw)
    content: str = post.content
    tags_raw = post.metadata.get("tags", [])
    tags: list[str] = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []

    tokens: list[dict] = _md_parser(content)  # type: ignore[assignment]
    title = "Untitled"
    for token in tokens:
        if token["type"] == "heading" and token["attrs"]["level"] == 1:
            title = _inline_to_text(token.get("children", []))
            break

    return SpikeResponse(
        id=spike_id,
        title=title,
        tags=tags,
        createdAt=_to_iso(post.metadata.get("created", "")),
        modifiedAt=_to_iso(post.metadata.get("modified", "")),
        raw=raw,
        sections=_parse_sections(tokens),
        languages=_extract_languages(tokens),
        image_count=_count_images(tokens),
    )


def list_spike_ids(workspace: Path) -> list[str]:
    """Return the IDs of all spikes present on disk.

    Scans ``<workspace>/spikes/`` for ``.md`` files whose names begin with a
    UUID and returns those UUIDs.  Does not read file contents — suitable for
    bulk existence checks.

    Args:
        workspace: Root workspace directory.

    Returns:
        Unsorted list of spike ID strings extracted from the filenames.
    """
    result: list[str] = []
    for p in spikes_dir(workspace).glob("*.md"):
        m = _SPIKE_ID_RE.match(p.stem)
        if m:
            result.append(m.group(1))
    return result


ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

_EXT_TO_MIME: dict[str, str] = {ext: mime for mime, ext in ALLOWED_IMAGE_TYPES.items()}

_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def _validate_image_magic(data: bytes, content_type: str) -> bool:
    """Return True when the leading magic bytes of *data* match *content_type*.

    Validates the actual file content rather than trusting the client-supplied
    MIME type, guarding against disguised payloads.
    """
    if content_type == "image/png":
        return len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n"
    if content_type == "image/jpeg":
        return len(data) >= 3 and data[:3] == b"\xff\xd8\xff"
    if content_type == "image/gif":
        return len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a")
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def write_image(workspace: Path, data: bytes, content_type: str) -> str:
    """Persist image bytes to disk and return the stored filename.

    Args:
        workspace: Root workspace directory.
        data: Raw image bytes.
        content_type: MIME type; must be one of the keys in ``ALLOWED_IMAGE_TYPES``.

    Returns:
        The filename (e.g. ``"abc123.png"``) stored under ``images_dir``.

    Raises:
        ValueError: If ``content_type`` is not supported or ``data`` exceeds 10 MB.
    """
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"Unsupported image type: {content_type!r}")
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds {_MAX_IMAGE_BYTES // 1024 // 1024} MB limit")
    if not _validate_image_magic(data, content_type):
        raise ValueError(f"Image content does not match declared type {content_type!r}")
    ext = ALLOWED_IMAGE_TYPES[content_type]
    filename = f"{uuid.uuid4()}{ext}"
    (images_dir(workspace) / filename).write_bytes(data)
    return filename


def read_image(workspace: Path, filename: str) -> tuple[bytes, str]:
    """Read image bytes and infer the MIME type from the file extension.

    Args:
        workspace: Root workspace directory.
        filename: Plain basename of the image file (e.g. ``"abc123.png"``).

    Returns:
        Tuple of ``(raw_bytes, mime_type)``.

    Raises:
        FileNotFoundError: If the image does not exist on disk.
        ValueError: If the file extension is not a known image type.
    """
    images_root = images_dir(workspace).resolve()
    path = (images_root / filename).resolve()
    if not path.is_relative_to(images_root):
        raise ValueError("Invalid image path")
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {filename}")
    mime = _EXT_TO_MIME.get(path.suffix.lower())
    if mime is None:
        raise ValueError(f"Unknown image extension: {path.suffix!r}")
    return path.read_bytes(), mime


########################################################################################################################
# Implementation                                                                                                       #
########################################################################################################################

_md_parser = mistune.create_markdown(renderer="ast")

# Matches a standard UUID at the start of a filename stem.
_SPIKE_ID_RE = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)

# Characters that are unsafe in filenames across common operating systems.
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _title_to_slug(title: str) -> str:
    """Convert a spike title to a filename-safe slug with underscores replacing spaces.

    Args:
        title: Raw spike title extracted from the H1 heading.

    Returns:
        Slug string, at most 64 characters long. Empty string if nothing remains.
    """
    slug = _UNSAFE_FILENAME_RE.sub("", title).strip()
    slug = re.sub(r"\s+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:64]


def _extract_title_from_raw(raw: str) -> str:
    """Extract the H1 title from raw markdown content.

    Args:
        raw: Full markdown including frontmatter.

    Returns:
        Title string, or ``"Untitled"`` when no H1 heading is found.
    """
    post = frontmatter.loads(raw)
    tokens: list[dict] = _md_parser(post.content)  # type: ignore[assignment]
    for token in tokens:
        if token["type"] == "heading" and token["attrs"]["level"] == 1:
            return _inline_to_text(token.get("children", []))
    return "Untitled"


def _find_spike_file(workspace: Path, spike_id: str) -> Path | None:
    """Locate a spike file by its UUID prefix.

    Args:
        workspace: Root workspace directory.
        spike_id: UUID string to look up.

    Returns:
        Path to the spike file, or ``None`` if no matching file exists.
    """
    matches = list(spikes_dir(workspace).glob(f"{spike_id}_*.md"))
    if len(matches) > 1:
        _logger.warning("Multiple files found for spike %s; using %s", spike_id, matches[0])
    if matches:
        return matches[0]
    # Fallback: UUID-only filename written when the title slug is empty.
    plain = spikes_dir(workspace) / f"{spike_id}.md"
    if plain.exists():
        return plain
    return None


def _to_iso(val: object) -> str:
    """Convert a frontmatter timestamp value to an ISO-8601 string.

    PyYAML parses bare datetime strings into ``datetime`` objects; this
    helper normalises both forms back to a string.
    """
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


def _extract_languages(tokens: list[dict]) -> list[str]:
    """Return deduplicated, ordered list of languages found in fenced code blocks.

    Args:
        tokens: Top-level mistune AST token list.

    Returns:
        Language identifiers in order of first appearance; empty strings are omitted.
    """
    langs: list[str] = []
    for token in tokens:
        if token["type"] == "block_code":
            info = (token.get("attrs", {}).get("info", "") or "").strip()
            lang = info.split()[0] if info else ""
            if lang and lang not in langs:
                langs.append(lang)
    return langs


def _count_images(nodes: list[dict]) -> int:
    """Recursively count image nodes in a mistune AST subtree.

    Args:
        nodes: List of AST nodes (top-level or inline children).

    Returns:
        Total number of ``image`` nodes found at any depth.
    """
    count = 0
    for node in nodes:
        if node["type"] == "image":
            count += 1
        if "children" in node:
            count += _count_images(node["children"])
    return count


def _inline_to_text(children: list[dict]) -> str:
    parts: list[str] = []
    for node in children:
        t = node["type"]
        if t == "text":
            parts.append(node.get("raw", ""))
        elif t == "codespan":
            parts.append(f"`{node.get('raw', '')}`")
        elif t == "strong":
            parts.append(f"**{_inline_to_text(node.get('children', []))}**")
        elif t == "emphasis":
            parts.append(f"*{_inline_to_text(node.get('children', []))}*")
        elif t == "image":
            alt = _inline_to_text(node.get("children", []))
            url = node.get("attrs", {}).get("url", "")
            parts.append(f"![{alt}]({url})")
        elif t == "link":
            label = _inline_to_text(node.get("children", []))
            url = node.get("attrs", {}).get("url", "")
            parts.append(f"[{label}]({url})")
        elif "children" in node:
            parts.append(_inline_to_text(node["children"]))
    return "".join(parts)


def _tokens_to_text(tokens: list[dict]) -> str:
    parts: list[str] = []
    for token in tokens:
        t = token["type"]
        if t == "paragraph":
            parts.append(_inline_to_text(token.get("children", [])))
        elif t == "block_code":
            info = token.get("attrs", {}).get("info", "") or ""
            parts.append(f"```{info}\n{token['raw']}```")
        elif t == "heading":
            level = token["attrs"]["level"]
            parts.append("#" * level + " " + _inline_to_text(token.get("children", [])))
        elif t == "list":
            ordered = token.get("attrs", {}).get("ordered", False)
            lines: list[str] = []
            for idx, item in enumerate(token.get("children", [])):
                item_text = _inline_to_text(
                    [child for node in item.get("children", []) for child in node.get("children", [])]
                )
                prefix = f"{idx + 1}." if ordered else "-"
                lines.append(f"{prefix} {item_text}")
            parts.append("\n".join(lines))
    return "\n\n".join(p for p in parts if p)


def _parse_sections(tokens: list[dict]) -> list[Section]:
    sections: list[Section] = []
    current_heading: str | None = None
    current_body: list[dict] = []

    for token in tokens:
        if token["type"] == "heading" and token["attrs"]["level"] == 2:
            if current_heading is not None:
                sections.append(Section(heading=current_heading, content=_tokens_to_text(current_body)))
            current_heading = _inline_to_text(token.get("children", []))
            current_body = []
        elif current_heading is not None:
            current_body.append(token)

    if current_heading is not None:
        sections.append(Section(heading=current_heading, content=_tokens_to_text(current_body)))

    return sections
