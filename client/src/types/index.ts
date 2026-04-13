/* ---------------------------------------------------------------
 * PMOS — Shared TypeScript types
 * All domain models used across pages, components, stores & hooks
 * --------------------------------------------------------------- */

/* ---- Conversations & Messages ---- */

export interface Conversation {
  id: string;
  team_id?: string;
  title: string;
  created_at: string;
  updated_at: string;
  status: 'active' | 'archived' | 'deleted';
  message_count: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'agent' | 'system';
  content: string;
  agent_name?: string;
  agent_id?: number;
  model?: string;
  score?: number;
  band?: ScoreBand;
  latency_ms?: number;
  tool_calls?: ToolCall[];
  steps?: PipelineStep[];
  course_correction?: CourseCorrection;
  timestamp: string;
}

export interface ScoreBand {
  low: number;
  high: number;
}

/* ---- Tool Calls ---- */

export interface ToolCall {
  id: string;
  tool_name: string;
  tool_type: string;
  status: 'success' | 'error' | 'running';
  latency_ms: number;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
}

/* ---- Pipeline Steps ---- */

export type PipelineStepStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface PipelineStep {
  name: string;
  label: string;
  status: PipelineStepStatus;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  details?: StepDetail[];
}

export interface StepDetail {
  agent_name: string;
  agent_id: number;
  score?: number;
  action: string;
}

/* ---- Course Correction ---- */

export interface CourseCorrection {
  reason: string;
  from_agent?: string;
  to_agent?: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  details?: string;
}

/* ---- Task Graph ---- */

export type TaskNodeStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'SUCCESS'
  | 'FAILED'
  | 'CORRECTING'
  | 'SKIPPED';

export interface TaskNode {
  task_id: string;
  parent_id: string | null;
  depth: number;
  status: TaskNodeStatus;
  description: string;
  agent_name?: string;
  agent_id?: number;
  score?: number;
  band?: ScoreBand;
  criticality?: 'low' | 'medium' | 'high' | 'critical';
  execution_time_ms?: number;
  iteration?: number;
  correction_history?: CorrectionEntry[];
  created_at: string;
  updated_at: string;
  /** Backend may return these alternate field names */
  node_id?: string;
  assigned_agent_name?: string;
  graph_id?: string;
}

export interface TaskEdge {
  source: string;
  target: string;
  relationship: 'SPAWNED_BY' | 'ASSIGNED_TO' | 'FOLLOWS_SOP';
}

export interface TaskGraphData {
  nodes: TaskNode[];
  edges: TaskEdge[];
}

export interface CorrectionEntry {
  timestamp: string;
  from_agent: string;
  to_agent: string;
  reason: string;
  severity: string;
}

/* ---- WebSocket stream events ---- */

export type WSEventType =
  | 'step'
  | 'tool_call'
  | 'score'
  | 'course_correct'
  | 'complete'
  | 'stream_chunk'
  | 'stream_complete'
  | 'error';

export interface WSEvent {
  type: WSEventType;
  agent_name: string;
  content: string;
  score: number | null;
  trace_id: string;
  timestamp: string;
}

/* ---- Agents ---- */

export interface Agent {
  id: number;
  agent_id: string;
  name: string;
  role: string;
  status: 'IDLE' | 'ACTIVE' | 'BUSY' | 'DEGRADED' | 'DEPRECATED';
  foundation_model: string;
  accuracy_rate: number;
  success_rate: number;
  total_executions: number;
  health_score: number;
  description?: string;
  meta_capable: boolean;
  is_primary: boolean;
  tools: string[];
  domains: string[];
}

/* ---- Health ---- */

export interface ServiceHealth {
  status: string;
  latency_ms?: number;
}

export interface HealthStatus {
  service: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  latency_ms: number;
  timestamp: string;
  services?: Record<string, ServiceHealth>;
}

/* ---- Tools ---- */

