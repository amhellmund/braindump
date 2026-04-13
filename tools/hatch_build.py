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

"""Hatchling build hook — compiles the React frontend before wheel assembly.

The built assets land in ``frontend/dist/``.  Hatchling's ``force-include``
then maps that directory into ``braindump/frontend/dist/`` inside the wheel.
"""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface  # type: ignore[import-unresolved]


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        frontend = Path(self.root) / "frontend"

        print("Building frontend…", flush=True)
        subprocess.run(["npm", "ci"], cwd=frontend, check=True, stdout=sys.stdout, stderr=sys.stderr)  # noqa: S607  # nosec B603, B607
        subprocess.run(["npm", "run", "build"], cwd=frontend, check=True, stdout=sys.stdout, stderr=sys.stderr)  # noqa: S607  # nosec B603, B607
        print("Frontend built.", flush=True)
