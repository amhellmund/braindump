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

"""Chat session persistence — read/write JSON files in ``workspace/chats/``."""

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from braindump import dirs
from braindump.types import (
    ChatSession,
    ChatSessionResponse,
    ChatSessionSummary,
    QuerySource,
    StoredChatTurn,
)

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################

_logger = logging.getLogger(__name__)

_MAX_TITLE_LEN = 60
_MAX_LIST_COUNT = 20


def create_session(workspace: Path, first_query: str) -> ChatSession:
    """Create a new empty chat session and persist it to disk.

    Args:
        workspace: Root workspace directory.
        first_query: The first user query — used as the session title (truncated to 60 chars).

    Returns:
        The newly created ChatSession.
    """
    now = datetime.now(UTC).isoformat()
    session = ChatSession(
        id=str(uuid.uuid4()),
        title=first_query[:_MAX_TITLE_LEN],
        created_at=now,
        updated_at=now,
        turns=[],
    )
    _write_session(workspace, session)
    return session


def append_turn(
    workspace: Path,
    session_id: str,
    query: str,
    answer: str,
    citations: list[QuerySource],
) -> None:
    """Append a query-answer turn to an existing session and persist it.

    Args:
        workspace: Root workspace directory.
        session_id: ID of the session to update.
        query: The user's question.
        answer: The assistant's answer.
        citations: Sources cited in the answer.

    Raises:
        FileNotFoundError: If the session does not exist.
    """
    session = _read_session(workspace, session_id)
    session.turns.append(
        StoredChatTurn(
            query=query,
            answer=answer,
            citations=citations,
            timestamp=datetime.now(UTC).isoformat(),
        )
    )
    session.updated_at = datetime.now(UTC).isoformat()
    _write_session(workspace, session)


def session_exists(workspace: Path, session_id: str) -> bool:
    """Return True if a session file exists for the given ID."""
    return dirs.chat_session_path(workspace, session_id).exists()


def list_sessions(workspace: Path) -> list[ChatSessionSummary]:
    """Return up to 20 session summaries sorted by last-updated descending.

    Corrupt or unreadable session files are silently skipped.
    """
    sessions: list[ChatSession] = []
    for path in dirs.chats_dir(workspace).glob("*.json"):
        try:
            sessions.append(ChatSession.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:
            _logger.warning("Skipping unreadable chat session file: %s", path, exc_info=True)
            continue
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return [
        ChatSessionSummary(
            id=s.id,
            title=s.title,
            createdAt=s.created_at,
            updatedAt=s.updated_at,
            turnCount=len(s.turns),
        )
        for s in sessions[:_MAX_LIST_COUNT]
    ]


def get_session(workspace: Path, session_id: str) -> ChatSessionResponse:
    """Return the full session with all stored turns.

    Raises:
        FileNotFoundError: If the session does not exist.
    """
    session = _read_session(workspace, session_id)
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        createdAt=session.created_at,
        updatedAt=session.updated_at,
        turns=session.turns,
    )


########################################################################################################################
# Private Helpers                                                                                                      #
########################################################################################################################


def _write_session(workspace: Path, session: ChatSession) -> None:
    path = dirs.chat_session_path(workspace, session.id)
    path.write_text(session.model_dump_json(), encoding="utf-8")


def _read_session(workspace: Path, session_id: str) -> ChatSession:
    path = dirs.chat_session_path(workspace, session_id)
    if not path.exists():
        raise FileNotFoundError(f"Chat session not found: {session_id}")
    return ChatSession.model_validate_json(path.read_text(encoding="utf-8"))
