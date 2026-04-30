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

"""LLM backend for the RAG query pipeline.

:class:`ClaudeBackend` calls the Anthropic SDK directly using the
credentials managed by an authenticated Claude Code installation.

The active model is selected from ``llm.json`` inside the workspace
``.config`` directory, written once by ``braindump init``.
"""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, NamedTuple

import claude_agent_sdk

from braindump.types import ChatTurn, LLMConfig


class LLMCompletion(NamedTuple):
    """Result of a single LLM completion call."""

    text: str
    cost_usd: float
    total_tokens: int


########################################################################################################################
# Constants                                                                                                            #
########################################################################################################################

LLM_CONFIG_FILENAME = "llm.json"

_PING_SYSTEM = "You are a connectivity test assistant."
_PING_PROMPT = "Reply with exactly one word: pong"

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################


class ChatBackend(ABC):
    """Common interface every LLM backend must implement."""

    @abstractmethod
    async def _complete_async(
        self,
        system: str,
        history: list[ChatTurn],
        user_message: str,
        allowed_read_dir: Path | None = None,
    ) -> LLMCompletion:
        """Send a full conversation to the LLM and return the reply with usage info.

        Args:
            system: System prompt string.
            history: Prior turns from the current chat session, oldest first.
            user_message: The current user message (already includes RAG context).
            allowed_read_dir: When set, the LLM may use the Read tool restricted to
                files inside this directory.  Otherwise all file-system tools are off.

        Returns:
            :class:`LLMCompletion` with ``text``, ``cost_usd``, and ``total_tokens``.
        """

    def complete_with_usage(
        self,
        system: str,
        history: list[ChatTurn],
        user_message: str,
        allowed_read_dir: Path | None = None,
    ) -> LLMCompletion:
        """Synchronous wrapper around :meth:`_complete_async` — runs a fresh event loop."""
        return asyncio.run(self._complete_async(system, history, user_message, allowed_read_dir))

    def complete(
        self,
        system: str,
        history: list[ChatTurn],
        user_message: str,
        allowed_read_dir: Path | None = None,
    ) -> str:
        """Convenience wrapper — returns only the reply text, discarding usage info."""
        return self.complete_with_usage(system, history, user_message, allowed_read_dir).text

    def ping(self) -> bool:
        """Test connectivity by issuing a ping and expecting pong in the reply.

        Returns:
            ``True`` if the backend responded with a message containing "pong".
        """
        try:
            reply = self.complete(_PING_SYSTEM, [], _PING_PROMPT)
            return "pong" in reply.lower()
        except Exception:
            return False


class ClaudeBackend(ChatBackend):
    """Claude Agent SDK backend for Anthropic subscription (Claude Code) auth.

    Runs the system-installed ``claude`` CLI as a managed subprocess via
    ``claude-agent-sdk``.  Authentication is handled entirely by the CLI's
    stored ``~/.claude/`` credentials — a working, authenticated Claude Code
    installation is required before starting braindump.

    Args:
        model: Anthropic model name passed to the CLI.
    """

    def __init__(self, model: str) -> None:
        self._model = model

    async def _complete_async(
        self,
        system: str,
        history: list[ChatTurn],
        user_message: str,
        allowed_read_dir: Path | None = None,
    ) -> LLMCompletion:
        # Format prior turns into the prompt so the model has session context.
        # The Agent SDK starts fresh on each query() call, so history is
        # embedded as a transcript rather than as structured message objects.
        parts: list[str] = []
        for turn in history:
            label = "User" if turn.role == "user" else "Assistant"
            parts.append(f"{label}: {turn.text}")
        parts.append(f"User: {user_message}")
        prompt = "\n\n".join(parts)

        disallowed = [
            "Bash",
            "Write",
            "Edit",
            "MultiEdit",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "TodoWrite",
            "TodoRead",
            "NotebookRead",
            "NotebookEdit",
        ]
        if allowed_read_dir is None:
            disallowed.append("Read")

        resolved_dir = allowed_read_dir.resolve() if allowed_read_dir is not None else None

        async def _can_use_tool(
            tool_name: str,
            tool_input: dict[str, Any],
            context: claude_agent_sdk.ToolPermissionContext,
        ) -> claude_agent_sdk.PermissionResultAllow | claude_agent_sdk.PermissionResultDeny:
            if tool_name == "Read" and resolved_dir is not None:
                file_path = Path(tool_input.get("file_path", "")).resolve()
                try:
                    file_path.relative_to(resolved_dir)
                    return claude_agent_sdk.PermissionResultAllow()
                except ValueError:
                    return claude_agent_sdk.PermissionResultDeny(message=f"Read is restricted to {resolved_dir}")
            return claude_agent_sdk.PermissionResultDeny(message=f"Tool {tool_name} is not permitted")

        options = claude_agent_sdk.ClaudeAgentOptions(
            system_prompt=system,
            model=self._model,
            max_turns=10 if allowed_read_dir is not None else 1,
            disallowed_tools=disallowed,
            can_use_tool=_can_use_tool if allowed_read_dir is not None else None,
        )

        chunks: list[str] = []
        cost_usd = 0.0
        total_tokens = 0
        try:
            async for message in claude_agent_sdk.query(prompt=prompt, options=options):
                if isinstance(message, claude_agent_sdk.AssistantMessage):
                    for block in message.content:
                        if isinstance(block, claude_agent_sdk.TextBlock):
                            chunks.append(block.text)
                elif isinstance(message, claude_agent_sdk.ResultMessage):
                    cost_usd = message.total_cost_usd or 0.0
                    if message.usage:
                        total_tokens = message.usage.get("input_tokens", 0) + message.usage.get("output_tokens", 0)
        except Exception as exc:
            raise RuntimeError(f"Claude CLI failed: {exc}") from exc

        return LLMCompletion("".join(chunks), cost_usd, total_tokens)


def load_backend(braindump_data_dir: Path) -> ChatBackend:
    """Instantiate the configured :class:`ChatBackend` from ``llm.json``.

    Args:
        braindump_data_dir: Path to the ``.config`` directory.

    Returns:
        The active :class:`ChatBackend` instance.

    Raises:
        RuntimeError: If ``llm.json`` is missing or the model field is empty.
    """
    config_path = braindump_data_dir / LLM_CONFIG_FILENAME

    if not config_path.exists():
        raise RuntimeError("LLM backend not configured. Run `braindump init <workspace>` to set it up.")

    config = LLMConfig.model_validate_json(config_path.read_text(encoding="utf-8"))

    if not config.model:
        raise RuntimeError(f"No model specified in {config_path}. Run `braindump init <workspace>` to reconfigure.")

    return ClaudeBackend(model=config.model)
