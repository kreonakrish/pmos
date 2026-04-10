# PMOS Client

React frontend for the Perpetual Multi-Agent Orchestration System.

## Stack

- React 18 + TypeScript
- Vite (dev server + build)
- Material UI v5 (dark + light themes)
- TanStack React Query v5 (server state)
- Zustand (client state)
- React Router v6 (routing)
- Socket.io-client (WebSocket streaming)
- Axios (HTTP client)
- Recharts (charts)
- D3.js (graph visualization)

## Pages

| Route | Page | Description |
|-------|------|-------------|
| `/chat` | Chat | Conversation interface with streaming |
| `/graph` | Graph | Living task execution graph (D3) |
| `/agents` | Agents | Agent management grid + detail drawer |
| `/scoring` | Scoring | Adaptive scoring dashboard |
| `/tools` | Tools | Tool and capability management |
| `/memory` | Memory | 4-tier memory browser |
| `/settings` | Settings | System configuration |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_BASE_URL` | `http://localhost:4000` | Gateway API base URL |
| `VITE_WS_URL` | `http://localhost:4000` | WebSocket server URL |

## Development

```bash
# Install dependencies
npm install

# Start dev server on port 3000
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Docker

```bash
# Build image
docker build -t pmos-client .

# Run container
docker run -p 3000:3000 pmos-client
```

The Docker image uses a multi-stage build: Node.js for building, nginx for serving.
The nginx config proxies `/v1` and `/health` requests to the gateway service.

## Project Structure

```
src/
  api/          React Query hooks + axios client
  components/
    Layout/     Sidebar, TopBar, HealthBar
    common/     SkeletonLoader, ErrorCard, EmptyState
    Chat/       Chat-specific components
    Agents/     Agent cards, detail drawer
    Scoring/    Charts and stat cards
    Graph/      D3 task graph canvas
  pages/        Route-level page components
  store/        Zustand stores (conversation, ws, ui)
  theme/        MUI dark + light theme definitions
  types/        Shared TypeScript interfaces
  ws/           Socket.io client setup
```
