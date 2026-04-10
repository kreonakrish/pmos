# PMOS Scoring Service

6-factor weighted scoring engine with adaptive bands and reinforcement-learning weight updates for the Perpetual Multi-Agent Orchestration System.

## Purpose

The scoring service computes a composite quality score for every agent execution result using six weighted factors. Scoring bands adapt over time based on rolling history, and an RL engine continuously tunes per-agent weight vectors based on feedback signals from four sources (automated, user, inter-agent, orchestrator).

### Score Formula

```
S = w1*Relevance + w2*Accuracy + w3*ToolSuccess + w4*LatencyPenalty + w5*MemoryUtilization + w6*ValidationPass
```

All weights are loaded from MySQL (`scoring_weights` table) and never hardcoded.

### Adaptive Bands

```
band_width = std(last_N_scores) * sensitivity_factor
band_low   = max(0.0, mean - band_width)
band_high  = min(1.0, mean + band_width)
```

Minimum band width is enforced via configuration.

### RL Weight Updates

```
effective_reward = reward_signal * source_weight
w_new = w_old + learning_rate * (effective_reward - w_old)
```

The RL engine runs as a background consumer of the `scoring:feedback` Redis stream.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/scoring/evaluate` | Compute score for a single execution result |
| `POST` | `/v1/scoring/band` | Return current adaptive band for agent + context_type |
| `POST` | `/v1/scoring/feedback` | Accept feedback signal, enqueue RL update |
| `GET` | `/v1/scoring/weights/{agent_id}` | Return current weight vector for an agent |
| `GET` | `/health` | Liveness check with MySQL + Redis connectivity status |
| `GET` | `/metrics` | Prometheus metrics exposition |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCORING_PORT` | `8003` | Service listen port |
| `MYSQL_HOST` | `localhost` | MySQL host |
| `MYSQL_PORT` | `3306` | MySQL port |
| `MYSQL_DB` | `pmos` | MySQL database name |
| `MYSQL_USER` | `root` | MySQL username |
| `MYSQL_PASSWORD` | *(required)* | MySQL password |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `SCORING_HISTORY_WINDOW` | `50` | Number of recent scores for band computation |
| `BAND_SENSITIVITY_FACTOR` | `1.0` | Multiplier for band width from std |
| `BAND_MIN_WIDTH` | `0.05` | Minimum enforced band width |
| `RL_LEARNING_RATE` | `0.1` | Q-learning alpha parameter |
| `RL_FEEDBACK_WEIGHTS` | `{"automated":0.4,"user":0.3,"inter_agent":0.2,"orchestrator":0.1}` | JSON source weight map |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `RETRY_MAX_ATTEMPTS` | `3` | Outbound call retry limit |
| `RETRY_WAIT_MULTIPLIER` | `1.0` | Exponential backoff multiplier |
| `RETRY_WAIT_MAX_SEC` | `10.0` | Max wait between retries |
| `CB_TIMEOUT_SEC` | `30.0` | Circuit breaker half-open timeout |

## Running

```bash
# With Docker
docker build -t pmos-scoring .
docker run -p 8003:8003 --env-file .env pmos-scoring

# Local development
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=app --cov-report=term-missing

# Run only unit tests
pytest tests/unit/ -v

# Run only integration tests
pytest tests/integration/ -v
```
