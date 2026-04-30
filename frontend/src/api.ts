/**
 * Typed API client for the braindump backend.
 * All functions throw on non-OK responses.
 */

import { Daily, GraphEdge, GraphNode, Spike, Stream } from './types'

const BASE = '/api/v1'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`)
  }
  // 204 No Content — no body to parse
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

export async function fetchSpikes(): Promise<Spike[]> {
  return request<Spike[]>('/spikes')
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export async function fetchGraph(zoomLevel: number = 2): Promise<GraphData> {
  return request<GraphData>(`/graph?zoom=${zoomLevel}`)
}

export async function createSpike(
  raw: string,
  stream: string | null = null,
  updateWiki = true,
): Promise<Spike> {
  return request<Spike>('/spikes', {
    method: 'POST',
    body: JSON.stringify({ raw, stream, update_wiki: updateWiki }),
  })
}

export async function updateSpike(
  id: string,
  raw: string,
  stream: string | null = null,
  updateWiki = true,
): Promise<Spike> {
  return request<Spike>(`/spikes/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ raw, stream, update_wiki: updateWiki }),
  })
}

export async function updateSpikeWiki(id: string): Promise<void> {
  return request<void>(`/spikes/${id}/update-wiki`, { method: 'POST' })
}

export async function triggerPendingWikiUpdates(): Promise<{ queued: number }> {
  return request<{ queued: number }>('/wiki/trigger-pending', { method: 'POST' })
}

export async function deleteSpike(id: string): Promise<void> {
  return request<void>(`/spikes/${id}`, { method: 'DELETE' })
}

export interface QuerySource {
  index: number
  spikeId: string
  title: string
  section: string
  snippet: string
}

export interface QueryResponse {
  answer: string
  citations: QuerySource[]
  sessionId: string
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  text: string
}

export async function sendQuery(
  query: string,
  history: ChatTurn[] = [],
  sessionId?: string,
): Promise<QueryResponse> {
  return request<QueryResponse>('/query', {
    method: 'POST',
    body: JSON.stringify({
      query,
      history,
      ...(sessionId !== undefined ? { session_id: sessionId } : {}),
    }),
  })
}

export interface ChatSessionSummary {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  turnCount: number
}

export interface StoredChatTurn {
  query: string
  answer: string
  citations: QuerySource[]
  timestamp: string
}

export interface ChatSessionDetail {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  turns: StoredChatTurn[]
}

export async function fetchChatSessions(): Promise<ChatSessionSummary[]> {
  return request<ChatSessionSummary[]>('/chats')
}

export async function fetchChatSession(sessionId: string): Promise<ChatSessionDetail> {
  return request<ChatSessionDetail>(`/chats/${sessionId}`)
}

export interface ImageUploadResponse {
  filename: string
  url: string
}

export interface StatusData {
  syncing: boolean
  total_cost_usd: number
  total_tokens: number
}

export async function fetchStatus(): Promise<StatusData> {
  return request<StatusData>('/status')
}

export interface WikiUpdateLogDetail {
  kind: 'wiki_update'
  spike_id: string
  spike_title: string
  index_section: string
  connections_lines: string[]
  hierarchy_section: string
  cost_usd: number
  total_tokens: number
  system_prompt_chars?: number
  prompt_chars?: number
}

export interface WikiRemoveLogDetail {
  kind: 'wiki_remove'
  spike_id: string
  cost_usd: number
  total_tokens: number
  system_prompt_chars?: number
  prompt_chars?: number
}

export interface HealthCheckLogDetail {
  kind: 'health_check'
  issues: string[]
}

export interface HealthRepairLogDetail {
  kind: 'health_repair'
  repaired_count: number
  errors: string[]
}

export interface StreamSummaryLogDetail {
  kind: 'stream_summary'
  stream_name: string
  spike_count: number
  cost_usd: number
  total_tokens: number
}

export interface DailySummaryLogDetail {
  kind: 'daily_summary'
  date: string
  spike_count: number
  cost_usd: number
  total_tokens: number
}

export type LogDetail =
  | WikiUpdateLogDetail
  | WikiRemoveLogDetail
  | HealthCheckLogDetail
  | HealthRepairLogDetail
  | StreamSummaryLogDetail
  | DailySummaryLogDetail

export interface LogEntry {
  ts: string
  summary: string
  detail?: LogDetail
}

export async function fetchLog(lines = 50): Promise<{ entries: LogEntry[] }> {
  return request<{ entries: LogEntry[] }>(`/braindump/log?lines=${lines}`)
}

export interface InfoData {
  version: string
  wiki_schema: number
  meta: number
  streams: number
  dailies: number
}

export async function fetchInfo(): Promise<InfoData> {
  return request<InfoData>('/info')
}

export interface StreamSummaryData {
  stream_name: string
  content: string
  generated_at: string
}

export async function fetchStreams(): Promise<Stream[]> {
  return request<Stream[]>('/streams')
}

export async function fetchStreamSummary(streamName: string): Promise<StreamSummaryData> {
  return request<StreamSummaryData>(`/streams/${encodeURIComponent(streamName)}/summary`)
}

export async function triggerStreamSummary(streamName: string): Promise<void> {
  return request<void>(`/streams/${encodeURIComponent(streamName)}/summarize`, { method: 'POST' })
}

export interface DailySummaryData {
  date: string
  content: string
  generated_at: string
}

export async function fetchDailies(): Promise<Daily[]> {
  return request<Daily[]>('/dailies')
}

export async function fetchDailySummary(date: string): Promise<DailySummaryData> {
  return request<DailySummaryData>(`/dailies/${encodeURIComponent(date)}/summary`)
}

export async function triggerDailySummary(date: string): Promise<void> {
  return request<void>(`/dailies/${encodeURIComponent(date)}/summarize`, { method: 'POST' })
}

export async function uploadImage(file: File): Promise<ImageUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  // No Content-Type header — browser sets multipart/form-data with boundary automatically
  const resp = await fetch(`${BASE}/images`, { method: 'POST', body: form })
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`)
  }
  return resp.json() as Promise<ImageUploadResponse>
}
