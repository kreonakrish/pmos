# PMOS — Deployment Guide

End-to-end instructions for installing PMOS on a fresh server (Linux, macOS,
or Windows with Git Bash). All commands assume you are inside the `pmos/`
directory unless stated otherwise.

---

## 1. Prerequisites

Install these on the target server before you start:

| Requirement       | Version | Notes                                                                      |
|-------------------|---------|----------------------------------------------------------------------------|
| Docker Engine     | 24+     | With the `docker compose` v2 plugin. Docker Desktop on macOS/Windows.      |
| Node.js           | 20+     | Needed for the React client (`npm`, `npx`).                                |
| MySQL             | 8.0+    | Reachable from the host that runs Docker. Local install or remote server.  |
| Neo4j             | 5.x     | Self-hosted (`bolt://`) or AuraDB Cloud (`neo4j+s://`).                    |
| `bash`, `curl`, `git` | any | Plus `lsof` or `fuser` (Linux/macOS) for client port cleanup.              |
| `mysql` CLI       | 8.0+    | Optional but recommended (used by `bootstrap.sh` to load the schema).      |
| `cypher-shell`    | latest  | Optional — falls back to the Python `neo4j` driver automatically.          |

**Network ports** that must be free on the host (override any in `.env`):
`3000` (client), `4000` (gateway), `4001` (agent-mgmt), `8000–8004` (Python services), `6379` (Redis), `6333/6334` (Qdrant).

---

## 2. Get the code

```bash
git clone <your-fork-or-repo-url> multiagentic_system
cd multiagentic_system/pmos
```

---

## 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in **every** required value. Nothing is hardcoded in the
source — if a value is missing here, the matching service will fail loudly.

### Required keys

| Key                                | What to put                                                            |
|------------------------------------|-------------------------------------------------------------------------|
| `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`) | LLM provider key matching `LLM_PROVIDER`. |
| `NEO4J_URI`                        | `neo4j+s://<host>` (AuraDB) or `bolt://<host>:7687` (self-hosted).      |
| `NEO4J_USER`, `NEO4J_PASSWORD`     | Neo4j credentials.                                                      |
| `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB` | MySQL connection. |
| `JWT_SECRET`                       | Generate fresh: `openssl rand -hex 64`.                                 |
| `AUTH_PASSWORD`                    | Gateway login password (no default — must be set).                      |

### Recommended overrides for non-localhost deployments

| Key                   | When to change                                                            |
|-----------------------|----------------------------------------------------------------------------|
| `*_PORT`              | If a port collides with something else on the host.                       |
| `REACT_APP_API_BASE_URL`, `REACT_APP_WS_URL` | Public URL of the gateway when the client is served from a different host. |
| `ORCHESTRATOR_URL`, `MEMORY_SERVICE_URL`, etc. | Inside docker-compose these resolve to container names; only override if you split services across hosts. |

> ⚠️ **Never commit `.env`.** It is in `.gitignore`. Treat the file as a secret.

---

## 4. One-shot install

From `pmos/`:

```bash
./scripts/deploy.sh install
```

This will:

1. Validate `.env` (fails loudly if anything required is missing).
2. Check Docker, `docker compose`, Node, MySQL connectivity.
3. Start Redis + Qdrant containers (`pmos_redis`, `pmos_qdrant`).
4. Run `scripts/bootstrap.sh` — creates the MySQL schema, applies Neo4j
   constraints, initializes Redis stream consumer groups.
5. Build and start the 7 backend services via `docker compose`.
6. Install client deps (if needed) and start the Vite dev server on
   `CLIENT_PORT` (default `3000`).
7. Print a health summary.

When it finishes, open `http://<server>:3000`.

---

## 5. Day-to-day operations

All commands use the same script, so the same workflow works on every server.

```bash
./scripts/deploy.sh up                          # start everything
./scripts/deploy.sh up orchestrator scoring     # start only specific components
./scripts/deploy.sh down                        # stop everything
./scripts/deploy.sh down gateway                # stop just one
./scripts/deploy.sh restart rag                 # restart one component
./scripts/deploy.sh status                      # containers + health
./scripts/deploy.sh health                      # health endpoints only
./scripts/deploy.sh logs orchestrator           # tail one component's logs
./scripts/deploy.sh validate                    # run the validation suite
```

