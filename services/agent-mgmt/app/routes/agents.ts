import { Router, Request, Response } from 'express';
import { z } from 'zod';
import axios from 'axios';
import { agentService } from '../services/agentService';
import { agentHistoryService } from '../services/agentHistoryService';
import { config } from '../config';
import { logger } from '../utils/logger';
import { requestTotal, requestDurationSeconds } from '../utils/metrics';

const router = Router();

function traceId(req: Request): string {
  return (req.headers['x-request-id'] as string) || '';
}

function errorResponse(res: Response, status: number, message: string, code: string, tid: string) {
  return res.status(status).json({ error: message, code, trace_id: tid });
}

const createAgentSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
  foundation_model: z.string().optional(),
  meta_capable: z.boolean().optional(),
  is_primary: z.boolean().optional(),
});

const updateAgentSchema = z.object({
  name: z.string().min(1).optional(),
  description: z.string().optional(),
  foundation_model: z.string().optional(),
  status: z.enum(['IDLE', 'ACTIVE', 'BUSY', 'DEGRADED', 'DEPRECATED']).optional(),
  meta_capable: z.boolean().optional(),
  is_primary: z.boolean().optional(),
  accuracy_rate: z.number().min(0).max(1).optional(),
  success_rate: z.number().min(0).max(1).optional(),
  health_score: z.number().min(0).max(1).optional(),
  memory_seed: z.string().optional(),
  reasoning_seed: z.string().optional(),
});

const assignToolSchema = z.object({
  tool_id: z.string().uuid(),
  permission_level: z.enum(['READ', 'WRITE', 'ADMIN']).optional(),
});

const syncToolsSchema = z.object({
  tool_ids: z.array(z.string().uuid()),
});

const testAgentSchema = z.object({
  prompt: z.string().min(1),
  system_prompt: z.string().optional(),
  provider: z.string().optional(),
  model: z.string().optional(),
  temperature: z.number().min(0).max(2).optional(),
  max_tokens: z.number().int().positive().optional(),
});

// GET /v1/agents
router.get('/', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  try {
    const filter: { status?: string; meta_capable?: boolean } = {};
    if (req.query['status']) filter.status = req.query['status'] as string;
    if (req.query['meta_capable'] !== undefined) {
      filter.meta_capable = req.query['meta_capable'] === 'true';
    }

    const agents = await agentService.listAgents(filter as Parameters<typeof agentService.listAgents>[0]);
    requestTotal.inc({ method: 'GET', path: '/v1/agents', status: '200' });
    res.json({ agents, count: agents.length, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('listAgents failed', 'router', { error: error.message, trace_id: tid });
    requestTotal.inc({ method: 'GET', path: '/v1/agents', status: '500' });
    errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'GET', path: '/v1/agents' }, (Date.now() - start) / 1000);
  }
});

