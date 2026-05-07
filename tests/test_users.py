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

"""Tests for the user registry module."""

from pathlib import Path

import pytest

from braindump.users import TOKEN_PREFIX, UserRegistry, generate_token


def test_generate_token_has_prefix_and_length() -> None:
    token = generate_token()
    assert token.startswith(TOKEN_PREFIX)
    assert len(token) == len(TOKEN_PREFIX) + 64


def test_generate_token_is_unique() -> None:
    assert generate_token() != generate_token()


def test_registry_add_and_lookup(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    token = registry.add_user("alice")
    record = registry.lookup(token)
    assert record is not None
    assert record.username == "alice"
    assert record.token == token


def test_registry_lookup_unknown_token(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    registry.add_user("alice")
    assert registry.lookup("bd_" + "x" * 64) is None


def test_registry_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    registry = UserRegistry(path)
    token = registry.add_user("alice")
    registry.save()

    registry2 = UserRegistry(path)
    registry2.load()
    record = registry2.lookup(token)
    assert record is not None
    assert record.username == "alice"


def test_registry_duplicate_username_raises(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    registry.add_user("alice")
    with pytest.raises(ValueError, match="already exists"):
        registry.add_user("alice")


def test_registry_remove_user(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    token = registry.add_user("alice")
    registry.remove_user("alice")
    assert registry.lookup(token) is None


def test_registry_remove_unknown_user_raises(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    with pytest.raises(ValueError, match="not found"):
        registry.remove_user("nobody")


def test_registry_list_users(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    registry.add_user("alice")
    registry.add_user("bob")
    usernames = {r.username for r in registry.list_users()}
    assert usernames == {"alice", "bob"}


def test_registry_save_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "users.json"
    registry = UserRegistry(path)
    registry.add_user("alice")
    registry.save()
    assert path.exists()


def test_registry_update_token_returns_new_token(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    old_token = registry.add_user("alice")
    new_token = registry.update_token("alice")
    assert new_token != old_token
    assert new_token.startswith(TOKEN_PREFIX)


def test_registry_update_token_old_token_invalid(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    old_token = registry.add_user("alice")
    registry.update_token("alice")
    assert registry.lookup(old_token) is None


def test_registry_update_token_new_token_valid(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    registry.add_user("alice")
    new_token = registry.update_token("alice")
    record = registry.lookup(new_token)
    assert record is not None
    assert record.username == "alice"


def test_registry_update_token_preserves_created_at(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    registry.add_user("alice")
    before = registry.lookup(next(t for t, r in registry._by_token.items() if r.username == "alice"))
    assert before is not None
    new_token = registry.update_token("alice")
    after = registry.lookup(new_token)
    assert after is not None
    assert after.created_at == before.created_at


def test_registry_update_token_unknown_user_raises(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    with pytest.raises(ValueError, match="not found"):
        registry.update_token("nobody")
