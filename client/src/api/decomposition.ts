import { useQuery } from '@tanstack/react-query';
import apiClient from '@/api/axios';
import type { TaskDecomposition, TaskNodeDetail, AgentInteraction, Agent } from '@/types';

export function useTaskDecomposition(conversationId: string | undefined, messageId: string | undefined) {
  return useQuery<TaskDecomposition>({
    queryKey: ['decomposition', conversationId, messageId],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (messageId) params.message_id = messageId;
      const { data } = await apiClient.get(
        `/v1/conversations/${conversationId}/decomposition`,
        { params },
      );
      // Transform API response {tasks: [...]} to expected {nodes: [...], edges: [...]}
      const tasks = data.tasks ?? data.nodes ?? [];
      const nodes = tasks.map((t: Record<string, unknown>) => ({
        ...t,
        id: t.node_id || t.task_id || t.id,
        task_id: t.node_id || t.task_id || t.id,
        agent_name: t.assigned_agent_name || t.agent_name,
        agent_id: t.assigned_agent_id || t.agent_id,
      }));
      const edges = tasks
        .filter((t: Record<string, unknown>) => t.parent_id)
        .map((t: Record<string, unknown>) => ({
          source: String(t.parent_id),
          target: String(t.node_id || t.task_id || t.id),
          label: 'SPAWNED_BY',
        }));
      return {
        graph_id: data.graph_id ?? tasks[0]?.graph_id ?? '',
        message_id: messageId ?? '',
        nodes,
        edges,
      };
    },
    enabled: !!conversationId,
  });
}

export function useTaskNodeDetail(conversationId: string | undefined, taskId: string | undefined) {
  return useQuery<TaskNodeDetail>({
    queryKey: ['task-node-detail', conversationId, taskId],
    queryFn: async () => {
      const { data } = await apiClient.get(
        `/v1/conversations/${conversationId}/tasks/${taskId}`,
      );
      return data;
    },
    enabled: !!conversationId && !!taskId,
  });
}

/* ---- Bid / negotiation data for a single task ---- */

export interface TaskBid {
  agent_id?: number;
  agent_name?: string;
  assigned_agent_name?: string;
  confidence?: number;
  bid_confidence?: number;
  can_solve?: boolean;
  approach?: string;
  tools_needed?: string[];
  estimated_latency_ms?: number;
  memory_hits?: number;
  rank_score?: number;
  event_type?: string;
  interaction_type?: string;
  timestamp?: string;
  source?: string;
  [key: string]: unknown;
}

export function useTaskBids(taskId: string | undefined) {
  return useQuery<TaskBid[]>({
    queryKey: ['task-bids', taskId],
    queryFn: async () => {
      const { data } = await apiClient.get(
        `/v1/orchestrator/tasks/${taskId}/bids`,
      );
      return data.bids ?? [];
    },
    enabled: !!taskId,
  });
}

