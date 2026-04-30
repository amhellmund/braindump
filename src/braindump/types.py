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

"""Pydantic models for spike request and response payloads."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

########################################################################################################################
# Public Interface                                                                                                     #
########################################################################################################################


class LLMConfig(BaseModel):
    """Configuration stored in ``.config/llm.json``."""

    model: str
    env_file: str | None = None
    health_check_interval_minutes: int = Field(60, gt=0)


class WorkspaceVersions(BaseModel):
    """Schema version numbers stored in ``versions.json`` at the workspace root."""

    wiki_schema: int = 1
    meta: int = 1
    streams: int = 1
    dailies: int = 0


class SpikeMeta(BaseModel):
    """Per-spike metadata entry stored in ``wiki/meta.json``."""

    title: str
    tags: list[str] = []
    created_at: str = ""
    modified_at: str = ""
    languages: list[str] = []
    image_count: int = 0
    wiki_pending: bool = False


class SpikeMetaEntry(SpikeMeta):
    """SpikeMeta with its spike ID attached, as returned by ``list_all_meta``."""

    id: str


class Section(BaseModel):
    """A single ## section within a spike."""

    heading: str | None
    content: str


class StreamMeta(BaseModel):
    """Metadata for a single named stream stored in ``streams/streams.json``."""

    created_at: str
    modified_at: str
    summary_at: str | None = None


class StreamsData(BaseModel):
    """Full contents of ``streams/streams.json`` — maps stream name to its metadata."""

    streams: dict[str, StreamMeta] = {}


class StreamsAssignments(BaseModel):
    """Full contents of ``streams/assignments.json`` — maps spike_id to stream name."""

    assignments: dict[str, str] = {}


class InfoResponse(BaseModel):
    """Response for the /info endpoint."""

    version: str
    wiki_schema: int
    meta: int
    streams: int
    dailies: int


class SpikePayload(BaseModel):
    """Request body for creating or updating a spike."""

    raw: str = Field(max_length=200_000)
    stream: str | None = None
    update_wiki: bool = True


class SpikeResponse(BaseModel):
    """Full spike representation returned by the API."""

    id: str
    title: str
    tags: list[str]
    createdAt: str
    modifiedAt: str
    raw: str
    sections: list[Section]
    languages: list[str] = []
    image_count: int = 0
    stream: str | None = None
    wikiPending: bool = False


class ChatTurn(BaseModel):
    """A single prior turn in the conversation (user or assistant)."""

    role: Literal["user", "assistant"]
    text: str


class QueryRequest(BaseModel):
    """Request body for a RAG query."""

    query: str = Field(max_length=10_000)
    history: list[ChatTurn] = []
    session_id: str | None = None


class QuerySource(BaseModel):
    """A single retrieved source cited in the answer."""

    index: int
    spikeId: str
    title: str
    section: str
    snippet: str


class QueryResponse(BaseModel):
    """Response from the RAG query pipeline."""

    answer: str
    citations: list[QuerySource]
    sessionId: str = ""


class StoredChatTurn(BaseModel):
    """A single query-answer pair stored as part of a persisted chat session."""

    query: str
    answer: str
    citations: list[QuerySource]
    timestamp: str


class ChatSession(BaseModel):
    """Full chat session as stored on disk in ``workspace/chats/{id}.json``."""

    id: str
    title: str
    created_at: str
    updated_at: str
    turns: list[StoredChatTurn]


class ChatSessionSummary(BaseModel):
    """Lightweight session summary returned by ``GET /chats``."""

    id: str
    title: str
    createdAt: str
    updatedAt: str
    turnCount: int


class ChatSessionResponse(BaseModel):
    """Full session returned by ``GET /chats/{session_id}``."""

    id: str
    title: str
    createdAt: str
    updatedAt: str
    turns: list[StoredChatTurn]


class ImageUploadResponse(BaseModel):
    """Returned after a successful image upload."""

    filename: str
    url: str


class HealthReport(BaseModel):
    """Result of a wiki consistency health check."""

    checked_at: str
    missing_index_entries: list[str]
    stale_index_entries: list[str]
    broken_links: list[str]
    orphaned_wiki_pages: list[str]
    incomplete_transactions: list[str]
    issues: list[str]


class WikiUpdateLogDetail(BaseModel):
    """Details captured when the LLM updates the wiki for a spike."""

    kind: Literal["wiki_update"] = "wiki_update"
    spike_id: str
    spike_title: str
    index_section: str
    connections_lines: list[str]
    hierarchy_section: str
    cost_usd: float
    total_tokens: int
    system_prompt_chars: int | None = None
    prompt_chars: int | None = None


class WikiRemoveLogDetail(BaseModel):
    """Details captured when the LLM removes a spike from the wiki."""

    kind: Literal["wiki_remove"] = "wiki_remove"
    spike_id: str
    cost_usd: float
    total_tokens: int
    system_prompt_chars: int | None = None
    prompt_chars: int | None = None


class HealthCheckLogDetail(BaseModel):
    """Details from a wiki consistency health check."""

    kind: Literal["health_check"] = "health_check"
    issues: list[str]


class HealthRepairLogDetail(BaseModel):
    """Details from a health-check repair run."""

    kind: Literal["health_repair"] = "health_repair"
    repaired_count: int
    errors: list[str]


class StreamSummaryLogDetail(BaseModel):
    """Details captured when the LLM generates a stream summary."""

    kind: Literal["stream_summary"] = "stream_summary"
    stream_name: str
    spike_count: int
    cost_usd: float
    total_tokens: int


class DailySummaryLogDetail(BaseModel):
    """Details captured when the LLM generates a daily summary."""

    kind: Literal["daily_summary"] = "daily_summary"
    date: str
    spike_count: int
    cost_usd: float
    total_tokens: int


LogDetail = Annotated[
    WikiUpdateLogDetail
    | WikiRemoveLogDetail
    | HealthCheckLogDetail
    | HealthRepairLogDetail
    | StreamSummaryLogDetail
    | DailySummaryLogDetail,
    Field(discriminator="kind"),
]


class LogEntry(BaseModel):
    """A single activity log entry, optionally carrying structured detail."""

    ts: str
    summary: str
    detail: LogDetail | None = None


class UsageData(BaseModel):
    """Persisted LLM usage counters stored in ``.config/usage.json``."""

    total_cost_usd: float = 0.0
    total_tokens: int = 0


class StatusResponse(BaseModel):
    """Current LLM sync state and cumulative usage since server start."""

    syncing: bool
    total_cost_usd: float
    total_tokens: int


class StreamInfo(BaseModel):
    """Stream metadata returned by ``GET /api/v1/streams``."""

    name: str
    created_at: str
    modified_at: str
    summary_at: str | None
    spike_count: int
    summary_pending: bool


class StreamSummaryResponse(BaseModel):
    """Stream summary returned by the stream summary endpoints."""

    stream_name: str
    content: str
    generated_at: str


class DailyMeta(BaseModel):
    """Metadata for a single day stored in ``dailies/dailies.json``."""

    summary_at: str | None = None


class DailiesData(BaseModel):
    """Full contents of ``dailies/dailies.json`` — maps YYYY-MM-DD date to its metadata."""

    dailies: dict[str, DailyMeta] = {}


class DailyInfo(BaseModel):
    """Daily metadata returned by ``GET /api/v1/dailies``."""

    date: str
    spike_count: int
    summary_at: str | None
    summary_pending: bool


class DailySummaryResponse(BaseModel):
    """Daily summary returned by the daily summary endpoints."""

    date: str
    content: str
    generated_at: str
