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

"""Daily management — init, read/write dailies.json and summary files."""

from pathlib import Path

from braindump.dirs import dailies_path, daily_summaries_dir, daily_summary_path
from braindump.types import DailiesData, DailyMeta

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################


def init_dailies(workspace: Path) -> None:
    """Create the dailies directory and seed dailies.json if it does not yet exist.

    Args:
        workspace: Root workspace directory.
    """
    p = dailies_path(workspace)
    if not p.exists():
        p.write_text(DailiesData().model_dump_json(indent=2), encoding="utf-8")
    daily_summaries_dir(workspace)


def read_dailies(workspace: Path) -> DailiesData:
    """Read dailies/dailies.json, returning empty DailiesData when the file is missing.

    Args:
        workspace: Root workspace directory.
    """
    path = dailies_path(workspace)
    if not path.exists():
        return DailiesData()
    return DailiesData.model_validate_json(path.read_text(encoding="utf-8"))


def write_dailies(workspace: Path, data: DailiesData) -> None:
    """Persist DailiesData to dailies/dailies.json.

    Args:
        workspace: Root workspace directory.
        data: The dailies data to persist.
    """
    dailies_path(workspace).write_text(data.model_dump_json(indent=2), encoding="utf-8")


def read_daily_summary(workspace: Path, date: str) -> str | None:
    """Read the stored summary markdown for a given date, or None if absent.

    Args:
        workspace: Root workspace directory.
        date: ISO date string (YYYY-MM-DD).
    """
    path = daily_summary_path(workspace, date)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_daily_summary(workspace: Path, date: str, content: str, generated_at: str) -> None:
    """Write a summary for a given date and update summary_at in dailies.json.

    Args:
        workspace: Root workspace directory.
        date: ISO date string (YYYY-MM-DD).
        content: Markdown summary content.
        generated_at: ISO timestamp of generation.
    """
    daily_summary_path(workspace, date).write_text(content, encoding="utf-8")
    data = read_dailies(workspace)
    data.dailies[date] = DailyMeta(summary_at=generated_at)
    write_dailies(workspace, data)
