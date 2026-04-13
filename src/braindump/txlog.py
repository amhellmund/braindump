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

"""Transaction log for wiki update operations.

Records ``begin`` / ``step`` / ``commit`` events for every wiki operation so
that incomplete transactions (e.g. from an abrupt process kill or crash) can be
detected on the next startup.

The log is stored as an append-only JSONL file at
``<workspace>/wiki/txlog.jsonl``.  Each line is a JSON object:

    {"txid": "<uuid>", "op": "update_spike|remove_spike",
     "spike_id": "<uuid>", "event": "begin", "ts": "<ISO-8601>"}
    {"txid": "<uuid>", "event": "step_index",       "ts": "..."}
    {"txid": "<uuid>", "event": "step_connections", "ts": "..."}
    {"txid": "<uuid>", "event": "step_hierarchy",   "ts": "..."}
    {"txid": "<uuid>", "event": "commit",            "ts": "..."}

A transaction is *incomplete* when its ``txid`` has a ``begin`` entry but no
corresponding ``commit`` entry.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ValidationError

from braindump.dirs import txlog_path

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################


class TxOp(StrEnum):
    """Operation type recorded at the start of a transaction."""

    UPDATE_SPIKE = "update_spike"
    REMOVE_SPIKE = "remove_spike"


class TxEvent(StrEnum):
    """Event type for a single transaction log entry."""

    BEGIN = "begin"
    STEP_INDEX = "step_index"
    STEP_CONNECTIONS = "step_connections"
    STEP_HIERARCHY = "step_hierarchy"
    COMMIT = "commit"


class TxEntry(BaseModel):
    """A single entry in the transaction log JSONL file."""

    txid: str
    event: TxEvent
    ts: str
    op: TxOp | None = None
    spike_id: str | None = None


def begin_transaction(workspace: Path, op: TxOp, spike_id: str) -> str:
    """Record the start of a wiki operation.

    Args:
        workspace: Root workspace directory.
        op: Operation type.
        spike_id: UUID of the spike being operated on.

    Returns:
        A new transaction ID (UUID string) that must be passed to subsequent
        :func:`record_step` and :func:`commit_transaction` calls.
    """
    txid = str(uuid.uuid4())
    _append(workspace, TxEntry(txid=txid, op=op, spike_id=spike_id, event=TxEvent.BEGIN, ts=_now()))
    return txid


def record_step(workspace: Path, txid: str, step: TxEvent) -> None:
    """Record successful completion of one step within a transaction.

    Args:
        workspace: Root workspace directory.
        txid: Transaction ID returned by :func:`begin_transaction`.
        step: Step event — one of :attr:`TxEvent.STEP_INDEX`, :attr:`TxEvent.STEP_CONNECTIONS`,
            :attr:`TxEvent.STEP_HIERARCHY`.
    """
    _append(workspace, TxEntry(txid=txid, event=step, ts=_now()))


def commit_transaction(workspace: Path, txid: str) -> None:
    """Record successful completion of a transaction.

    Args:
        workspace: Root workspace directory.
        txid: Transaction ID returned by :func:`begin_transaction`.
    """
    _append(workspace, TxEntry(txid=txid, event=TxEvent.COMMIT, ts=_now()))


def compact_transaction_log(workspace: Path, keep_complete: int = 100) -> None:
    """Rewrite the transaction log, retaining only incomplete transactions and the
    most recent *keep_complete* committed transactions.

    Call periodically (e.g. after each health-check cycle) to prevent the log
    from growing without bound.

    Args:
        workspace: Root workspace directory.
        keep_complete: Maximum number of committed transaction groups to retain.
    """
    path = txlog_path(workspace)
    if not path.exists():
        return

    entries: list[TxEntry] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entries.append(TxEntry.model_validate_json(line))
        except ValidationError:
            continue

    # Group entries by txid (preserving insertion order)
    by_txid: dict[str, list[TxEntry]] = {}
    for entry in entries:
        if entry.txid:
            by_txid.setdefault(entry.txid, []).append(entry)

    committed: list[str] = [
        txid for txid, txentries in by_txid.items() if any(e.event == TxEvent.COMMIT for e in txentries)
    ]
    incomplete: set[str] = {txid for txid in by_txid if txid not in set(committed)}

    # Keep all incomplete + the tail of committed (newest last)
    keep: set[str] = incomplete | set(committed[-keep_complete:])
    kept = [e for e in entries if e.txid in keep]
    path.write_text("".join(e.model_dump_json(exclude_none=True) + "\n" for e in kept), encoding="utf-8")


def find_incomplete_transactions(workspace: Path) -> list[TxEntry]:
    """Return all transactions that began but were never committed.

    Reads ``wiki/txlog.jsonl`` from top to bottom, collecting every
    ``begin`` entry and removing those that were later committed.  Any
    remaining entries represent operations that did not finish.

    Args:
        workspace: Root workspace directory.

    Returns:
        List of ``begin``-event :class:`TxEntry` objects for each incomplete
        transaction, in the order they were started.
    """
    path = txlog_path(workspace)
    if not path.exists():
        return []

    begun: dict[str, TxEntry] = {}
    committed: set[str] = set()

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = TxEntry.model_validate_json(line)
        except ValidationError:
            continue
        if not entry.txid:
            continue
        if entry.event == TxEvent.BEGIN:
            begun[entry.txid] = entry
        elif entry.event == TxEvent.COMMIT:
            committed.add(entry.txid)

    return [tx for txid, tx in begun.items() if txid not in committed]


########################################################################################################################
# Implementation                                                                                                       #
########################################################################################################################


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _append(workspace: Path, entry: TxEntry) -> None:
    path = txlog_path(workspace)
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(entry.model_dump_json(exclude_none=True) + "\n")
