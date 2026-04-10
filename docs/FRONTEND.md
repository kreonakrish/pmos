# FRONTEND.md — React Client Reference

## Stack
React 18, Vite, TypeScript, Material UI 5, React Query, D3.js, React Router, Zustand

**Port:** 3000 (Vite dev server)
**Entry:** `client/src/App.tsx`
**Types:** `client/src/types/index.ts`
**API hooks:** `client/src/api/`

## Navigation & Pages

### Converse
| Route | Page | Purpose |
|-------|------|---------|
| `/conversations` | ConversationsPage | Main chat interface with sidebar |
| `/chat` | ChatPage | Alternate chat view |
| `/decomposition/:id` | TaskDecompositionPage | Force-directed graph of task breakdown |
| `/agent-interactions/:id` | AgentInteractionPage | D3 sequence diagram of agent comms |

### Build (Agent Studio)
| Route | Page | Purpose |
|-------|------|---------|
| `/tool-studio` | ToolStudioPage | Create/edit/test tools |
| `/agent-studio` | AgentStudioPage | Create/edit agents, assign tools |
| `/team-studio` | TeamStudioPage | Create teams, add agents |

### Monitor
| Route | Page | Purpose |
|-------|------|---------|
| `/jobs` | JobsPage | Pipeline execution history, task node details |
| `/graph` | GraphPage | Live D3 force graph of all TaskNodes |
| `/scoring` | ScoringPage | Score history, band evolution, RL weight convergence |
| `/memory` | MemoryPage | 4-tier memory explorer per agent |
| `/documents` | DocumentsPage | Upload, manage, re-index documents |

### System
| Route | Page | Purpose |
|-------|------|---------|
| `/settings` | SettingsPage | System configuration |

## Key Components

### Chat
- `ChatInput.tsx` — Text input + file attach button (paperclip icon). Accepts .pdf/.csv/.txt/.json/.xlsx/.docx/.md. Shows upload chip.
- `MessageBubble.tsx` — Renders user/agent messages with markdown
- `ConversationList.tsx` — Sidebar conversation list

### Agent Interaction
- `SequenceDiagram.tsx` — D3 sequence diagram. Participants ordered: User → Orchestrator → alphabetical agents. Arrows colored by type.
- `InteractionDetail.tsx` — Right panel showing selected interaction details (payloads, trace_id, duration)
- `InteractionFeed.tsx` — Scrollable + maximizable feed. Default 320px, maximizes to near-fullscreen. Filterable by agent/type.

### Graph
- `TaskGraphCanvas.tsx` — D3 force simulation. Nodes colored by status.
- `NodeDetailPanel.tsx` — Slide-in detail for selected nodes
- `GraphControls.tsx` — Filters: team, agent, graph_id, status, depth

### Scoring
- `BandEvolutionChart.tsx` — Area chart: band_high, band_low, score over time
- `WeightConvergenceChart.tsx` — Line chart of 6 RL weight factors
- `ScoreDistribution.tsx` — Histogram of score buckets
- `ScoreFeed.tsx` — Real-time scrollable feed

## API Hooks (client/src/api/)

| File | Key Hooks |
|------|-----------|
| `conversations.ts` | `useConversations`, `useSendMessage`, `useConversationMessages` |
| `agents.ts` | `useAgents`, `useCreateAgent`, `useUpdateAgent` |
| `tools.ts` | `useTools`, `useCreateTool`, `useTestTool` |
| `teams.ts` | `useTeams`, `useCreateTeam`, `useAddAgentToTeam` |
| `decomposition.ts` | `useTaskDecomposition`, `useAgentInteractions` |
| `graph.ts` | `useTaskGraph` |
| `jobs.ts` | `useJobs`, `useJobDetail` |
| `scoring.ts` | `useScoreHistory`, `useScoringWeights`, `useScoreBand` |
| `memory.ts` | `useMemoryEntries`, `useMemoryStats`, `useAssemblePrompt` |
| `documents.ts` | `useDocuments`, `useDeleteDocument`, `useReindexDocument` |

## Interaction Type Colors (Sequence Diagram)

| Type | Color | Visual |
|------|-------|--------|
| task_assignment | Blue | Solid arrow |
| tool_call | Green | Solid arrow |
| tool_result | Light green | Dashed arrow |
| score_evaluation | Orange | Solid arrow |
| course_correction | Dark orange | Solid arrow |
| memory_read/write | Purple | Solid/dashed |
| error | Red | Solid arrow |
| fallback | Light red | Dashed arrow |
| sub_agent_spawn | Deep orange | Solid arrow |
| sub_agent_result | Deep orange | Dashed arrow |

## Document Upload from Chat

Both Chat and Conversations pages support file upload:
1. User clicks paperclip icon → file picker
2. File content read as text → POST to `/v1/documents` as JSON
3. Gateway proxies to RAG service `/v1/rag/ingest`
4. RAG chunks + embeds → stores in Qdrant + MySQL
5. Next pipeline execution retrieves relevant chunks via RAG query
