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

"""LLM-driven stream summarization."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from braindump import storage
from braindump import streams as streams_module
from braindump.dirs import index_path
from braindump.llm import ChatBackend
from braindump.types import StreamSummaryLogDetail
from braindump.wiki import _extract_index_section, append_log

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################

_SYSTEM_PROMPT = """\
You are a knowledge synthesizer for braindump, a personal knowledge base of Markdown notes called "spikes".
Produce a comprehensive, well-structured Markdown document synthesizing all spikes in a named stream.

Rules:
1. Output ONLY the Markdown document — no preamble, no wrapping code fences.
2. Use exactly these four top-level sections in order:
   ## Overview
   ## Key Themes
   ## Spike Highlights
   ## Synthesis
3. In "Spike Highlights", include a ### subsection for each spike (2-3 sentences each).
4. In "Synthesis", draw cross-cutting insights, patterns, or contradictions.
5. Every claim must be traceable to the provided spike content.
"""


async def generate_stream_summary(workspace: Path, stream_name: str, backend: ChatBackend) -> str:
    """Generate a markdown summary for all spikes in a named stream.

    Reads spike content and wiki index summaries, calls the LLM, writes the result
    to ``streams/summaries/{safe_name}.md``, and updates ``summary_at`` in streams.json.

    Args:
        workspace: Root workspace directory.
        stream_name: Name of the stream to summarize.
        backend: Active LLM backend.

    Returns:
        Generated summary markdown content.

    Raises:
        ValueError: If the stream has no assigned spikes.
        RuntimeError: If the LLM call fails.
    """
    assignments = streams_module.read_assignments(workspace)
    spike_ids = [sid for sid, sname in assignments.assignments.items() if sname == stream_name]
    if not spike_ids:
        raise ValueError(f"Stream '{stream_name}' has no spikes")

    index_text = index_path(workspace).read_text(encoding="utf-8") if index_path(workspace).exists() else ""

    spike_blocks: list[str] = []
    for spike_id in spike_ids:
        try:
            raw = storage.read_spike_raw(workspace, spike_id)
        except FileNotFoundError:
            continue
        spike = storage.parse_spike(raw, spike_id)
        index_section = _extract_index_section(index_text, spike_id)
        block = (
            f"### {spike.title} (ID: {spike_id})\n"
            f"**Tags:** {', '.join(spike.tags) or '(none)'}\n"
            f"**Modified:** {spike.modifiedAt}\n\n"
            f"**Wiki Summary:**\n{index_section or '(not yet indexed)'}\n\n"
            f"**Full Content:**\n{spike.raw}\n"
        )
        spike_blocks.append(block)

    if not spike_blocks:
        raise ValueError(f"Stream '{stream_name}' has no readable spikes")

    user_prompt = _build_prompt(stream_name, spike_blocks)
    result = await asyncio.to_thread(backend.complete_with_usage, _SYSTEM_PROMPT, [], user_prompt)

    content = result.text.strip() + "\n"
    now = datetime.now(UTC).isoformat()
    streams_module.write_summary(workspace, stream_name, content, now)
    detail = StreamSummaryLogDetail(
        stream_name=stream_name,
        spike_count=len(spike_blocks),
        cost_usd=result.cost_usd,
        total_tokens=result.total_tokens,
    )
    append_log(workspace, f"Generated summary for stream '{stream_name}' ({len(spike_blocks)} spike(s))", detail)
    return content


########################################################################################################################
# Implementation                                                                                                       #
########################################################################################################################


def _build_prompt(stream_name: str, spike_blocks: list[str]) -> str:
    spikes_text = "\n\n---\n\n".join(spike_blocks)
    return (
        f'Synthesize the following {len(spike_blocks)} spike(s) from the stream "{stream_name}" '
        f"into a comprehensive Markdown document.\n\n"
        f"=== SPIKES ===\n\n{spikes_text}\n\n"
        f"=== END SPIKES ===\n\n"
        f"Output the complete synthesis document now."
    )
