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

"""Tests for the braindump CLI init command (git and git LFS setup)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from braindump.main import _init_git, _init_git_lfs

# ---------------------------------------------------------------------------
# _init_git_lfs
# ---------------------------------------------------------------------------


def test_init_git_lfs_tracks_jpg_and_png(tmp_path: Path) -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/git-lfs"),
        patch("subprocess.run") as mock_run,
    ):
        _init_git_lfs(tmp_path)

    assert mock_run.call_count == 5
    mock_run.assert_any_call(["git", "lfs", "install"], check=True, cwd=tmp_path)
    mock_run.assert_any_call(["git", "lfs", "track", "*.png"], check=True, cwd=tmp_path)
    mock_run.assert_any_call(["git", "lfs", "track", "*.jpg"], check=True, cwd=tmp_path)
    mock_run.assert_any_call(["git", "lfs", "track", "*.gif"], check=True, cwd=tmp_path)
    mock_run.assert_any_call(["git", "lfs", "track", "*.webp"], check=True, cwd=tmp_path)


def test_init_git_lfs_skips_when_git_lfs_missing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run") as mock_run,
    ):
        _init_git_lfs(tmp_path)

    mock_run.assert_not_called()
    assert "git-lfs not found" in caplog.text


# ---------------------------------------------------------------------------
# _init_git — git_lfs flag
# ---------------------------------------------------------------------------


def test_init_git_calls_lfs_by_default(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()  # simulate existing repo

    with (
        patch("shutil.which", return_value="/usr/bin/git"),
        patch("braindump.main._init_git_lfs") as mock_lfs,
    ):
        _init_git(tmp_path)

    mock_lfs.assert_called_once_with(tmp_path)


def test_init_git_skips_lfs_when_disabled(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    with (
        patch("shutil.which", return_value="/usr/bin/git"),
        patch("braindump.main._init_git_lfs") as mock_lfs,
    ):
        _init_git(tmp_path, git_lfs=False)

    mock_lfs.assert_not_called()
