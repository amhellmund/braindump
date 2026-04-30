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

"""LLM-driven daily summarization."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from braindump import dailies as dailies_module
from braindump import storage
from braindump.dirs import index_path
from braindump.llm import ChatBackend
from braindump.types import DailySummaryLogDetail
from braindump.wiki import _extract_index_section, append_log, list_all_meta

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################

_SYSTEM_PROMPT = """\
You are a knowledge synthesizer for braindump, a personal knowledge base of Markdown notes called "spikes".
Produce a short, scannable Markdown recap of what was explored on a given date — a quick reminder, not an exhaustive
report.

Rules:
1. Output ONLY the Markdown document — no preamble, no wrapping code fences.
2. Use exactly these two top-level sections in order:
   ## What was done
   ## Key takeaways
3. In "What was done", one bullet per spike: spike title followed by a single sentence describing what it covers.
4. In "Key takeaways", at most 3 bullets capturing the most important insights or patterns across all spikes.
5. Total length must not exceed 200 words.
"""


async def generate_daily_summary(workspace: Path, date: str, backend: ChatBackend) -> str:
    """Generate a markdown summary for all spikes created on a given date.

    Reads spike content and wiki index summaries, calls the LLM, writes the result
    to ``dailies/summaries/{date}.md``, and updates ``summary_at`` in dailies.json.

    Args:
        workspace: Root workspace directory.
        date: ISO date string (YYYY-MM-DD) identifying the day to summarize.
        backend: Active LLM backend.

    Returns:
        Generated summary markdown content.

    Raises:
        ValueError: If the date has no spikes.
        RuntimeError: If the LLM call fails.
    """
    all_meta = list_all_meta(workspace)
    spike_ids = [m.id for m in all_meta if _spike_date(m.created_at) == date]
    if not spike_ids:
        raise ValueError(f"No spikes found for date '{date}'")

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
        raise ValueError(f"No readable spikes found for date '{date}'")

    user_prompt = _build_prompt(date, spike_blocks)
    result = await asyncio.to_thread(backend.complete_with_usage, _SYSTEM_PROMPT, [], user_prompt)

    content = result.text.strip() + "\n"
    now = datetime.now(UTC).isoformat()
    dailies_module.write_daily_summary(workspace, date, content, now)
    detail = DailySummaryLogDetail(
        date=date,
        spike_count=len(spike_blocks),
        cost_usd=result.cost_usd,
        total_tokens=result.total_tokens,
    )
    append_log(workspace, f"Generated summary for daily '{date}' ({len(spike_blocks)} spike(s))", detail)
    return content


########################################################################################################################
# Implementation                                                                                                       #
########################################################################################################################


def _spike_date(created_at: str) -> str:
    """Extract the UTC date portion (YYYY-MM-DD) from an ISO-8601 timestamp."""
    try:
        return datetime.fromisoformat(created_at).date().isoformat()
    except (ValueError, AttributeError):
        return ""


def _build_prompt(date: str, spike_blocks: list[str]) -> str:
    spikes_text = "\n\n---\n\n".join(spike_blocks)
    return (
        f"Summarize the following {len(spike_blocks)} spike(s) created on {date} "
        f"into a brief daily recap.\n\n"
        f"=== SPIKES ===\n\n{spikes_text}\n\n"
        f"=== END SPIKES ===\n\n"
        f"Output the short recap now."
    )