// POST /v1/agents
router.post('/', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  try {
    const parsed = createAgentSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'POST', path: '/v1/agents', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    const agent = await agentService.createAgent(parsed.data);
    requestTotal.inc({ method: 'POST', path: '/v1/agents', status: '201' });
    return res.status(201).json({ agent, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('createAgent failed', 'router', { error: error.message, trace_id: tid });
    requestTotal.inc({ method: 'POST', path: '/v1/agents', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'POST', path: '/v1/agents' }, (Date.now() - start) / 1000);
  }
});

// PUT /v1/agents/:agent_id/tools — bulk sync: replaces all tool assignments
router.put('/:agent_id/tools', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const agent_id = String(req.params.agent_id);
  try {
    const parsed = syncToolsSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'PUT', path: '/v1/agents/:id/tools', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    const tools = await agentService.syncTools(agent_id, parsed.data.tool_ids);
    requestTotal.inc({ method: 'PUT', path: '/v1/agents/:id/tools', status: '200' });
    return res.json({ tools, count: tools.length, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('syncTools failed', 'router', { error: error.message, agent_id, trace_id: tid });
    requestTotal.inc({ method: 'PUT', path: '/v1/agents/:id/tools', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'PUT', path: '/v1/agents/:id/tools' }, (Date.now() - start) / 1000);
  }
});

// DELETE /v1/agents/:agent_id/tools/:tool_id — remove a single tool assignment
router.delete('/:agent_id/tools/:tool_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const agent_id = String(req.params.agent_id);
  const tool_id = String(req.params.tool_id);
  try {
    const deleted = await agentService.removeTool(agent_id, tool_id);
    if (!deleted) {
      requestTotal.inc({ method: 'DELETE', path: '/v1/agents/:id/tools/:tool_id', status: '404' });
      return errorResponse(res, 404, 'Tool assignment not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'DELETE', path: '/v1/agents/:id/tools/:tool_id', status: '200' });
    return res.json({ message: 'Tool assignment removed', trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('removeTool failed', 'router', { error: error.message, agent_id, tool_id, trace_id: tid });
    requestTotal.inc({ method: 'DELETE', path: '/v1/agents/:id/tools/:tool_id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'DELETE', path: '/v1/agents/:id/tools/:tool_id' }, (Date.now() - start) / 1000);
  }
});

// POST /v1/agents/:agent_id/test — test agent with a prompt via LLM (with tool-use loop)
router.post('/:agent_id/test', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const agent_id = String(req.params.agent_id);
  try {
    const parsed = testAgentSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'POST', path: '/v1/agents/:id/test', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }

    // Fetch the agent
    const agent = await agentService.getAgent(agent_id);
    if (!agent) {
      requestTotal.inc({ method: 'POST', path: '/v1/agents/:id/test', status: '404' });
      return errorResponse(res, 404, 'Agent not found', 'NOT_FOUND', tid);
    }

    // Fetch assigned tools
    const agentTools = await agentService.listAgentTools(agent_id);

    const { prompt, system_prompt, provider, model, temperature, max_tokens } = parsed.data;

    // Cast tools to Record for accessing extended join columns
    const toolRows = agentTools as unknown as Array<Record<string, unknown>>;

    // --- Step 2: Write user prompt to SHORT_TERM memory ---
    const numericAgentId = agent.id ?? 0;
    try {
      await axios.post(`${config.MEMORY_SERVICE_URL}/v1/memory/write`, {
        agent_id: numericAgentId,
        tier: 'short_term',
        content: prompt,
        metadata: { type: 'user_query', timestamp: new Date().toISOString() },
      }, { headers: { 'x-request-id': tid }, timeout: 5000 });
      logger.info('Short-term memory write succeeded', 'router', { agent_id, trace_id: tid });
    } catch (memErr: unknown) {
      logger.error('Short-term memory write failed (non-blocking)', 'router', {
        error: (memErr as Error).message, agent_id, trace_id: tid,
      });
    }

    // --- Step 3: Assemble system prompt FROM memory tiers (with fallback) ---
    let sysPrompt = system_prompt || `You are ${agent.name}. ${agent.description || ''}`;
    let memoryHits = false;
    try {
      const assembleResp = await axios.post(`${config.MEMORY_SERVICE_URL}/v1/memory/assemble-prompt`, {
        agent_id: numericAgentId,
        context: {
          task_type: 'general',
          domain: 'general',
          recent_messages: [prompt],
        },
        tiers: ['short_term', 'long_term', 'reasoning', 'episodic'],
      }, { headers: { 'x-request-id': tid }, timeout: 8000 });

      const assembled = assembleResp.data;
      if (assembled.system_prompt && assembled.system_prompt.trim().length > 0) {
        sysPrompt = assembled.system_prompt;
        memoryHits = true;
        logger.info('Memory-assembled prompt used', 'router', {
          agent_id, trace_id: tid,
          sources: assembled.sources,
        });
      }
    } catch (assembleErr: unknown) {
      logger.error('Memory assemble-prompt failed, using fallback prompt', 'router', {
        error: (assembleErr as Error).message, agent_id, trace_id: tid,
      });
    }

    // --- Step 4: Append tool descriptions to the prompt ---
    if (toolRows.length > 0) {
      const toolList = toolRows.map((t) =>
        `- ${t.tool_name} (${t.tool_type}): ${t.tool_description || 'No description'}`
      ).join('\n');
      sysPrompt += `\n\nYou have access to the following tools:\n${toolList}\n\nUse the appropriate tool when the user's request requires data retrieval, computation, or external information. Always use tools when available rather than guessing answers.`;
    }

    const messages = [
      { role: 'system', content: sysPrompt },
      { role: 'user', content: prompt },
    ];

    // Build tool definitions for the orchestrator
    const toolDefs = toolRows.map((t) => {
      let toolConfig: Record<string, unknown> = {};
      const authConfig = t.tool_auth_config;
      if (authConfig && typeof authConfig === 'object') {
        toolConfig = { ...toolConfig, ...(authConfig as Record<string, unknown>) };
      }
      if (t.tool_endpoint) {
        const endpoint = t.tool_endpoint as string;
        if ((t.tool_type as string) === 'DATABASE') {
          toolConfig.connection_string = endpoint;
        } else if ((t.tool_type as string) === 'API') {
          toolConfig.base_url = endpoint;
        }
        toolConfig.endpoint = endpoint;
      }
      return {
        name: t.tool_name as string,
        description: (t.tool_description as string) || '',
        tool_type: t.tool_type as string,
        tool_id: t.tool_id as string,
        config: toolConfig,
      };
    });

    logger.info('Agent test initiated (with tools + memory)', 'router', {
      agent_id,
      agent_name: agent.name,
      model: model || agent.foundation_model,
      tool_count: toolDefs.length,
      memory_assembled: memoryHits,
      trace_id: tid,
    });

    // Map UI provider names to backend provider identifiers
    const providerMap: Record<string, string> = {
      OpenAI: 'openai', Anthropic: 'anthropic', Google: 'google', Ollama: 'ollama',
      openai: 'openai', anthropic: 'anthropic', google: 'google', ollama: 'ollama',
    };
    const resolvedProvider = providerMap[provider || 'OpenAI'] || 'openai';

    // --- Step 5: Call orchestrator agent-execute endpoint (tool-use loop) ---
    const orchestratorUrl = `${config.ORCHESTRATOR_URL}/v1/sandbox/agent-execute`;
    const payload: Record<string, unknown> = {
      messages,
      tools: toolDefs,
      tool_executor_url: `http://pmos-agent-mgmt:4001/v1/tools/test`,
      provider: resolvedProvider,
      model: model || agent.foundation_model,
      max_iterations: 5,
      max_continuations: 3,
    };
    if (temperature !== undefined) payload.temperature = temperature;
    if (max_tokens) payload.max_tokens = max_tokens;

    const response = await axios.post(orchestratorUrl, payload, {
      headers: { 'x-request-id': tid, 'content-type': 'application/json' },
      timeout: 120000,
    });

    const result = response.data;
    const latencyMs = result.latency_ms || (Date.now() - start);
    const responseText = result.response || '';
    const toolCallNames: string[] = Array.isArray(result.tool_calls)
      ? result.tool_calls.map((tc: Record<string, unknown>) => (tc.tool_name || tc.name || 'unknown') as string)
      : [];

    // --- Steps 6-8: Fire-and-forget post-execution memory writes + scoring ---
    let executionScore: number | null = null;

    // Step 8: Score the execution (awaited briefly so we can include score in response)
    try {
      const scoreResp = await axios.post(`${config.SCORING_SERVICE_URL}/v1/scoring/evaluate`, {
        agent_id: numericAgentId,
        task_id: tid,
        context_type: 'general',
        response_text: responseText,
        used_knowledge: memoryHits,
        latency_ms: latencyMs,
        tool_calls: toolCallNames,
      }, { headers: { 'x-request-id': tid }, timeout: 10000 });
      executionScore = scoreResp.data?.score ?? null;
      logger.info('Scoring evaluate succeeded', 'router', {
        agent_id, trace_id: tid, score: executionScore,
        recommendation: scoreResp.data?.recommendation,
      });
    } catch (scoreErr: unknown) {
      logger.error('Scoring evaluate failed (non-blocking)', 'router', {
        error: (scoreErr as Error).message, agent_id, trace_id: tid,
      });
    }

    // Step 6: Write execution result to LONG_TERM memory (fire-and-forget)
    axios.post(`${config.MEMORY_SERVICE_URL}/v1/memory/write`, {
      agent_id: numericAgentId,
      tier: 'long_term',
      content: `Q: ${prompt}\nA: ${responseText}\nTools used: ${toolCallNames.join(', ') || 'none'}\nScore: ${executionScore ?? 'N/A'}`,
      metadata: {
        task_type: 'general',
        tools_used: toolCallNames,
        score: executionScore,
      },
    }, { headers: { 'x-request-id': tid }, timeout: 5000 }).catch((err: Error) => {
      logger.error('Long-term memory write failed (fire-and-forget)', 'router', {
        error: err.message, agent_id, trace_id: tid,
      });
    });

    // Step 7: Write full episode to EPISODIC memory (fire-and-forget)
    axios.post(`${config.MEMORY_SERVICE_URL}/v1/memory/write`, {
      agent_id: numericAgentId,
      tier: 'episodic',
      content: JSON.stringify({
        task_description: prompt,
        steps_taken: result.tool_calls || [],
        final_output: responseText,
        score: executionScore,
        outcome: result.success ? 'success' : 'failure',
      }),
      metadata: {
        agent_name: agent.name,
      },
    }, { headers: { 'x-request-id': tid }, timeout: 5000 }).catch((err: Error) => {
      logger.error('Episodic memory write failed (fire-and-forget)', 'router', {
        error: err.message, agent_id, trace_id: tid,
      });
    });

    // --- Step 9: Record execution in history (with score) ---
    try {
      await agentHistoryService.recordExecution(agent_id, agent.name, {
        prompt,
        system_prompt: sysPrompt,
        response: responseText,
        model: result.model || model || agent.foundation_model,
        temperature: temperature,
        latency_ms: latencyMs,
        tokens_used: result.tokens_used || null,
        status: result.success ? 'success' : 'failure',
        error_message: result.error || null,
        tool_calls: result.tool_calls || null,
        trace_id: tid,
        source: 'manual',
        score: executionScore ?? undefined,
      });
    } catch (histErr: unknown) {
      logger.error('Failed to record agent execution history', 'router', {
        error: (histErr as Error).message,
        agent_id,
        trace_id: tid,
      });
    }

    // --- Step 10: Return result with score ---
    requestTotal.inc({ method: 'POST', path: '/v1/agents/:id/test', status: '200' });
    return res.json({
      ...result,
      agent_id,
      agent_name: agent.name,
      score: executionScore,
      memory_assembled: memoryHits,
      trace_id: tid,
    });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('Agent test failed', 'router', { error: error.message, agent_id, trace_id: tid });
    requestTotal.inc({ method: 'POST', path: '/v1/agents/:id/test', status: '500' });

    // Record failed execution
    try {
      const agent = await agentService.getAgent(agent_id);
      await agentHistoryService.recordExecution(agent_id, agent?.name || 'unknown', {
        prompt: req.body?.prompt || '',
        system_prompt: req.body?.system_prompt || '',
        response: '',
        model: req.body?.model || '',
        temperature: req.body?.temperature,
        latency_ms: Date.now() - start,
        tokens_used: null,
        status: 'failure',
        error_message: error.message,
        trace_id: tid,
        source: 'manual',
      });
    } catch {
      // Best effort
    }

    return errorResponse(res, 500, 'Agent test failed: ' + error.message, 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'POST', path: '/v1/agents/:id/test' }, (Date.now() - start) / 1000);
  }
});

// GET /v1/agents/:agent_id/executions — get execution history
router.get('/:agent_id/executions', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const agent_id = String(req.params.agent_id);
  try {
    const limit = parseInt(req.query['limit'] as string) || 50;
    const offset = parseInt(req.query['offset'] as string) || 0;
    const result = await agentHistoryService.getHistory(agent_id, limit, offset);
    requestTotal.inc({ method: 'GET', path: '/v1/agents/:id/executions', status: '200' });
    return res.json({ ...result, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('getAgentExecutions failed', 'router', { error: error.message, agent_id, trace_id: tid });
    requestTotal.inc({ method: 'GET', path: '/v1/agents/:id/executions', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'GET', path: '/v1/agents/:id/executions' }, (Date.now() - start) / 1000);
  }
});

// GET /v1/agents/:agent_id
router.get('/:agent_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const agent_id = String(req.params.agent_id);
  try {
    const agent = await agentService.getAgent(agent_id);
    if (!agent) {
      requestTotal.inc({ method: 'GET', path: '/v1/agents/:id', status: '404' });
      return errorResponse(res, 404, 'Agent not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'GET', path: '/v1/agents/:id', status: '200' });
    return res.json({ agent, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('getAgent failed', 'router', { error: error.message, agent_id, trace_id: tid });
    requestTotal.inc({ method: 'GET', path: '/v1/agents/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'GET', path: '/v1/agents/:id' }, (Date.now() - start) / 1000);
  }
});

// PUT /v1/agents/:agent_id
router.put('/:agent_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const agent_id = String(req.params.agent_id);
  try {
    const parsed = updateAgentSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'PUT', path: '/v1/agents/:id', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    const agent = await agentService.updateAgent(agent_id, parsed.data);
    if (!agent) {
      requestTotal.inc({ method: 'PUT', path: '/v1/agents/:id', status: '404' });
      return errorResponse(res, 404, 'Agent not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'PUT', path: '/v1/agents/:id', status: '200' });
    return res.json({ agent, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('updateAgent failed', 'router', { error: error.message, agent_id, trace_id: tid });
    requestTotal.inc({ method: 'PUT', path: '/v1/agents/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'PUT', path: '/v1/agents/:id' }, (Date.now() - start) / 1000);
  }
});

// DELETE /v1/agents/:agent_id
router.delete('/:agent_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const agent_id = String(req.params.agent_id);
  try {
    const deleted = await agentService.deleteAgent(agent_id);
    if (!deleted) {
      requestTotal.inc({ method: 'DELETE', path: '/v1/agents/:id', status: '404' });
      return errorResponse(res, 404, 'Agent not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'DELETE', path: '/v1/agents/:id', status: '200' });
    return res.json({ message: 'Agent deprecated', trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('deleteAgent failed', 'router', { error: error.message, agent_id, trace_id: tid });
    requestTotal.inc({ method: 'DELETE', path: '/v1/agents/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'DELETE', path: '/v1/agents/:id' }, (Date.now() - start) / 1000);
  }
});

// GET /v1/agents/:agent_id/tools
router.get('/:agent_id/tools', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const agent_id = String(req.params.agent_id);
  try {
    const tools = await agentService.listAgentTools(agent_id);
    requestTotal.inc({ method: 'GET', path: '/v1/agents/:id/tools', status: '200' });
    return res.json({ tools, count: tools.length, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('listAgentTools failed', 'router', { error: error.message, agent_id, trace_id: tid });
    requestTotal.inc({ method: 'GET', path: '/v1/agents/:id/tools', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'GET', path: '/v1/agents/:id/tools' }, (Date.now() - start) / 1000);
  }
});

// POST /v1/agents/:agent_id/tools
router.post('/:agent_id/tools', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const agent_id = String(req.params.agent_id);
  try {
    const parsed = assignToolSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'POST', path: '/v1/agents/:id/tools', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    await agentService.assignTool(agent_id, parsed.data);
    requestTotal.inc({ method: 'POST', path: '/v1/agents/:id/tools', status: '201' });
    return res.status(201).json({ message: 'Tool assigned', trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('assignTool failed', 'router', { error: error.message, agent_id, trace_id: tid });
    requestTotal.inc({ method: 'POST', path: '/v1/agents/:id/tools', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'POST', path: '/v1/agents/:id/tools' }, (Date.now() - start) / 1000);
  }
});

export default router;
