/**
 * PMOS Permission Registry — Gateway
 * ----------------------------------------------------------------------------
 * Central, auditable list mapping permission names to (route_pattern, method)
 * pairs. Every entry here is enforced at runtime by the rbac middleware so
 * that the server NEVER trusts the client.
 *
 * Conventions:
 *   - Permission names mirror the ones in infra/mysql/auth_schema.sql
 *     (e.g. 'agents.write', 'tools.delete').
 *   - We gate **mutating** routes (POST / PUT / PATCH / DELETE) by default.
 *     Read-only routes that show data the user is allowed to see can use a
 *     less-restrictive policy (see PERMISSION_REQUIREMENTS_READ).
 *   - This file is the single source of truth for "which permission gates
 *     which route" — keep it sorted by resource for grep-ability.
 *
 * NOTE: the auth/JWT identity flow itself is unchanged. We use the JWT's
 * `uid` claim only as a key into MySQL — the actual permission set comes
 * from `users → user_roles → role_permissions → permissions`.
 */

/** Single permission name (e.g. 'agents.write'). */
export type Perm = string;

export interface RouteRule {
  /**
   * Express path pattern, *relative to the /v1 mount* (because that is where
   * the rbac middleware is attached). Wildcards use Express `*` semantics.
   */
  path: string;
  /** HTTP methods to which this rule applies. Empty array = all methods. */
  methods: ReadonlyArray<'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'>;
  /** Required permission(s). User must hold AT LEAST ONE. */
  anyOf: ReadonlyArray<Perm>;
}

/**
 * Mutating routes. The middleware fails CLOSED for these (deny on DB error,
 * deny when user lacks permission).
 *
 * Order matters only for documentation; the middleware uses path-pattern
 * matching not order.
 */
