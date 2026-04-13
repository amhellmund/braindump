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

"""Wiki-grounded query pipeline — single LLM call using the wiki index.

The LLM receives the full ``braindump/index.md`` (which contains LLM-authored
summaries of every spike) and is instructed to answer from that compiled
knowledge, citing sources by their numbered position in the spike reference
list.  Because ``index.md`` summaries are rich enough to answer most
questions, no raw spike content is sent to the model.
"""

import asyncio
import re
from pathlib import Path
from typing import NamedTuple

from braindump import dirs, wiki
from braindump.llm import ChatBackend
from braindump.types import ChatTurn, QueryResponse, QuerySource


class QueryResult(NamedTuple):
    """Result of a wiki query, including LLM usage metadata."""

    response: QueryResponse
    cost_usd: float
    total_tokens: int


########################################################################################################################
# Constants                                                                                                            #
########################################################################################################################

_SNIPPET_LEN = 250  # characters shown in source cards

_SYSTEM_PROMPT = (
    "You are braindump, an AI assistant for a personal knowledge base. "
    "You answer questions using ONLY the compiled knowledge index provided in the user message. "
    "The index contains LLM-authored summaries of all notes ('spikes') in the knowledge base, "
    "each identified by a number [N]. "
    "Cite every piece of information inline using [N] notation matching the source number. "
    "If the index summaries are insufficient to answer confidently, say so explicitly — "
    "do not invent facts or reference information not present in the index."
)

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################


async def run_query(
    workspace: Path,
    backend: ChatBackend,
    query_text: str,
    history: list[ChatTurn] | None = None,
) -> QueryResult:
    """Answer a user query using the compiled wiki index (single LLM call).

    The pipeline:
    1. Read ``braindump/meta.json`` to build a numbered spike reference list.
    2. Read ``braindump/index.md`` for the LLM-authored summaries.
    3. Call the LLM with: system prompt + spike reference + index + question.
    4. Parse [N] citations from the answer to build ``QuerySource`` objects.
    5. Append the query event to ``braindump/log.md``.

    Args:
        workspace: Root workspace directory.
        backend: Active LLM backend.
        query_text: Raw user question.
        history: Prior turns from the same chat session, oldest first.

    Returns:
        :class:`QueryResult` with ``response``, ``cost_usd``, and ``total_tokens``.
    """
    meta = wiki.list_all_meta(workspace)  # sorted newest-first

    if not meta:
        return QueryResult(
            response=QueryResponse(answer="No spikes found in your knowledge base yet.", citations=[]),
            cost_usd=0.0,
            total_tokens=0,
        )

    index_content = dirs.index_path(workspace).read_text(encoding="utf-8")

    # Build a numbered reference table so the LLM can cite by [N]
    spike_ref: list[dict] = []
    ref_lines: list[str] = []
    for i, entry in enumerate(meta, start=1):
        tags_str = ", ".join(entry.tags) or "—"
        ref_lines.append(f'[{i}] {entry.id} — "{entry.title}" (tags: {tags_str})')
        spike_ref.append({"index": i, **entry.model_dump()})

    reference_block = "\n".join(ref_lines)
    user_message = (
        f"Spike reference (use [N] to cite):\n{reference_block}\n\n"
        f"Knowledge index (summaries):\n{index_content}\n\n"
        f"Question:\n<user_question>{query_text}</user_question>"
    )

    completion = await asyncio.to_thread(backend.complete_with_usage, _SYSTEM_PROMPT, history or [], user_message)

    summaries = _parse_index_summaries(index_content)
    citations = _extract_citations(completion.text, spike_ref, summaries)
    wiki.append_log(workspace, f"Query answered: {query_text[:80]!r}")

    return QueryResult(
        response=QueryResponse(answer=completion.text, citations=citations),
        cost_usd=completion.cost_usd,
        total_tokens=completion.total_tokens,
    )


########################################################################################################################
# Implementation                                                                                                       #
########################################################################################################################

_CITATION_RE = re.compile(r"\[(\d+)\]")
_INDEX_UUID_HEADING_RE = re.compile(
    r"^## ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s*$",
    re.MULTILINE,
)
_SUMMARY_LINE_RE = re.compile(r"^\*\*Summary:\*\*\s*(.+)$", re.MULTILINE)


def _parse_index_summaries(index_content: str) -> dict[str, str]:
    """Parse ``index.md`` and return a mapping of spike UUID to summary text.

    Each section in ``index.md`` starts with a ``## {uuid}`` heading and
    contains a ``**Summary:** …`` line.  Only the first summary line in each
    section is captured; multi-sentence summaries on a single line are kept
    as-is.

    Args:
        index_content: Full text of ``braindump/index.md``.

    Returns:
        Dict mapping spike UUID strings to their summary text.
    """
    summaries: dict[str, str] = {}
    parts = _INDEX_UUID_HEADING_RE.split(index_content)
    # split() with a capturing group gives [before, uuid1, body1, uuid2, body2, …]
    it = iter(parts[1:])
    for uuid, body in zip(it, it, strict=False):
        if m := _SUMMARY_LINE_RE.search(body):
            summaries[uuid] = m.group(1).strip()
    return summaries


def _extract_citations(
    answer: str,
    spike_ref: list[dict],
    summaries: dict[str, str],
) -> list[QuerySource]:
    """Parse [N] citation markers from the answer and build QuerySource objects.

    Only indices that actually appear in the answer are included.  Each index
    maps to its entry in ``spike_ref`` (built from ``braindump/meta.json``).
    The snippet is taken from the LLM-authored summary in ``index.md`` when
    available, falling back to the spike title.

    Args:
        answer: The raw LLM answer text (may contain [1], [2], … markers).
        spike_ref: List of dicts with ``index``, ``id``, ``title`` keys.
        summaries: UUID → summary text, parsed from ``braindump/index.md``.

    Returns:
        Deduplicated, ordered list of :class:`~braindump.models.QuerySource`.
    """
    ref_by_index = {entry["index"]: entry for entry in spike_ref}
    seen: set[int] = set()
    sources: list[QuerySource] = []

    for m in _CITATION_RE.finditer(answer):
        n = int(m.group(1))
        if n in seen or n not in ref_by_index:
            continue
        seen.add(n)
        entry = ref_by_index[n]
        title = entry.get("title", entry["id"])
        snippet = summaries.get(entry["id"], title)[:_SNIPPET_LEN]
        sources.append(
            QuerySource(
                index=n,
                spikeId=entry["id"],
                title=title,
                section="",
                snippet=snippet,
            )
        )

    return sources
