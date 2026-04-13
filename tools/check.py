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

"""Quality gate — runs all static analysis and build tools, prints a summary table."""

from __future__ import annotations

import subprocess  # nosec B404
import time
from dataclasses import dataclass, field
from pathlib import Path

from tabulate import tabulate
from yachalk import chalk

########################################################################################################################
# Public Interface                                                                                                    #
########################################################################################################################

ROOT = Path(__file__).parent.parent
FRONTEND = ROOT / "frontend"


@dataclass
class Check:
    """A single quality check."""

    label: str
    cmd: list[str]
    cwd: Path = field(default_factory=lambda: ROOT)
    skip_if_missing: Path | None = None
    ok_exit_codes: frozenset[int] = field(default_factory=lambda: frozenset({0}))


@dataclass
class Result:
    """Outcome of running a Check."""

    check: Check
    passed: bool
    duration: float
    output: str
    skipped: bool = False


CHECKS: list[Check] = [
    Check("ruff format", ["uv", "run", "ruff", "format", "."]),
    Check("ruff check", ["uv", "run", "ruff", "check", "."]),
    Check("ty", ["uv", "run", "ty", "check", "."]),
    Check(
        "pytest",
        ["uv", "run", "pytest", "tests", "-q", "--tb=no"],
        skip_if_missing=ROOT / "tests",
        ok_exit_codes=frozenset({0, 5}),  # 5 = no tests collected
    ),
    Check("bandit", ["uv", "run", "bandit", "--configfile", "pyproject.toml", "-r", "-q", "."]),
    Check("tsc", ["npx", "tsc", "--noEmit"], cwd=FRONTEND),
    Check("eslint", ["npm", "run", "lint", "--silent"], cwd=FRONTEND),
    Check("vite build", ["npm", "run", "build", "--silent"], cwd=FRONTEND),
]


def run_checks(checks: list[Check]) -> list[Result]:
    """Run all checks and return their results."""
    results: list[Result] = []
    for check in checks:
        if check.skip_if_missing and not check.skip_if_missing.exists():
            print(chalk.dim(f"  skipping {check.label} (not found)"))
            results.append(Result(check=check, passed=True, duration=0.0, output="", skipped=True))
            continue

        print(chalk.dim(f"  Running: {check.label}"))
        start = time.monotonic()
        proc = subprocess.run(  # nosec B603  # noqa: S603
            check.cmd,
            cwd=check.cwd,
            capture_output=True,
            text=True,
        )
        duration = time.monotonic() - start
        output = (proc.stdout + proc.stderr).strip()
        passed = proc.returncode in check.ok_exit_codes
        results.append(Result(check=check, passed=passed, duration=duration, output=output))
    return results


def print_summary(results: list[Result]) -> None:
    """Print a coloured tabulate summary table."""
    rows = []
    for r in results:
        if r.skipped:
            status = chalk.yellow("- skip")
        elif r.passed:
            status = chalk.green("✔ pass")
        else:
            status = chalk.red("✘ fail")
        label = chalk.bold(r.check.label)
        duration = chalk.dim(f"{r.duration:.1f}s")
        rows.append([label, status, duration])

    print()
    headers = [chalk.bold("check"), chalk.bold("status"), chalk.bold("time")]
    print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))

    failed = [r for r in results if not r.passed and not r.skipped]
    if failed:
        print()
        for r in failed:
            print(chalk.red.bold(f"── {r.check.label} output ──"))
            print(chalk.dim(r.output or "(no output)"))
            print()
        print(chalk.red.bold(f"  {len(failed)}/{len(results)} checks failed"))
    else:
        print(chalk.green.bold(f"  all {len(results)} checks passed"))

    print()


########################################################################################################################
# Implementation                                                                                                    #
########################################################################################################################


def _main() -> None:
    print()
    print(chalk.bold("braindump quality gate"))
    print(chalk.dim(f"  Workspace: {ROOT}"))
    print(chalk.dim(f"  Frontend: `{FRONTEND}`"))
    print()

    results = run_checks(CHECKS)
    print_summary(results)

    if any(not r.passed and not r.skipped for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    _main()