export interface Tool {
  id: number;
  tool_id: string;
  name: string;
  description?: string;
  tool_type: string;
  hostname?: string;
  endpoint?: string;
  auth_method?: string;
  auth_config?: Record<string, unknown>;
  status: 'ACTIVE' | 'DEGRADED' | 'OFFLINE';
  avg_latency_ms: number;
  success_rate: number;
  last_health_check?: string;
  is_dynamic: boolean;
}

/* ---- Capabilities ---- */

export interface Capability {
  id: number;
  capability_type: 'TOOL' | 'SKILL' | 'AGENT';
  capability_id: string;
  name: string;
  description?: string;
  source: 'STATIC' | 'DYNAMIC';
  validation_score?: number;
  is_active: boolean;
  usage_count: number;
  created_at: string;
}

/* ---- Teams ---- */

export interface Team {
  id: number;
  team_id: string;
  name: string;
  description?: string;
  use_smart_workflow: boolean;
  accuracy_threshold: number;
  max_retries: number;
  retry_strategy: 'LINEAR' | 'EXPONENTIAL' | 'FIBONACCI';
  agents?: TeamAgent[];
  created_at?: string;
}

export interface TeamAgent {
  agent_id: string;
  agent_name?: string;
  priority: number;
  role?: string;
  parent_agent_id?: string | null;
  execution_mode?: string;
  criticality?: string;
  timeout_seconds?: number;
  fallback_agent_id?: string | null;
  accuracy: number;
  success_rate: number;
}

/* ---- Documents ---- */

export interface Document {
  id: number;
  document_id: string;
  filename: string;
  mime_type: string;
  file_size: number;
  status: 'UPLOADING' | 'CHUNKING' | 'EMBEDDING' | 'INDEXED' | 'FAILED';
  chunk_count?: number;
  embedding_model?: string;
  team_id?: string;
  agent_id?: number;
  created_at: string;
}

/* ---- Agent Interactions ---- */

export type InteractionType =
  | 'task_assignment'
  | 'tool_call'
  | 'tool_result'
  | 'score_request'
  | 'score_evaluation'
  | 'memory_read'
  | 'memory_write'
  | 'rag_query'
  | 'course_correction'
  | 'error'
  | 'fallback'
  | 'sub_agent_spawn'
  | 'sub_agent_result';

export interface AgentInteraction {
  id: string;
  from_service: string;
  to_service: string;
  type: InteractionType;
  summary?: string;
  timestamp: string;
  duration_ms: number;
  request_payload?: Record<string, unknown>;
  response_payload?: Record<string, unknown>;
  trace_id?: string;
  is_sub_agent?: boolean;
  parent_node_id?: string;
  sub_agent_depth?: number;
  sub_agent_name?: string;
  children?: AgentInteraction[];
}

/* ---- Task Decomposition ---- */

export interface TaskDecomposition {
  graph_id: string;
  message_id: string;
  nodes: TaskNode[];
  edges: Array<{ source: string; target: string; label: string }>;
}

/* ---- API response wrappers ---- */

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApiError {
  error: string;
  code: string;
  trace_id: string;
}

/* ---- Task Decomposition Detail (extended node info) ---- */

export interface TaskNodeDetail extends TaskNode {
  fallback_agents?: Array<{ id: number; name: string }>;
  retry_count?: number;
  tool_calls?: ToolCall[];
  memory_hits?: MemoryHits;
}

export interface MemoryHits {
  short_term: number;
  long_term: number;
  reasoning: number;
  episodic: number;
}

/* ---- Memory Entries ---- */

export interface MemoryEntry {
  id: number;
  agent_id: number;
  memory_tier: 'SHORT_TERM' | 'LONG_TERM' | 'REASONING' | 'EPISODIC';
  content: string;
  metadata?: Record<string, unknown>;
  relevance_score: number;
  access_count: number;
  decay_factor: number;
  expires_at?: string;
  created_at: string;
}

/* ---- Score History ---- */

export interface ScoreHistory {
  id: number;
  agent_id: number;
  task_id?: string;
  context_type: string;
  score: number;
  factors: Record<string, number>;
  band_low: number;
  band_high: number;
  within_band: boolean;
  created_at: string;
}