**Components** accepted by `up` / `down` / `restart`:
`backing`, `gateway`, `agent-mgmt`, `orchestrator`, `memory`, `rag`,
`scoring`, `meta-assembly`, `client` (production nginx container),
`client-dev` (Vite hot-reload dev server on the host — local development only).

### Frontend modes

| Mode | Component | When to use | How |
|---|---|---|---|
| Production | `client` | All deployments (staging, prod, even local smoke tests). | Built by Vite, served by nginx in a container. nginx proxies `/v1` and `/health` to `gateway:4000` over the compose network, so the browser only sees one origin. |
| Dev | `client-dev` | Active local frontend development with hot reload. | Vite dev server runs on the host. `./scripts/deploy.sh up client-dev` |

The container reads `PMOS_API_BASE_URL`, `PMOS_WS_BASE_URL`, `PMOS_ENV` at
**container start** (not build time) and writes them to `/config.js`, which the
React app loads before its main bundle. So the same image runs in any
environment — no rebuild needed when promoting from staging to prod.

Leave `PMOS_API_BASE_URL` and `PMOS_WS_BASE_URL` empty if the client and
gateway are served from the same hostname (the typical case behind a single
TLS-terminating reverse proxy). Set them to absolute URLs only if the SPA is
served from a different origin (e.g. a CDN) than the API.

---

## 6. Validation

Run after install or after any deploy to confirm the system is healthy:

```bash
./scripts/deploy.sh validate
```

The suite is env-driven. To run it against a remote deployment:

```bash
PMOS_GATEWAY_URL=https://api.example.com \
PMOS_ORCHESTRATOR_URL=https://orchestrator.example.com \
... \
./scripts/deploy.sh validate
```

Override any of: `PMOS_GATEWAY_URL`, `PMOS_ORCHESTRATOR_URL`,
`PMOS_MEMORY_URL`, `PMOS_RAG_URL`, `PMOS_SCORING_URL`,
`PMOS_AGENT_MGMT_URL`, `PMOS_META_ASSEMBLY_URL`,
`PMOS_REQUEST_TIMEOUT`, `PMOS_POLL_TIMEOUT`, `PMOS_POLL_INTERVAL`.

---

## 7. Production hardening checklist

Before exposing PMOS to the public internet:

- [ ] Rotate `JWT_SECRET`, `AUTH_PASSWORD`, all DB passwords, and any LLM keys
      that may have been used elsewhere.
- [ ] Put the gateway behind TLS (nginx / Caddy / cloud LB). Update
      `REACT_APP_API_BASE_URL` and `REACT_APP_WS_URL` to the public URL.
- [ ] The `client` service already builds the SPA and serves it via nginx in
      a container — you do **not** need to run Vite manually. Put a TLS-
      terminating reverse proxy (nginx, Caddy, ALB, Cloud Run) in front of the
      `pmos-client` container on port 80.
- [ ] Restrict MySQL / Redis / Qdrant ports so they are not publicly reachable.
- [ ] Set `LOG_LEVEL=INFO` (or `WARN`) and ship logs to your aggregator.
- [ ] Configure backups for MySQL and Neo4j.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Configuration validation failed: AUTH_PASSWORD ...` | Missing in `.env`. | Set `AUTH_PASSWORD` in `.env`. |
| Orchestrator/meta-assembly fails to start, Neo4j errors | `NEO4J_URI` / `NEO4J_PASSWORD` missing or wrong. | Verify connectivity with `cypher-shell` or the Neo4j browser. |
| `bootstrap.sh` fails on MySQL step | `mysql` client not on `PATH`, or wrong creds. | Install the MySQL client; confirm `MYSQL_*` values. |
| RAG service `[DOWN]` at first boot | First-time embedding model download is slow. | Wait ~60s, re-run `./scripts/deploy.sh health`. |
| Client port already in use | Another process on `CLIENT_PORT`. | Set `CLIENT_PORT=<free-port>` in `.env`. |
| Windows: `lsof` not found warnings | Expected on Git Bash. | Harmless — script falls back to PID file. |

For deeper details see [SERVICES.md](SERVICES.md), [DATA.md](DATA.md), and
[ARCHITECTURE.md](ARCHITECTURE.md).
