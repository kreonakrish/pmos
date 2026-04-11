# DATA_CATALOG.md — Phase 1 Metadata Crawler Reference

> The "Data Sources" sidebar section and its `/data-catalog` page, the
> crawler framework behind it, and the auditor review loop that makes
> semantic mapping progressively more accurate over time.
>
> Added in branch `feat/systems-integration`.

## Purpose

Build a business ontology knowledge graph in Neo4j that sits *above* the
scattered physical databases the enterprise owns, so that when a user asks a
question like "which correspondent lenders originated the loans currently in
foreclosure, and what's our total distressed UPB by investor," the agent:

1. Resolves each business term (`loan`, `foreclosure`, `lender`, `investor`,
   `UPB`) to physical columns across N source systems using the knowledge graph.
2. Walks the graph to find join paths.
3. Issues precise SQL (or Cypher, or Glue API calls) to each authoritative
   source and stitches the results.

That is the path to **deterministic answers from federated systems.** Phase 1
ships the crawler + mapper + auditor loop; agent-side semantic lookup (the
`SEMANTIC_LOOKUP` tool) is Phase 3.

## Quick Start

Seed a crawler, run it, review the mappings:

```bash
# 1. Schema + first crawler (MySQL → pmos_servicing)
mysql -u root -p < infra/mysql/catalog.sql
mysql -u root -p < infra/mysql/catalog_seed.sql

# 2. Kick off the crawl via the gateway
curl -X POST -H "Authorization: Bearer <jwt>" \
  http://localhost:4000/v1/catalog/crawlers/<crawler_id>/run

# 3. Review in the UI
open http://localhost:3000/data-catalog
```

In the UI, the sidebar has a new **Data Sources → Data Catalog** entry with
four tabs: Crawlers, Assets, Business Ontology, Mapping Review.

## Ontology in Neo4j

The knowledge graph is built with five node labels and a handful of
relationships. This shape was chosen to stay stable as we add more source
types (Snowflake, SQL Server, Oracle, Glue, S3, Excel, SSRS) without
rewriting the ontology.

```
(:DataSource {source_name, source_type, source_uri})
  -[:HAS_ASSET]-> (:DataAsset {fq_name, fully_qualified, asset_type,
                               schema_name, asset_name, row_count, comment})
    -[:HAS_COLUMN]-> (:DataColumn {fq_name, name, data_type, nullable,
                                   is_pk, is_fk, fk_references,
                                   ordinal, sample_values, comment})

(:BusinessDomain {name})
  -[:HAS_ENTITY]-> (:BusinessEntity {name, domain})
    -[:HAS_ATTRIBUTE]-> (:BusinessAttribute {fq_name, name, entity, domain})
      -[:MAPS_TO {confidence, status, model_version, reasoning,
                  reviewed_by, reviewed_at}]-> (:DataColumn)

(:DataColumn)-[:REFERENCES]->(:DataColumn)        -- physical FK
(:DataAsset)-[:RELATED_TO {via}]->(:DataAsset)    -- derived from FK
```

The `status` property on the `MAPS_TO` edge transitions:
`AUTO_ACCEPTED → CONFIRMED | CORRECTED | REJECTED` as the auditor reviews.

## MySQL schema (registry + audit)

Three tables in the existing `pmos` database, defined in
`infra/mysql/catalog.sql`:

| Table | Purpose |
|---|---|
| `crawlers` | One row per crawler instance. `connection` JSON holds source-specific config, `options` JSON holds crawler-specific flags. |
| `crawl_runs` | One row per execution with status, counts, duration, errors, stats JSON. |
| `semantic_mapping_decisions` | **The audit trail.** Every LLM-proposed column mapping, with proposed domain/entity/attribute, confidence, reasoning, model version, and reviewer fields. The review endpoint fills in `auditor_*`, `reviewed_by`, `reviewed_at`, and `reward_signal`. |

Reward signal values written by the review endpoint:
- `CONFIRM` → **+1.0**
- `CORRECT` → **−0.5**
- `REJECT` → **−1.0**

These are the reinforcement signal that future mapper training runs (or
fine-tuning / few-shot) will consume.

## Crawler framework

Code lives in `services/orchestrator/app/services/crawler/`:

```
base.py            — BaseCrawler ABC, CrawledAsset / CrawledColumn / CrawlResult dataclasses
mysql_crawler.py   — MySQL implementation (INFORMATION_SCHEMA based)
semantic_mapper.py — LLM-powered mapper, one call per table, JSON output
catalog_writer.py  — Merges DataSource/Asset/Column/Domain/Entity/Attribute into Neo4j + audit rows into MySQL
runner.py          — async entry point used by the /run HTTP route
__init__.py        — exports
```

