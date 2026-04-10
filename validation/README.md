# PMOS Validation Suite

End-to-end validation of the Perpetual Multi-Agent Orchestration System.
Each suite runs sequentially and populates shared state so downstream suites
can reference entities created by earlier ones.

## Prerequisites

- Python 3.11+
- `httpx` (`pip install httpx`)
- `fpdf2` (optional, for PDF fixture generation: `pip install fpdf2`)
- All PMOS services running (see root `docker-compose.yml`)
- Backing stores online: MySQL, Redis, Neo4j (AuraDB), Qdrant

## Quick Start

```bash
cd pmos/validation

# Install dependencies
pip install httpx fpdf2

# Run everything
bash run_validation.sh
```

Or run individual suites:

```bash
python suites/00_health_check.py
python suites/01_tool_validation.py
python suites/02_agent_validation.py
python suites/03_team_validation.py
```

## Suite Overview

| Suite | File | What It Covers |
|-------|------|----------------|
| 00 | `00_health_check.py` | Health endpoints for all 7 services plus Neo4j, MySQL, Redis, and Qdrant connectivity checks. Aborts the run if any fail. |
| 01 | `01_tool_validation.py` | Creates 6 tool types (DATABASE, API, GITHUB, PYTHON, WEBSERVICE), tests CRUD, live API call, health field, and deletion with 404 verification. |
| 02 | `02_agent_validation.py` | Creates 3 agents (DataAnalyst, WebResearcher, ProjectOrchestrator), assigns tools, writes and reads all 4 memory tiers, tests prompt assembly, scoring evaluation, positive/negative feedback, and weight retrieval. |
| 03 | `03_team_validation.py` | Creates a team with orchestrator + specialist hierarchy, tests CRUD, priority updates, agent add/remove/re-add, and structural validation. |

## Configuration

Edit `config.py` to change service URLs or timeouts:

```python
GATEWAY_URL      = "http://localhost:4000"
ORCHESTRATOR_URL = "http://localhost:8000"
MEMORY_URL       = "http://localhost:8001"
RAG_URL          = "http://localhost:8002"
SCORING_URL      = "http://localhost:8003"
AGENT_MGMT_URL   = "http://localhost:4001"
META_ASSEMBLY_URL = "http://localhost:8004"

REQUEST_TIMEOUT  = 30   # seconds per HTTP call
POLL_TIMEOUT     = 60   # seconds for polling loops
POLL_INTERVAL    = 2    # seconds between poll attempts
```

## Shared State

Suites pass data forward via `utils.store()` / `utils.get()`.  State is also
persisted to `.validation_state.json` so suites can be re-run independently
after the earlier ones have populated it.

Key state entries:

| Key | Written By | Contains |
|-----|------------|----------|
| `tool_ids` | Suite 01 | List of created tool UUIDs |
| `tool_map` | Suite 01 | `{tool_name: tool_id}` dict |
| `agent_ids` | Suite 02 | List of created agent UUIDs |
| `agent_map` | Suite 02 | `{agent_name: agent_id}` dict |
| `team_id` | Suite 03 | Team UUID |

## Output Format

Each test prints a single line:

```
  [PASS]  test_name: description
  [FAIL]  test_name: description  -- error detail
  [SKIP]  test_name: description  -- reason
```

A summary is printed after each suite, and a final aggregate report at the end
of the full run.

## Fixtures

`fixtures_gen.py` generates three sample files in `fixtures/`:

- `sample_document.txt` -- PMOS architecture overview text
- `sample_document.csv` -- 20-row product dataset
- `sample_document.pdf` -- PDF version of the txt content (requires `fpdf2`)

Run fixture generation manually:

```bash
python fixtures_gen.py
```

## Adding New Suites

1. Create `suites/NN_name.py` (NN = two-digit number for ordering).
2. Import `config`, `utils`, and create a `ValidationReporter`.
3. Use `async_client()` for HTTP calls.
4. Use `store()` / `get()` for cross-suite state.
5. Call `rp.summary()` at the end.
6. The runner script auto-discovers files matching `suites/NN_*.py`.