export function useAgentInteractions(conversationId: string | undefined, messageId: string | undefined, agents?: Agent[]) {
  // Include agents in queryKey so interactions re-map when agents load
  const agentIds = agents?.map((a) => a.agent_id).join(',') ?? '';
  return useQuery<AgentInteraction[]>({
    queryKey: ['interactions', conversationId, messageId, agentIds],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (messageId) params.message_id = messageId;
      const { data } = await apiClient.get(
        `/v1/conversations/${conversationId}/interactions`,
        { params },
      );

      // Build agent name lookup from agents list
      const agentMap = new Map<string, string>();
      if (agents) {
        for (const a of agents) {
          agentMap.set(a.agent_id, a.name);
          agentMap.set(String(a.id), a.name);
        }
      }
      const resolveAgent = (id: string | unknown, fallbackName?: string) => {
        const sid = String(id || '');
        return agentMap.get(sid) || fallbackName || (sid === '0' ? 'Orchestrator' : sid.slice(0, 8));
      };

      const raw = data.interactions ?? data.items ?? data;
      const mysql = data.mysql_interactions ?? [];

      // Combine Neo4j and MySQL interactions
      const all = [...(raw as Record<string, unknown>[]), ...(mysql as Record<string, unknown>[])];

      return all.map((r, idx) => {
        const eventType = String(r.event_type || r.interaction_type || '');
        const agentId = String(r.agent_id || r.assigned_agent || r.from_id || '');

        // Extract agent_name from multiple possible sources
        // 1. Direct field on the record
        let nameFromRecord = r.assigned_agent_name || r.agent_name || r.from_name || '';
        // 2. Parse action_taken JSON (BID events store name inside JSON)
        if (!nameFromRecord && r.action_taken && typeof r.action_taken === 'string') {
          try {
            const parsed = JSON.parse(r.action_taken as string);
            nameFromRecord = parsed.agent_name || '';
          } catch { /* not JSON */ }
        }
        // 3. Parse description for AgentInteraction nodes
        if (!nameFromRecord && r.description && typeof r.description === 'string') {
          const descStr = r.description as string;
          // Extract from patterns like "Won bid for:", "Sub-agent spawned:"
          const match = descStr.match(/^(?:Won bid|Fallback|Sub-agent spawned).*?:\s/);
          if (!match) nameFromRecord = '';
        }

        const agentName = String(nameFromRecord || resolveAgent(agentId));
        const taskDesc = String(r.task_description || r.summary || r.description || '').slice(0, 60);
        const score = r.score != null ? Number(r.score) : null;
        const bidConf = r.bid_confidence != null ? Number(r.bid_confidence) : null;

        let type: AgentInteraction['type'] = 'tool_call';
        let fromService = 'orchestrator';
        let toService = taskDesc || 'task';
        let summary = '';

        if (eventType === 'BID_WON' || eventType === 'capability_bid_request') {
          type = 'task_assignment';
          fromService = 'Orchestrator';
          toService = agentName;
          summary = `Bid won by ${agentName} (confidence: ${(score ?? bidConf ?? 0).toFixed(2)})`;
        } else if (eventType === 'BID_SUBMITTED') {
          type = 'tool_result';
          fromService = agentName;
          toService = 'Orchestrator';
          summary = `${agentName} bid (confidence: ${(score ?? bidConf ?? 0).toFixed(2)})`;
        } else if (eventType === 'task_execution' || eventType === 'EXECUTION') {
          type = 'task_assignment';
          fromService = 'Orchestrator';
          toService = agentName || 'agent';
          const status = String(r.status || 'completed');
          summary = `Dispatched to ${agentName}: ${taskDesc} — ${status} (score: ${(score ?? 0).toFixed(2)})`;
        } else if (eventType === 'capability_bid_response') {
          type = 'tool_result';
          fromService = agentName;
          toService = 'Orchestrator';
          summary = `${agentName} bid response`;
        } else if (eventType === 'memory_read') {
          type = 'memory_read';
          fromService = agentName;
          toService = 'Memory';
          summary = String(r.summary || `${agentName} reading memory`);
        } else if (eventType === 'tool_call') {
          type = 'tool_call';
          fromService = agentName;
          toService = String(r.to_name || 'Tool');
          summary = String(r.summary || `${agentName} calling tool`);
        } else if (eventType === 'score_request' || eventType === 'SCORE_BELOW_BAND') {
          type = 'score_evaluation';
          fromService = 'Orchestrator';
          toService = 'Scoring';
          summary = String(r.summary || `Evaluating ${agentName} (score: ${(score ?? 0).toFixed(2)})`);
        } else if (eventType === 'AUTOCORRECT' || eventType === 'COURSE_CORRECTION') {
          type = 'course_correction';
          fromService = 'Orchestrator';
          toService = agentName;
          summary = `Auto-corrected: ${r.action_taken || 'score below band'}`;
        } else if (eventType === 'ESCALATION' || eventType === 'FALLBACK_ACTIVATION') {
          type = 'fallback';
          fromService = 'Orchestrator';
          toService = agentName;
          summary = `Fallback to ${agentName}: ${String(r.description || r.action_taken || '').slice(0, 60)}`;
        } else if (eventType === 'SUB_AGENT_SPAWN') {
          type = 'sub_agent_spawn';
          fromService = 'Orchestrator';
          toService = agentName;
          summary = `Sub-agent spawned: ${agentName} (depth ${r.sub_agent_depth || 1})`;
        } else if (eventType === 'BID_ACCURACY') {
          type = 'score_evaluation';
          fromService = 'Orchestrator';
          toService = agentName;
          summary = `Bid accuracy: ${r.action_taken || `score ${(score ?? 0).toFixed(2)}`}`;
        } else {
          // Generic: orchestrator dispatches outward
          fromService = 'Orchestrator';
          toService = agentName || taskDesc || 'task';
          summary = `${eventType || 'executed'}${score != null ? ` (score: ${score.toFixed(2)})` : ''}`;
        }

        return {
          id: String(r.event_id || r.interaction_id || r.node_id || idx),
          from_service: fromService,
          to_service: toService,
          type,
          summary,
          timestamp: String(r.timestamp || r.created_at || r.updated_at || new Date().toISOString()),
          duration_ms: Number(r.execution_time_ms || r.duration_ms || 0),
          request_payload: r.request_payload as Record<string, unknown> ?? { task: taskDesc, node_id: r.node_id },
          response_payload: r.response_payload as Record<string, unknown> ?? { status: r.status, score, agent: agentName, tools_used: r.tools_used },
        };
      });
    },
    enabled: !!conversationId,
  });
}