### Adding a new source type

1. Create `services/orchestrator/app/services/crawler/<type>_crawler.py`
   subclassing `BaseCrawler`. Implement `discover()` — must return a
   `CrawlResult` with populated `assets` and `columns`.
2. Register the class in `runner.py` → `CRAWLER_CLASSES` dict:
   `"SNOWFLAKE": SnowflakeCrawler`.
3. Add the new type to the ENUM in `infra/mysql/catalog.sql` (or alter the
   table to accept it).
4. Insert a row in `crawlers` with the right config.
5. Trigger it via the existing `/v1/catalog/crawlers/{id}/run` endpoint.

**No other changes required.** The semantic mapper, catalog writer, audit
loop, and UI all work unchanged for any source type because they operate on
the shared `CrawledAsset` shape.

### Conventions for new crawlers

- `discover()` is sync. The runner wraps it in `asyncio.to_thread` so it
  does not block the FastAPI loop.
- Never raise on partial failures — append to `result.errors` instead and
  keep going. The runner will mark the overall status `PARTIAL`.
- Sample values are optional but strongly recommended — they massively
  improve LLM mapping quality. Skip for sensitive columns (the MySQL
  crawler uses the `SENSITIVE_PATTERNS` regex).

## Semantic mapper (LLM)

One LLM call per table (not per column — 40× cheaper). The prompt in
`semantic_mapper.py` shows the LLM:

- Table name and optional comment
- Each column's name, data type, flags (PK / FK target / NOT NULL),
  up to 3 sample values, column comment

and asks for a single JSON object:

```json
{
  "domain": "Servicing",
  "entity": "Loan",
  "columns": [
    {
      "column": "current_balance",
      "attribute": "current_balance",
      "confidence": 0.95,
      "reasoning": "decimal column on loans table — unpaid principal"
    },
    ...
  ]
}
```

The response parser validates that every `column` field matches a real
column name; hallucinated columns are discarded. Any real columns the LLM
misses get a low-confidence heuristic fallback mapping so the auditor sees
them in the review queue.

If the LLM call fails entirely, the mapper falls back to a heuristic
table-name-based guesser (confidence 0.35) so crawls always produce *some*
output for the auditor — no silent gaps.

## Auditor review loop (the RL feedback surface)

The Mapping Review tab is the human-in-the-loop layer. Every decision can be:

- **Confirmed** — green check, reward `+1.0`. Nothing changes in Neo4j; the
  AUTO_ACCEPTED mapping stands.
- **Corrected** — yellow edit dialog, reward `−0.5`. The auditor supplies a
  new domain/entity/attribute. The review endpoint:
  1. Updates the MySQL row with the auditor's choice + reward.
  2. MERGEs the corrected `BusinessEntity` and `BusinessAttribute` in Neo4j.
  3. MERGEs a new `MAPS_TO` edge from the corrected attribute to the same
     `DataColumn`, confidence 1.0, status CORRECTED, `reviewed_by` recorded.
- **Rejected** — red X, reward `−1.0`. MySQL row flagged; no Neo4j change
  (the original mapping remains but is marked rejected so consuming code can
  filter it out).

Filter chips at the top of the tab let the auditor focus on
`AUTO_ACCEPTED` (the queue), `CONFIRMED`, `CORRECTED`, `REJECTED`, or all.
Decisions are sorted by status (pending first), then by ascending confidence
(most uncertain first) so the auditor's time goes to the rows most likely to
need correction.

## HTTP API

All under `/v1/catalog/*`, proxied through the gateway with JWT auth.

| Method | Path | Purpose |
|---|---|---|
| GET | `/crawlers` | List registered crawlers |
| POST | `/crawlers` | Create a new crawler (name + source_type + connection + options) |
| POST | `/crawlers/{id}/run` | Trigger a crawl as a FastAPI BackgroundTask |
| GET | `/crawlers/{id}/runs` | Run history for a crawler |
| GET | `/assets` | List crawled DataAssets (optional `source_name` filter) |
| GET | `/assets/{fq_name}` | Asset detail with columns and their business mappings |
| GET | `/ontology` | BusinessDomains → BusinessEntities tree with attribute counts |
| GET | `/mapping-decisions` | Audit log, filterable by `status`, `run_id` |
| GET | `/mapping-decisions/summary` | Aggregate counts + review coverage |
| POST | `/mapping-decisions/{id}/review` | Auditor action: `CONFIRM` / `CORRECT` / `REJECT` |

## Frontend

`client/src/pages/DataCatalog/index.tsx` — single page, four tabs:

