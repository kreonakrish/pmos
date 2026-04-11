"""MySQL metadata crawler.

Uses INFORMATION_SCHEMA to enumerate tables, views, columns, primary keys,
and foreign keys across one or more schemas in a single MySQL instance.
Optionally pulls up to `sample_rows` non-null sample values per column by
issuing a single `SELECT DISTINCT ... LIMIT N` per column — cheap for
narrow tables, skipped for columns that look sensitive (ssn, password,
secret, token).

config shape (stored in crawlers.connection / crawlers.options):

    {
      "connection": {
        "host": "host.docker.internal",
        "port": 3306,
        "user": "root",
        "password": "...",         # optional; falls back to MYSQL_PASSWORD env
        "database": "pmos_servicing",
        "schemas": ["pmos_servicing"]  # one or many
      },
      "options": {
        "include_views": true,
        "sample_rows": 3,
        "skip_sensitive": true
      }
    }
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import mysql.connector

from app.services.crawler.base import (
    BaseCrawler,
    CrawledAsset,
    CrawledColumn,
    CrawlResult,
)

logger = logging.getLogger("pmos.crawler.mysql")

SENSITIVE_PATTERNS = re.compile(
    r"(ssn|password|secret|token|api_?key|credit_?card|card_?num|cvv|pin|hash)",
    re.IGNORECASE,
)


class MySQLCrawler(BaseCrawler):
    source_type = "MYSQL"

    def _connect(self):
        conn_cfg = dict(self.connection)
        # Password resolution: explicit > env fallback
        password = conn_cfg.get("password") or os.environ.get("MYSQL_PASSWORD", "")
        return mysql.connector.connect(
            host=conn_cfg.get("host", "localhost"),
            port=int(conn_cfg.get("port", 3306)),
            user=conn_cfg.get("user", "root"),
            password=password,
            database=conn_cfg.get("database") or (conn_cfg.get("schemas") or [None])[0],
            connection_timeout=10,
        )

    def discover(self) -> CrawlResult:
        schemas: List[str] = self.connection.get("schemas") or []
        if not schemas:
            db = self.connection.get("database")
            schemas = [db] if db else []
        if not schemas:
            return CrawlResult(
                source_name="mysql_unknown",
                source_type=self.source_type,
                source_uri="mysql://unknown",
                errors=["No schemas or database configured"],
            )

        host = self.connection.get("host", "localhost")
        port = int(self.connection.get("port", 3306))
        source_uri = f"mysql://{host}:{port}/{','.join(schemas)}"
        source_name = self._source_name_from(
            self.source_type, f"{host}_{port}", schemas[0],
        )

        include_views = bool(self.options.get("include_views", True))
        sample_rows = int(self.options.get("sample_rows", 3))
        skip_sensitive = bool(self.options.get("skip_sensitive", True))

        result = CrawlResult(
            source_name=source_name,
            source_type=self.source_type,
            source_uri=source_uri,
        )

        conn = self._connect()
        try:
            cur = conn.cursor(dictionary=True)

            # 1. Discover tables/views for each schema
            placeholders = ",".join(["%s"] * len(schemas))
            type_clause = "('BASE TABLE','VIEW')" if include_views else "('BASE TABLE')"
            cur.execute(
                f"""
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, TABLE_COMMENT, TABLE_ROWS
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA IN ({placeholders})
                  AND TABLE_TYPE IN {type_clause}
                ORDER BY TABLE_SCHEMA, TABLE_NAME
                """,
                tuple(schemas),
            )
            table_rows = cur.fetchall() or []
            logger.info("Found %d tables/views across %d schemas", len(table_rows), len(schemas))

            # 2. Discover all columns in one query
            cur.execute(
                f"""
                SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION,
                       DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY,
                       COLUMN_DEFAULT, COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA IN ({placeholders})
                ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
                """,
                tuple(schemas),
            )
            col_rows = cur.fetchall() or []

            # 3. FK metadata
            cur.execute(
                f"""
                SELECT kcu.TABLE_SCHEMA, kcu.TABLE_NAME, kcu.COLUMN_NAME,
                       kcu.REFERENCED_TABLE_SCHEMA, kcu.REFERENCED_TABLE_NAME,
                       kcu.REFERENCED_COLUMN_NAME
                FROM information_schema.KEY_COLUMN_USAGE kcu
                WHERE kcu.TABLE_SCHEMA IN ({placeholders})
                  AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
                """,
                tuple(schemas),
            )
            fk_rows = cur.fetchall() or []
            fk_lookup: Dict[Tuple[str, str, str], str] = {}
            for fk in fk_rows:
                key = (fk["TABLE_SCHEMA"], fk["TABLE_NAME"], fk["COLUMN_NAME"])
                ref = (
                    f"{fk['REFERENCED_TABLE_SCHEMA']}."
                    f"{fk['REFERENCED_TABLE_NAME']}."
                    f"{fk['REFERENCED_COLUMN_NAME']}"
                )
                fk_lookup[key] = ref

            # 4. Build CrawledAssets
            assets_by_key: Dict[Tuple[str, str], CrawledAsset] = {}
            for t in table_rows:
                schema = t["TABLE_SCHEMA"]
                tbl = t["TABLE_NAME"]
                fq = f"{schema}.{tbl}"
                asset_type = "VIEW" if t["TABLE_TYPE"] == "VIEW" else "TABLE"
                asset = CrawledAsset(
                    source_name=source_name,
                    source_uri=source_uri,
                    asset_type=asset_type,
                    schema_name=schema,
                    asset_name=tbl,
                    fully_qualified=fq,
                    row_count=int(t["TABLE_ROWS"]) if t.get("TABLE_ROWS") is not None else None,
                    comment=(t.get("TABLE_COMMENT") or None),
                )
                assets_by_key[(schema, tbl)] = asset
                result.assets.append(asset)

            for c in col_rows:
                key = (c["TABLE_SCHEMA"], c["TABLE_NAME"])
                asset = assets_by_key.get(key)
                if asset is None:
                    continue
                is_pk = c.get("COLUMN_KEY") == "PRI"
                fk_ref = fk_lookup.get(
                    (c["TABLE_SCHEMA"], c["TABLE_NAME"], c["COLUMN_NAME"])
                )
                asset.columns.append(CrawledColumn(
                    name=c["COLUMN_NAME"],
                    data_type=c["COLUMN_TYPE"] or c["DATA_TYPE"] or "",
                    nullable=(c.get("IS_NULLABLE") == "YES"),
                    ordinal=int(c.get("ORDINAL_POSITION") or 0),
                    is_pk=is_pk,
                    is_fk=bool(fk_ref),
                    fk_references=fk_ref,
                    default_value=str(c["COLUMN_DEFAULT"]) if c.get("COLUMN_DEFAULT") is not None else None,
                    comment=(c.get("COLUMN_COMMENT") or None),
                ))

            # 5. Sample values (optional, one query per column — small cost
            # for pmos_servicing which tops out at ~15 columns per table)
            if sample_rows > 0:
                sample_cur = conn.cursor()
                for asset in result.assets:
                    if asset.asset_type != "TABLE":
                        continue
                    for col in asset.columns:
                        if skip_sensitive and SENSITIVE_PATTERNS.search(col.name):
                            continue
                        try:
                            sample_cur.execute(
                                f"SELECT DISTINCT `{col.name}` "
                                f"FROM `{asset.schema_name}`.`{asset.asset_name}` "
                                f"WHERE `{col.name}` IS NOT NULL "
                                f"LIMIT {int(sample_rows)}"
                            )
                            rows = sample_cur.fetchall()
                            col.sample_values = [
                                _to_jsonable(r[0]) for r in rows if r and r[0] is not None
                            ]
                        except Exception as exc:
                            result.errors.append(
                                f"sample {asset.fully_qualified}.{col.name}: {exc}"
                            )
                            continue
                sample_cur.close()

            cur.close()
        except Exception as exc:
            result.errors.append(f"crawler error: {exc}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return result


def _to_jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except Exception:
            return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)