export const PERMISSION_REQUIREMENTS_WRITE: ReadonlyArray<RouteRule> = [
  // ── Agents ────────────────────────────────────────────────────────────────
  { path: '/agents',                          methods: ['POST'],            anyOf: ['agents.write']  },
  { path: '/agents/:agentId',                 methods: ['PUT', 'PATCH'],    anyOf: ['agents.write']  },
  { path: '/agents/:agentId',                 methods: ['DELETE'],          anyOf: ['agents.delete'] },
  { path: '/agents/:agentId/tools',           methods: ['POST', 'PUT'],     anyOf: ['agents.write']  },
  { path: '/agents/:agentId/tools/:toolId',   methods: ['DELETE'],          anyOf: ['agents.write']  },
  { path: '/agents/:agentId/test',            methods: ['POST'],            anyOf: ['agents.write']  },

  // ── Tools ─────────────────────────────────────────────────────────────────
  { path: '/tools',                           methods: ['POST'],            anyOf: ['tools.write']   },
  { path: '/tools/:toolId',                   methods: ['PUT', 'PATCH'],    anyOf: ['tools.write']   },
  { path: '/tools/:toolId',                   methods: ['DELETE'],          anyOf: ['tools.delete']  },
  { path: '/tools/test',                      methods: ['POST'],            anyOf: ['tools.write']   },

  // ── Teams ─────────────────────────────────────────────────────────────────
  { path: '/teams',                           methods: ['POST'],            anyOf: ['teams.write']   },
  { path: '/teams/:teamId',                   methods: ['PUT', 'PATCH'],    anyOf: ['teams.write']   },
  { path: '/teams/:teamId',                   methods: ['DELETE'],          anyOf: ['teams.delete']  },
  { path: '/teams/:teamId/hierarchy',         methods: ['PUT'],             anyOf: ['teams.write']   },
  { path: '/teams/:teamId/agents',            methods: ['POST'],            anyOf: ['teams.write']   },
  { path: '/teams/:teamId/agents/:agentId',   methods: ['DELETE'],          anyOf: ['teams.write']   },

  // ── Conversations / chat / jobs ───────────────────────────────────────────
  { path: '/chat',                            methods: ['POST'],            anyOf: ['conversations.write'] },
  { path: '/conversations',                   methods: ['POST'],            anyOf: ['conversations.write'] },
  { path: '/conversations/:id',               methods: ['PATCH', 'PUT'],    anyOf: ['conversations.write'] },
  { path: '/conversations/:id',               methods: ['DELETE'],          anyOf: ['conversations.write'] },
  { path: '/conversations/:id/messages',      methods: ['POST'],            anyOf: ['conversations.write'] },
  { path: '/conversations/:id/feedback',      methods: ['POST'],            anyOf: ['conversations.write'] },
  { path: '/jobs/:graphId/resume',            methods: ['POST'],            anyOf: ['jobs.write']    },

  // ── Documents / RAG ───────────────────────────────────────────────────────
  { path: '/documents',                       methods: ['POST'],            anyOf: ['documents.write']  },
  { path: '/documents/upload',                methods: ['POST'],            anyOf: ['documents.write']  },
  { path: '/documents/:docId',                methods: ['DELETE'],          anyOf: ['documents.delete'] },
  { path: '/documents/:docId/reindex',        methods: ['POST'],            anyOf: ['documents.write']  },
  { path: '/rag/query',                       methods: ['POST'],            anyOf: ['documents.read']   },

  // ── Memory ────────────────────────────────────────────────────────────────
  { path: '/memory/write',                    methods: ['POST'],            anyOf: ['memory.write']  },
  { path: '/memory/assemble-prompt',          methods: ['POST'],            anyOf: ['memory.read']   },

  // ── Scoring / RL ──────────────────────────────────────────────────────────
  { path: '/scoring/evaluate',                methods: ['POST'],            anyOf: ['scoring.read']   },
  { path: '/scoring/band',                    methods: ['POST'],            anyOf: ['scoring.read']   },
  { path: '/scoring/feedback',                methods: ['POST'],            anyOf: ['scoring.write']  },

  // ── Translator ────────────────────────────────────────────────────────────
  { path: '/translate',                       methods: ['POST'],            anyOf: ['catalog.read']  },
  { path: '/translator/examples',             methods: ['POST'],            anyOf: ['catalog.write'] },

  // ── Data catalog ──────────────────────────────────────────────────────────
  { path: '/catalog/crawlers',                methods: ['POST'],            anyOf: ['catalog.write'] },
  { path: '/catalog/crawlers/:id/run',        methods: ['POST'],            anyOf: ['catalog.write'] },
  { path: '/catalog/mapping-decisions/:id/review', methods: ['POST'],       anyOf: ['catalog.write'] },

  // ── ML / governance write surfaces ────────────────────────────────────────
  { path: '/ml/sops/proposals/:id/promote',   methods: ['POST'],            anyOf: ['models.deploy'] },
  { path: '/ml/sops/proposals/:id/reject',    methods: ['POST'],            anyOf: ['models.write']  },

  // ── Users / roles ─────────────────────────────────────────────────────────
  // (already gated inline by requirePermission in routes/users.ts; listed
  // here so the registry is still the audit source of truth.)
  { path: '/users',                           methods: ['POST'],            anyOf: ['users.write']   },
  { path: '/users/:id',                       methods: ['PATCH', 'PUT'],    anyOf: ['users.write']   },
  { path: '/users/:id',                       methods: ['DELETE'],          anyOf: ['users.delete']  },
  { path: '/users/:id/reset-password',        methods: ['POST'],            anyOf: ['users.write']   },
  { path: '/users/:id/roles',                 methods: ['PUT'],             anyOf: ['roles.assign']  },
];

/**
 * Read-only routes. Most reads are not gated server-side because the user
 * has already been authenticated; the data they see is filtered by their
 * identity downstream (e.g. their conversations, their jobs).
 *
 * These are the few reads we *do* gate — pages that show admin-only data.
 * The middleware fails OPEN on DB outage for these so we stay observable.
 */
