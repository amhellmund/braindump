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

"""braindump CLI — ``init`` and ``run`` subcommands."""

import argparse
import logging
import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from braindump import dirs, migrations, wiki
from braindump.llm import LLM_CONFIG_FILENAME, ClaudeBackend
from braindump.storage import ALLOWED_IMAGE_TYPES
from braindump.types import LLMConfig
from braindump.users import UserRegistry

_logger = logging.getLogger(__name__)

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################


def _valid_port(value: str) -> int:
    """Argparse type converter that validates a TCP port number."""
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid port: {value!r}") from None
    if not (1 <= port <= 65535):
        raise argparse.ArgumentTypeError(f"Port must be 1-65535, got {port}")
    return port


def run() -> None:
    """Entry point for the ``braindump`` console script."""
    parser = argparse.ArgumentParser(
        prog="braindump",
        description="Local-first, AI-powered knowledge base.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # ------------------------------------------------------------------
    # init
    # ------------------------------------------------------------------
    init_p = sub.add_parser(
        "init",
        help="Initialise a workspace and configure the LLM backend.",
        description=(
            "Set up the workspace directory, write the wiki schema, and configure "
            "the LLM backend.  No model downloads are required."
        ),
    )
    init_p.add_argument("workspace", type=Path, help="Workspace directory to initialise.")
    init_p.add_argument(
        "--env-file",
        metavar="PATH",
        type=Path,
        help="Path to a .env file loaded at server startup (optional).",
    )
    init_p.add_argument(
        "--git",
        action="store_true",
        default=False,
        help="Initialise a git repository in the workspace.",
    )
    init_p.add_argument(
        "--no-git-lfs",
        action="store_true",
        default=False,
        help="Disable git LFS tracking for image files (only relevant with --git).",
    )
    init_p.set_defaults(func=_cmd_init)

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------
    run_p = sub.add_parser(
        "run",
        help="Start the braindump server.",
        description="Start the FastAPI server for the given workspace.",
    )
    run_p.add_argument(
        "workspace",
        type=Path,
        help="Workspace directory (must have been initialised with `braindump init`).",
    )
    run_p.add_argument("--port", type=_valid_port, default=8000, help="TCP port to listen on (default: 8000).")
    run_p.set_defaults(func=_cmd_run)

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------
    update_p = sub.add_parser(
        "update",
        help="Migrate a workspace to the current schema version.",
        description="Apply any pending schema migrations to the given workspace.",
    )
    update_p.add_argument(
        "workspace",
        type=Path,
        help="Workspace directory to migrate.",
    )
    update_p.set_defaults(func=_cmd_update)

    # ------------------------------------------------------------------
    # user
    # ------------------------------------------------------------------
    user_p = sub.add_parser(
        "user",
        help="Manage users for multi-user mode.",
        description="Manage the user registry stored in <workspace>/.users/users.json.",
    )
    user_sub = user_p.add_subparsers(dest="user_command", metavar="<subcommand>")
    user_sub.required = True

    user_add_p = user_sub.add_parser(
        "add",
        help="Add a new user and print their access token.",
        description=(
            "Create a new user in the workspace's user registry and print the generated token. "
            "The token is shown exactly once and cannot be retrieved later."
        ),
    )
    user_add_p.add_argument("username", type=str, help="Username for the new user.")
    user_add_p.add_argument("workspace", type=Path, help="Workspace directory.")
    user_add_p.set_defaults(func=_cmd_user_add)

    user_update_token_p = user_sub.add_parser(
        "update-token",
        help="Rotate the access token for an existing user.",
        description=(
            "Generate a new access token for the given user and invalidate the old one. "
            "The new token is shown exactly once and cannot be retrieved later."
        ),
    )
    user_update_token_p.add_argument("username", type=str, help="Username whose token should be rotated.")
    user_update_token_p.add_argument("workspace", type=Path, help="Workspace directory.")
    user_update_token_p.set_defaults(func=_cmd_user_update_token)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    run()


########################################################################################################################
# Implementation                                                                                                       #
########################################################################################################################


def _cmd_init(args: argparse.Namespace) -> None:
    """Initialise the workspace: create wiki layer, configure LLM backend."""
    workspace: Path = args.workspace.resolve()
    braindump_data_dir = dirs.config_dir(workspace)
    braindump_data_dir.mkdir(parents=True, exist_ok=True)

    wiki.init_wiki(workspace)
    wiki.init_versions(workspace)
    _logger.info("Braindump layer initialised at %s", dirs.wiki_dir(workspace))

    env_file: Path | None = args.env_file.resolve() if args.env_file else None
    _configure_llm(braindump_data_dir, env_file)

    if args.git:
        _init_git(workspace, git_lfs=not args.no_git_lfs)

    _logger.info("\nRun `braindump run %s` to start the server.", workspace)


def _configure_llm(braindump_data_dir: Path, env_file: Path | None) -> None:
    """Interactive wizard that writes llm.json to the workspace."""

    _logger.info("\n── LLM backend setup ──────────────────────────────────────────")

    if env_file is not None:
        if not env_file.exists():
            _logger.warning("Warning: .env file not found at %s — continuing without it.", env_file)
            env_file = None
        else:
            _load_env_file(env_file)
            _logger.info("Loaded environment from %s", env_file)

    default_model = "claude-sonnet-4-6"
    model = input(f"Model [{default_model}]: ").strip() or default_model

    default_interval = 60
    interval_raw = input(f"Health check interval in minutes [{default_interval}]: ").strip()
    interval = int(interval_raw) if interval_raw.isdigit() else default_interval

    llm_config = LLMConfig(
        model=model,
        health_check_interval_minutes=interval,
        env_file=str(env_file) if env_file is not None else None,
    )
    llm_config_path = braindump_data_dir / LLM_CONFIG_FILENAME
    llm_config_path.write_text(llm_config.model_dump_json(indent=2), encoding="utf-8")
    _logger.info("LLM configured: claude / %s, health check every %d minute(s)", model, interval)
    _logger.info("\nThe Claude Agent SDK requires a working Claude Code installation.")
    _logger.info("Make sure Claude Code is authenticated before starting the server.")


def _load_env_file(env_file: Path) -> None:
    """Load variables from a .env file into the current process environment."""
    load_dotenv(dotenv_path=env_file, override=False)


def _init_git(workspace: Path, *, git_lfs: bool = True) -> None:
    """Initialise a git repo in the workspace.

    Args:
        workspace: The workspace directory to initialise as a git repository.
        git_lfs: When ``True`` (the default), configure git LFS tracking for
            all common image types.  Pass ``False`` to skip LFS setup.
    """
    if not shutil.which("git"):
        _logger.warning("Warning: git not found on PATH — skipping git initialisation.")
        return

    git_dir = workspace / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init", str(workspace)], check=True)  # noqa: S603, S607  # nosec B603, B607
        _logger.info("Initialised git repository in %s", workspace)

    if git_lfs:
        _init_git_lfs(workspace)


_LFS_IMAGE_PATTERNS = tuple(f"*{ext}" for ext in ALLOWED_IMAGE_TYPES.values())


def _init_git_lfs(workspace: Path) -> None:
    """Configure git LFS tracking for all common image file types.

    Args:
        workspace: The workspace directory that contains an initialised git repository.
    """
    if not shutil.which("git-lfs"):
        _logger.warning(
            "Warning: git-lfs not found on PATH — skipping LFS setup. "
            "Install git-lfs or pass --no-git-lfs to suppress this warning."
        )
        return

    subprocess.run(["git", "lfs", "install"], check=True, cwd=workspace)  # noqa: S607  # nosec B603, B607
    for pattern in _LFS_IMAGE_PATTERNS:
        subprocess.run(["git", "lfs", "track", pattern], check=True, cwd=workspace)  # noqa: S603, S607  # nosec B603, B607
    _logger.info("Configured git LFS tracking for %s", ", ".join(_LFS_IMAGE_PATTERNS))


def _cmd_run(args: argparse.Namespace) -> None:
    """Load .env (if configured) and start the uvicorn server."""
    workspace: Path = args.workspace.resolve()

    workspace.mkdir(parents=True, exist_ok=True)
    os.environ["BRAINDUMP_WORKSPACE"] = str(workspace)

    messages = migrations.check_migration_needed(workspace)
    if messages:
        for msg in messages:
            _logger.error("Error: %s", msg)
        sys.exit(1)

    llm_config_path = dirs.config_dir(workspace) / LLM_CONFIG_FILENAME
    if llm_config_path.exists():
        llm_config = LLMConfig.model_validate_json(llm_config_path.read_text(encoding="utf-8"))
        if llm_config.env_file:
            env_file = Path(llm_config.env_file)
            if env_file.exists():
                _load_env_file(env_file)
            else:
                _logger.warning("Warning: .env file %s no longer exists — skipping.", env_file)
        if llm_config.model:
            _logger.info("Testing LLM connection…")
            backend = ClaudeBackend(model=llm_config.model)
            if backend.ping():
                _logger.info("Connection test passed (pong received).")
            else:
                _logger.warning(
                    "Warning: connection test failed — the server will start but queries may not work.\n"
                    "Ensure Claude Code is authenticated and the CLI is reachable."
                )
    else:
        _logger.warning("Warning: %s not found. Run `braindump init <workspace>` first.", llm_config_path)

    dev = os.getenv("BRAINDUMP_DEV", "0") == "1"
    uvicorn.run(
        "braindump.app:app",
        host="127.0.0.1",
        port=args.port,
        reload=dev,
    )


def _cmd_update(args: argparse.Namespace) -> None:
    """Apply pending schema migrations to the workspace."""
    workspace: Path = args.workspace.resolve()
    applied = migrations.run_migrations(workspace)
    if applied:
        for desc in applied:
            _logger.info("Applied: %s", desc)
    else:
        _logger.info("Workspace is already up-to-date.")


def _cmd_user_add(args: argparse.Namespace) -> None:
    """Add a user to the workspace registry and print the generated token."""
    workspace: Path = args.workspace.resolve()
    username: str = args.username

    users_file = dirs.users_path(workspace)
    registry = UserRegistry(users_file)
    if users_file.exists():
        registry.load()

    try:
        token = registry.add_user(username)
    except ValueError as exc:
        _logger.error("Error: %s", exc)
        sys.exit(1)

    registry.save()
    _ensure_gitignore(workspace)

    _logger.info("User '%s' added.", username)
    _logger.info("Access token (shown once — store it securely):\n\n  %s\n", token)
    _logger.info("Restart the server to activate multi-user mode if this is the first user.")


def _cmd_user_update_token(args: argparse.Namespace) -> None:
    """Rotate the access token for an existing user."""
    workspace: Path = args.workspace.resolve()
    username: str = args.username

    users_file = dirs.users_path(workspace)
    if not users_file.exists():
        _logger.error("Error: no user registry found at %s. Run `braindump user add` first.", users_file)
        sys.exit(1)

    registry = UserRegistry(users_file)
    registry.load()

    try:
        token = registry.update_token(username)
    except ValueError as exc:
        _logger.error("Error: %s", exc)
        sys.exit(1)

    registry.save()

    _logger.info("Token updated for '%s'.", username)
    _logger.info("New access token (shown once — store it securely):\n\n  %s\n", token)
    _logger.info("The old token is now invalid. Restart the server to apply the change.")


def _ensure_gitignore(workspace: Path) -> None:
    """Add ``.users/`` to ``<workspace>/.gitignore`` if not already present."""
    gitignore = workspace / ".gitignore"
    entry = ".users/"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        lines = content.splitlines()
        if entry in lines or entry.rstrip("/") in lines:
            return
        updated = content.rstrip("\n") + f"\n{entry}\n"
        gitignore.write_text(updated, encoding="utf-8")
    else:
        gitignore.write_text(f"{entry}\n", encoding="utf-8")
    _logger.info("Added '%s' to %s", entry, gitignore)