| Tab | What it shows |
|---|---|
| **Crawlers** | Registry list, per-crawler Run button, run history table |
| **Assets** | Crawled DataAssets with column detail + business mappings and confidence chips |
| **Business Ontology** | Domain → Entity cards with attribute counts |
| **Mapping Review** | Auditor workflow: summary cards, status filter, decision rows with CONFIRM/CORRECT/REJECT icons, correction dialog |

`client/src/api/catalog.ts` — react-query hooks: `useCrawlers`, `useCrawlRuns`,
`useRunCrawler`, `useCatalogAssets`, `useCatalogAssetDetail`, `useOntology`,
`useMappingDecisions`, `useMappingDecisionsSummary`, `useReviewMapping`.

Sidebar entry: new **Data Sources** section with the Data Catalog nav item.

## Known limits and deferred work

- **One source type today** — only `MYSQL` is implemented. The framework is
  ready for the other ten source types on the roadmap (Snowflake, SQL
  Server, Oracle, Teradata, Glue, S3, Postgres, Excel, CSV, SSRS RDL).
- **Entity resolution across sources** — when two sources both have a
  "Customer" table, we create two `BusinessEntity` nodes. Phase 2 adds a
  merge step based on cosine similarity of entity names and attribute
  overlap.
- **Agent integration** — no `SEMANTIC_LOOKUP` tool yet. Phase 3. Until
  then, the knowledge graph is a passive diagnostic surface, not a live
  query planner.
- **Freshness** — crawls are fully manual via the Run button today.
  Scheduled refresh via cron/k8s CronJob is pending the same deployment
  call as the ML scripts.
- **Sample values leak** — sample values are stored on `DataColumn` nodes
  in Neo4j for LLM convenience. This is fine for development but in
  production the graph becomes a data-governance surface and sample values
  for PII columns should be redacted or gated.
- **Review backpressure** — in full automation mode there is no alert when
  the review queue grows past a threshold. Add a metric + dashboard row
  when the first real source is crawled at scale.

## Key files

### Backend
- `services/orchestrator/app/routes/catalog.py` — HTTP endpoints
- `services/orchestrator/app/services/crawler/base.py` — ABC + dataclasses
- `services/orchestrator/app/services/crawler/mysql_crawler.py` — MySQL impl
- `services/orchestrator/app/services/crawler/semantic_mapper.py` — LLM mapping
- `services/orchestrator/app/services/crawler/catalog_writer.py` — Neo4j + audit writer
- `services/orchestrator/app/services/crawler/runner.py` — async entry point
- `services/orchestrator/app/main.py` — router registration
- `services/gateway/app/routes/orchestrator.ts` — `/v1/catalog/*` proxy routes

### Frontend
- `client/src/pages/DataCatalog/index.tsx` — page with all 4 tabs
- `client/src/api/catalog.ts` — react-query hooks
- `client/src/components/Layout/Sidebar.tsx` — Data Sources section
- `client/src/App.tsx` — `/data-catalog` route

### Schema + seed
- `infra/mysql/catalog.sql` — `crawlers`, `crawl_runs`, `semantic_mapping_decisions`
- `infra/mysql/catalog_seed.sql` — first MySQL → pmos_servicing crawler row

## Verification from first real run (Phase 1 smoke test)

Running the seeded `MySQL → pmos_servicing` crawler end-to-end produced:

- 9 `DataAsset` nodes (`bankruptcies`, `defaults`, `early_resolutions`,
  `foreclosures`, `investors`, `loans`, `payments`, `reds_filings`,
  `risk_assessments`)
- 63 `DataColumn` nodes
- 1 `BusinessDomain` (`Servicing`)
- 9 canonical `BusinessEntity` nodes (`Loan`, `Payment`, `Investor`,
  `Default`, `Bankruptcy`, `Foreclosure`, `EarlyResolution`,
  `RiskAssessment`, `RegulatoryFiling`)
- 63 `BusinessAttribute` nodes + `MAPS_TO` edges, all `AUTO_ACCEPTED`
- Average LLM confidence: **0.957**, zero low-confidence mappings
- Review round-trip verified: `CONFIRM` produced `reward_signal=+1.0`,
  `CORRECT` produced `−0.5`, summary stats updated, Neo4j updated with the
  corrected `BusinessAttribute`
- End-to-end duration: ~44 seconds (9 tables × 1 LLM call each)

Notable enrichments the LLM added without being asked:
- `term_months` → `Loan.loan_term_months` (added entity prefix for clarity)
- `origination_ref` → `Loan.origination_reference` (expanded abbreviation)
- `status` → `Loan.loan_status` (disambiguated from generic `status`)

That is the behavior we want from the mapper: not a dumb column-name copy,
but genuine semantic enrichment.