export const PERMISSION_REQUIREMENTS_READ: ReadonlyArray<RouteRule> = [
  // ── Catalog reads (frontend already gates with catalog.read) ──────────────
  { path: '/catalog/crawlers',                methods: ['GET'], anyOf: ['catalog.read'] },
  { path: '/catalog/crawlers/:id/runs',       methods: ['GET'], anyOf: ['catalog.read'] },
  { path: '/catalog/assets',                  methods: ['GET'], anyOf: ['catalog.read'] },
  { path: '/catalog/assets/:fqName',          methods: ['GET'], anyOf: ['catalog.read'] },
  { path: '/catalog/ontology',                methods: ['GET'], anyOf: ['catalog.read'] },
  { path: '/catalog/mapping-decisions',       methods: ['GET'], anyOf: ['catalog.read'] },
  { path: '/catalog/mapping-decisions/summary', methods: ['GET'], anyOf: ['catalog.read'] },

  // ── Governance / model traces (frontend gates with models.read) ───────────
  { path: '/governance/traces',               methods: ['GET'], anyOf: ['models.read', 'ml_insights.read'] },
  { path: '/governance/traces/:targetTraceId',methods: ['GET'], anyOf: ['models.read', 'ml_insights.read'] },
  { path: '/governance/traces/by-conversation/:cid', methods: ['GET'], anyOf: ['models.read', 'ml_insights.read'] },

  // ── Logs (frontend gates with logs.read) ──────────────────────────────────
  { path: '/logs/services',                   methods: ['GET'], anyOf: ['logs.read'] },
  { path: '/logs/tail',                       methods: ['GET'], anyOf: ['logs.read'] },

  // ── Memory entries (admin-ish view) ───────────────────────────────────────
  { path: '/memory/entries',                  methods: ['GET'], anyOf: ['memory.read'] },
  { path: '/memory/retrieve',                 methods: ['GET'], anyOf: ['memory.read'] },

  // ── ML insights ───────────────────────────────────────────────────────────
  { path: '/ml/bandits/summary',              methods: ['GET'], anyOf: ['ml_insights.read'] },
  { path: '/ml/bandits/state',                methods: ['GET'], anyOf: ['ml_insights.read'] },
  { path: '/ml/bandits/decisions',            methods: ['GET'], anyOf: ['ml_insights.read'] },
  { path: '/ml/bandits/convergence',          methods: ['GET'], anyOf: ['ml_insights.read'] },
  { path: '/ml/embeddings/summary',           methods: ['GET'], anyOf: ['ml_insights.read'] },
  { path: '/ml/embeddings/projection',        methods: ['GET'], anyOf: ['ml_insights.read'] },
  { path: '/ml/embeddings/similar',           methods: ['GET'], anyOf: ['ml_insights.read'] },
  { path: '/ml/learned-scorer/summary',       methods: ['GET'], anyOf: ['ml_insights.read'] },
  { path: '/ml/learned-scorer/predictions',   methods: ['GET'], anyOf: ['ml_insights.read'] },
  { path: '/ml/sops/proposals',               methods: ['GET'], anyOf: ['ml_insights.read'] },
];

/**
 * Routes intentionally LEFT OPEN (no permission required beyond auth):
 *   - /health, /metrics, /v1/auth/*  → public/auth flow itself
 *   - /v1/auth/me, /v1/auth/refresh, /v1/auth/change-password → user-self
 *   - GET /v1/agents, /v1/tools, /v1/teams, /v1/capabilities → already
 *       require auth; downstream agent-mgmt is the source-of-truth filter
 *   - GET /v1/conversations, /v1/conversations/:id, /v1/jobs, /v1/tasks
 *       → returns the *caller's* data; the orchestrator scopes by user_id
 *   - GET /v1/documents, /v1/rag/config → reading uploaded docs is a
 *       'documents.read' grant present in every default role; gating
 *       would just be noise.
 *   - GET /v1/scoring/weights/:agentId, /v1/scoring/history/:agentId →
 *       widely used as fallback scoring lookups; gating breaks unrelated
 *       agent flows.
 *
 * These omissions are intentional — re-add them only after a security
 * review. For documentation purposes:
 */
export const PERMISSION_REQUIREMENTS_OPEN: ReadonlyArray<string> = [
  '/health',
  '/metrics',
  '/v1/auth/login',
  '/v1/auth/refresh',
  '/v1/auth/me',
  '/v1/auth/change-password',
];

/** Helpful aggregate for tests / introspection. */
export const ALL_GATED_RULES: ReadonlyArray<RouteRule> = [
  ...PERMISSION_REQUIREMENTS_WRITE,
  ...PERMISSION_REQUIREMENTS_READ,
];
