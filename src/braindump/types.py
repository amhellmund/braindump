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


class SpikeMeta(BaseModel):
    """Per-spike metadata entry stored in ``wiki/meta.json``."""

    title: str
    tags: list[str] = []
    created_at: str = ""
    modified_at: str = ""
    languages: list[str] = []
    image_count: int = 0


class SpikeMetaEntry(SpikeMeta):
    """SpikeMeta with its spike ID attached, as returned by ``list_all_meta``."""

    id: str


class Section(BaseModel):
    """A single ## section within a spike."""

    heading: str | None
    content: str


class SpikePayload(BaseModel):
    """Request body for creating or updating a spike."""

    raw: str = Field(max_length=200_000)


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


class ChatTurn(BaseModel):
    """A single prior turn in the conversation (user or assistant)."""

    role: Literal["user", "assistant"]
    text: str


class QueryRequest(BaseModel):
    """Request body for a RAG query."""

    query: str = Field(max_length=10_000)
    history: list[ChatTurn] = []


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


LogDetail = Annotated[
    WikiUpdateLogDetail | WikiRemoveLogDetail | HealthCheckLogDetail | HealthRepairLogDetail,
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
