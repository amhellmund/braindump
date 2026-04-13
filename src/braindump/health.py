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

"""Periodic health checks and consistency validation for the wiki layer.

The health check compares the spikes on disk against what the wiki layer knows
about, flagging any discrepancies: spikes without index entries, stale entries
for deleted files, broken links in connections.md, and unclustered spikes in
hierarchy.md.

When inconsistencies are found the LLM is used to repair them.  The repair
loop retries until the wiki is clean or a maximum number of iterations is
reached.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from braindump import dirs, storage, txlog, wiki
from braindump.llm import ChatBackend
from braindump.types import HealthCheckLogDetail, HealthRepairLogDetail, HealthReport

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################


def run_health_check(workspace: Path) -> HealthReport:
    """Check consistency between spikes on disk and the wiki layer.

    Compares spike files found on disk with entries in ``wiki/meta.json``,
    validates references inside ``wiki/connections.md`` and
    ``wiki/hierarchy.md``, and inspects ``wiki/txlog.jsonl`` for
    transactions that began but were never committed.

    Args:
        workspace: Root workspace directory.

    Returns:
        :class:`~braindump.models.HealthReport` describing any issues found.
    """
    meta = wiki.read_meta(workspace)
    known_ids = set(meta)
    disk_ids = set(storage.list_spike_ids(workspace))

    # Spikes on disk without a meta.json / index.md entry
    missing_index_entries = sorted(disk_ids - known_ids)

    # Entries in meta.json whose file no longer exists on disk
    stale_index_entries = sorted(known_ids - disk_ids)

    # References to non-existent spike IDs in connections.md
    broken_links: list[str] = []
    conn_path = dirs.connections_path(workspace)
    if conn_path.exists():
        for line in conn_path.read_text(encoding="utf-8").splitlines():
            m = wiki.CONNECTION_RE.match(line.strip())
            if m:
                for uid in (m.group(1), m.group(2)):
                    if uid not in disk_ids and uid not in broken_links:
                        broken_links.append(uid)

    # Spikes in hierarchy.md that no longer exist on disk
    communities = wiki.parse_hierarchy(dirs.hierarchy_path(workspace))
    orphaned_wiki_pages = sorted(sid for sid in communities if sid not in disk_ids)

    incomplete = txlog.find_incomplete_transactions(workspace)
    incomplete_transactions = sorted({tx.spike_id for tx in incomplete})

    issues = [
        *[f"Spike {sid} exists on disk but has no wiki index entry" for sid in missing_index_entries],
        *[f"Wiki index entry {sid} has no corresponding spike file" for sid in stale_index_entries],
        *[f"Broken reference to {sid} in connections.md" for sid in broken_links],
        *[f"Spike {sid} appears in hierarchy.md but no longer exists on disk" for sid in orphaned_wiki_pages],
        *[f"Spike {sid} has an incomplete wiki transaction in the transaction log" for sid in incomplete_transactions],
    ]

    report = HealthReport(
        checked_at=datetime.now(UTC).isoformat(),
        missing_index_entries=missing_index_entries,
        stale_index_entries=stale_index_entries,
        broken_links=broken_links,
        orphaned_wiki_pages=orphaned_wiki_pages,
        incomplete_transactions=incomplete_transactions,
        issues=issues,
    )

    wiki.append_log(
        workspace,
        f"Health check completed: {len(issues)} issue(s) found",
        HealthCheckLogDetail(issues=issues),
    )
    return report


async def repair_inconsistencies(workspace: Path, report: HealthReport, backend: ChatBackend) -> wiki.WikiUsage:
    """Use the LLM to fix every inconsistency described in *report*.

    The LLM is the authoritative writer for all wiki files.  Each category of
    issue is addressed separately:

    - **missing_index_entries** — spikes on disk with no wiki entry are
      fully indexed via :func:`~braindump.wiki.update_wiki_for_spike`.
    - **stale_index_entries** — wiki entries whose spike file is gone are
      purged via :func:`~braindump.wiki.remove_spike_from_wiki`.
    - **broken_links** — connection lines in ``connections.md`` that
      reference non-existent IDs are removed by the LLM.
    - **orphaned_wiki_pages** — entries in ``hierarchy.md`` for non-existent
      spikes are removed by the LLM.
    - **incomplete_transactions** — transactions that were interrupted are
      retried (update or remove, depending on the recorded operation type),
      unless the affected spike was already handled by one of the categories
      above.

    Args:
        workspace: Root workspace directory.
        report: Health report produced by :func:`run_health_check`.
        backend: Active LLM backend used to rewrite wiki files.

    Returns:
        :class:`~braindump.wiki.WikiUsage` with accumulated LLM cost and
        token counts across all repair operations.
    """
    total_cost = 0.0
    total_tokens = 0
    schema = dirs.schema_path(workspace).read_text(encoding="utf-8")

    already_handled: set[str] = set()
    errors: list[str] = []

    # 1. Spikes on disk without wiki entries → index them
    for spike_id in report.missing_index_entries:
        try:
            raw = storage.read_spike_raw(workspace, spike_id)
            spike = storage.parse_spike(raw, spike_id)
            usage = await wiki.update_wiki_for_spike(workspace, spike, backend)
            total_cost += usage.cost_usd
            total_tokens += usage.total_tokens
            already_handled.add(spike_id)
        except Exception as exc:
            errors.append(f"Repair failed for missing entry {spike_id}: {exc}")

    # 2. Wiki entries with no spike file → remove them
    for spike_id in report.stale_index_entries:
        try:
            usage = await wiki.remove_spike_from_wiki(workspace, spike_id, backend)
            total_cost += usage.cost_usd
            total_tokens += usage.total_tokens
            already_handled.add(spike_id)
        except Exception as exc:
            errors.append(f"Repair failed for stale entry {spike_id}: {exc}")

    # 3. Broken references in connections.md → ask LLM to remove those lines
    if report.broken_links:
        try:
            ids_str = ", ".join(f"`{sid}`" for sid in report.broken_links)
            current = dirs.connections_path(workspace).read_text(encoding="utf-8")
            prompt = (
                f"Remove all connection lines that reference any of these non-existent spike IDs: {ids_str}.\n\n"
                f"Current connections.md:\n{current}\n\n"
                "Output only the complete updated connections.md."
            )
            result = await asyncio.to_thread(backend.complete_with_usage, schema, [], prompt)
            dirs.connections_path(workspace).write_text(result.text.strip() + "\n", encoding="utf-8")
            total_cost += result.cost_usd
            total_tokens += result.total_tokens
        except Exception as exc:
            errors.append(f"Repair failed for broken links: {exc}")

    # 4. Orphaned entries in hierarchy.md → ask LLM to remove them
    if report.orphaned_wiki_pages:
        try:
            ids_str = ", ".join(f"`{sid}`" for sid in report.orphaned_wiki_pages)
            current = dirs.hierarchy_path(workspace).read_text(encoding="utf-8")
            prompt = (
                f"Remove the entries for these non-existent spike IDs from hierarchy.md: {ids_str}. "
                "If removing an entry leaves a community empty, remove that community section too.\n\n"
                f"Current hierarchy.md:\n{current}\n\n"
                "Output only the complete updated hierarchy.md."
            )
            result = await asyncio.to_thread(backend.complete_with_usage, schema, [], prompt)
            dirs.hierarchy_path(workspace).write_text(result.text.strip() + "\n", encoding="utf-8")
            total_cost += result.cost_usd
            total_tokens += result.total_tokens
        except Exception as exc:
            errors.append(f"Repair failed for orphaned wiki pages: {exc}")

    # 5. Incomplete transactions → retry the recorded operation
    for tx in txlog.find_incomplete_transactions(workspace):
        spike_id = tx.spike_id
        if spike_id is None or spike_id in already_handled:
            continue
        op = tx.op
        try:
            if op == txlog.TxOp.UPDATE_SPIKE:
                raw = storage.read_spike_raw(workspace, spike_id)
                spike = storage.parse_spike(raw, spike_id)
                usage = await wiki.update_wiki_for_spike(workspace, spike, backend)
            elif op == txlog.TxOp.REMOVE_SPIKE:
                usage = await wiki.remove_spike_from_wiki(workspace, spike_id, backend)
            else:
                continue
            total_cost += usage.cost_usd
            total_tokens += usage.total_tokens
            already_handled.add(spike_id)
        except Exception as exc:
            errors.append(f"Repair failed for incomplete transaction {spike_id} ({op}): {exc}")

    wiki.append_log(
        workspace,
        f"Health repair completed: {len(already_handled)} spike(s) repaired",
        HealthRepairLogDetail(repaired_count=len(already_handled), errors=errors),
    )
    return wiki.WikiUsage(cost_usd=total_cost, total_tokens=total_tokens)
