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

"""Tests for braindump.llm."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from braindump.llm import LLM_CONFIG_FILENAME, ClaudeBackend, load_backend
from braindump.types import ChatTurn

########################################################################################################################
# Helpers
########################################################################################################################


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeAssistantMessage:
    def __init__(self, *blocks: _FakeTextBlock) -> None:
        self.content = list(blocks)


class _FakeResultMessage:
    """Minimal ResultMessage stub carrying cost and usage info."""

    def __init__(self, total_cost_usd: float = 0.0, usage: dict | None = None) -> None:
        self.total_cost_usd = total_cost_usd
        self.usage = usage


class _FakeOtherMessage:
    """Non-assistant, non-result message — should be ignored by ClaudeBackend."""


def _make_sdk(messages: list[object]) -> MagicMock:
    """Build a minimal claude_agent_sdk mock that yields *messages* from query()."""

    async def _query(**_kwargs: object) -> object:
        for msg in messages:
            yield msg

    sdk = MagicMock()
    sdk.TextBlock = _FakeTextBlock
    sdk.AssistantMessage = _FakeAssistantMessage
    sdk.ResultMessage = _FakeResultMessage
    sdk.ClaudeAgentOptions = MagicMock(return_value=MagicMock())
    sdk.query = _query
    return sdk


########################################################################################################################
# load_backend
########################################################################################################################


def test_load_backend_raises_when_config_missing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="braindump init"):
        load_backend(tmp_path)


def test_load_backend_raises_when_model_empty(tmp_path: Path) -> None:
    (tmp_path / LLM_CONFIG_FILENAME).write_text(json.dumps({"model": ""}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="No model specified"):
        load_backend(tmp_path)


def test_load_backend_returns_claude_backend_with_correct_model(tmp_path: Path) -> None:
    (tmp_path / LLM_CONFIG_FILENAME).write_text(json.dumps({"model": "claude-sonnet-4-6"}), encoding="utf-8")
    backend = load_backend(tmp_path)
    assert isinstance(backend, ClaudeBackend)
    assert backend._model == "claude-sonnet-4-6"


########################################################################################################################
# ClaudeBackend.complete
########################################################################################################################


def test_complete_returns_concatenated_text_blocks(tmp_path: Path) -> None:
    sdk = _make_sdk(
        [
            _FakeAssistantMessage(_FakeTextBlock("Hello"), _FakeTextBlock(", world")),
        ]
    )
    with patch("braindump.llm.claude_agent_sdk", sdk):
        result = ClaudeBackend(model="claude-sonnet-4-6").complete("sys", [], "hi")
    assert result == "Hello, world"


def test_complete_ignores_non_assistant_messages(tmp_path: Path) -> None:
    sdk = _make_sdk([_FakeOtherMessage(), _FakeAssistantMessage(_FakeTextBlock("ok"))])
    with patch("braindump.llm.claude_agent_sdk", sdk):
        result = ClaudeBackend(model="claude-sonnet-4-6").complete("sys", [], "hi")
    assert result == "ok"


def test_complete_raises_runtime_error_on_sdk_failure() -> None:
    async def _failing_query(**_kwargs: object) -> object:
        raise ValueError("network error")
        yield  # make it a generator

    sdk = MagicMock()
    sdk.TextBlock = _FakeTextBlock
    sdk.AssistantMessage = _FakeAssistantMessage
    sdk.ResultMessage = _FakeResultMessage
    sdk.ClaudeAgentOptions = MagicMock(return_value=MagicMock())
    sdk.query = _failing_query

    with patch("braindump.llm.claude_agent_sdk", sdk), pytest.raises(RuntimeError, match="Claude CLI failed"):
        ClaudeBackend(model="claude-sonnet-4-6").complete("sys", [], "hi")


def test_complete_embeds_history_in_prompt() -> None:
    """History turns must be formatted as a transcript before the user message."""
    captured: list[str] = []

    async def _capturing_query(*, prompt: str, **_kwargs: object) -> object:
        captured.append(prompt)
        yield _FakeAssistantMessage(_FakeTextBlock("reply"))

    sdk = MagicMock()
    sdk.TextBlock = _FakeTextBlock
    sdk.AssistantMessage = _FakeAssistantMessage
    sdk.ResultMessage = _FakeResultMessage
    sdk.ClaudeAgentOptions = MagicMock(return_value=MagicMock())
    sdk.query = _capturing_query

    history = [ChatTurn(role="user", text="first"), ChatTurn(role="assistant", text="second")]
    with patch("braindump.llm.claude_agent_sdk", sdk):
        ClaudeBackend(model="claude-sonnet-4-6").complete("sys", history, "third")

    assert len(captured) == 1
    prompt = captured[0]
    assert "User: first" in prompt
    assert "Assistant: second" in prompt
    assert "User: third" in prompt


def test_complete_with_usage_extracts_cost_and_tokens() -> None:
    result_msg = _FakeResultMessage(
        total_cost_usd=0.042,
        usage={"input_tokens": 100, "output_tokens": 50},
    )
    sdk = _make_sdk([_FakeAssistantMessage(_FakeTextBlock("hello")), result_msg])
    with patch("braindump.llm.claude_agent_sdk", sdk):
        completion = ClaudeBackend(model="claude-sonnet-4-6").complete_with_usage("sys", [], "hi")
    assert completion.text == "hello"
    assert completion.cost_usd == pytest.approx(0.042)
    assert completion.total_tokens == 150


def test_complete_with_usage_defaults_to_zero_when_no_result_message() -> None:
    sdk = _make_sdk([_FakeAssistantMessage(_FakeTextBlock("hi"))])
    with patch("braindump.llm.claude_agent_sdk", sdk):
        completion = ClaudeBackend(model="claude-sonnet-4-6").complete_with_usage("sys", [], "ping")
    assert completion.cost_usd == 0.0
    assert completion.total_tokens == 0


########################################################################################################################
# ChatBackend.ping
########################################################################################################################


def test_ping_returns_true_when_pong_in_reply() -> None:
    sdk = _make_sdk([_FakeAssistantMessage(_FakeTextBlock("pong"))])
    with patch("braindump.llm.claude_agent_sdk", sdk):
        assert ClaudeBackend(model="claude-sonnet-4-6").ping() is True


def test_ping_is_case_insensitive() -> None:
    sdk = _make_sdk([_FakeAssistantMessage(_FakeTextBlock("PONG"))])
    with patch("braindump.llm.claude_agent_sdk", sdk):
        assert ClaudeBackend(model="claude-sonnet-4-6").ping() is True


def test_ping_returns_false_when_no_pong_in_reply() -> None:
    sdk = _make_sdk([_FakeAssistantMessage(_FakeTextBlock("hello"))])
    with patch("braindump.llm.claude_agent_sdk", sdk):
        assert ClaudeBackend(model="claude-sonnet-4-6").ping() is False


def test_ping_returns_false_on_exception() -> None:
    async def _failing_query(**_kwargs: object) -> object:
        raise RuntimeError("no connection")
        yield

    sdk = MagicMock()
    sdk.TextBlock = _FakeTextBlock
    sdk.AssistantMessage = _FakeAssistantMessage
    sdk.ResultMessage = _FakeResultMessage
    sdk.ClaudeAgentOptions = MagicMock(return_value=MagicMock())
    sdk.query = _failing_query

    with patch("braindump.llm.claude_agent_sdk", sdk):
        assert ClaudeBackend(model="claude-sonnet-4-6").ping() is False
