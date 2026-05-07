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

"""User registry for multi-user bearer-token authentication."""

import secrets
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################

TOKEN_PREFIX = "bd_"  # nosec B105 — this is a token prefix, not a password  # noqa: S105


def generate_token() -> str:
    """Generate a new opaque bearer token with the ``bd_`` prefix."""
    return TOKEN_PREFIX + secrets.token_hex(32)


class UserRecord(BaseModel):
    """A single user entry as stored in the registry."""

    username: str
    token: str
    created_at: str


class UserRegistry:
    """Manages the user registry stored in ``<workspace>/.users/users.json``.

    Args:
        path: Absolute path to the ``users.json`` file.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._by_token: dict[str, UserRecord] = {}

    def load(self) -> None:
        """Read the registry file and populate the in-memory lookup table."""
        data = _RegistryData.model_validate_json(self._path.read_text(encoding="utf-8"))
        self._by_token = {}
        for username, entry in data.root.items():
            self._by_token[entry.token] = UserRecord(
                username=username,
                token=entry.token,
                created_at=entry.created_at,
            )

    def lookup(self, token: str) -> UserRecord | None:
        """Return the ``UserRecord`` for *token*, or ``None`` if not found.

        Uses ``secrets.compare_digest`` for each comparison to prevent timing attacks.
        """
        for stored_token, record in self._by_token.items():
            if secrets.compare_digest(stored_token, token):
                return record
        return None

    def add_user(self, username: str) -> str:
        """Add a new user and return the generated token.

        Args:
            username: Unique username for the new user.

        Returns:
            The generated bearer token (shown exactly once — not recoverable later).

        Raises:
            ValueError: If a user with that username already exists.
        """
        existing_usernames = {r.username for r in self._by_token.values()}
        if username in existing_usernames:
            raise ValueError(f"User '{username}' already exists")
        token = generate_token()
        record = UserRecord(
            username=username,
            token=token,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._by_token[token] = record
        return token

    def list_users(self) -> list[UserRecord]:
        """Return all registered users."""
        return list(self._by_token.values())

    def update_token(self, username: str) -> str:
        """Replace the token for an existing user and return the new token.

        Args:
            username: Username whose token should be rotated.

        Returns:
            The newly generated bearer token (shown exactly once — not recoverable later).

        Raises:
            ValueError: If the user does not exist.
        """
        old_token = next((t for t, r in self._by_token.items() if r.username == username), None)
        if old_token is None:
            raise ValueError(f"User '{username}' not found")
        record = self._by_token.pop(old_token)
        new_token = generate_token()
        self._by_token[new_token] = UserRecord(
            username=record.username,
            token=new_token,
            created_at=record.created_at,
        )
        return new_token

    def remove_user(self, username: str) -> None:
        """Remove a user from the registry.

        Args:
            username: Username to remove.

        Raises:
            ValueError: If the user does not exist.
        """
        token = next((t for t, r in self._by_token.items() if r.username == username), None)
        if token is None:
            raise ValueError(f"User '{username}' not found")
        del self._by_token[token]

    def save(self) -> None:
        """Atomically write the current registry to disk (write to tmp, then rename)."""
        entries = {r.username: _UserEntry(token=r.token, created_at=r.created_at) for r in self._by_token.values()}
        data = _RegistryData(entries)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        tmp.rename(self._path)


########################################################################################################################
# Implementation                                                                                                       #
########################################################################################################################


class _UserEntry(BaseModel):
    """Compact per-user record stored inside ``users.json`` (username is the dict key)."""

    token: str
    created_at: str


class _RegistryData(BaseModel):
    """Root model for ``users.json`` — maps username to its entry."""

    root: dict[str, _UserEntry] = {}

    def __init__(self, root: dict[str, _UserEntry] | None = None) -> None:
        super().__init__(root=root or {})

    def model_dump_json(self, *, indent: int | None = None) -> str:  # type: ignore[override]
        """Serialize as the raw dict (not wrapped in ``{"root": ...}``)."""
        import json

        return json.dumps(
            {name: entry.model_dump() for name, entry in self.root.items()},
            indent=indent,
        )

    @classmethod
    def model_validate_json(cls, json_data: str, **_kwargs: object) -> "_RegistryData":  # type: ignore[override]
        """Parse from the raw dict format on disk."""
        import json

        raw = json.loads(json_data)
        entries = {name: _UserEntry.model_validate(entry) for name, entry in raw.items()}
        instance = cls.__new__(cls)
        super(_RegistryData, instance).__init__(root=entries)
        return instance
