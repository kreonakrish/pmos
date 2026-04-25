"""Seed deterministic Report nodes in the ontology Neo4j.

In production these would be populated by report-system crawlers (SSRS,
Cognos, PowerBI, Tableau …). Until those exist we seed a small set so the
translator's report-resolution path has something to find.

Schema:
    (:Report {report_id, name, description, system, owner_team, created_at})
      -[:HAS_DATASET]-> (:ReportDataset {dataset_id, name, command, command_type})
                           -[:RUNS_ON]-> (:DataSource)
    (:Report)-[:USES_ATTRIBUTE]-> (:BusinessAttribute)
"""

from __future__ import annotations

import asyncio
import os
import sys

from neo4j import AsyncGraphDatabase


REPORTS = [
    {
        "report_id": "rpt-loan-default-annual-servicing",
        "name": "Loan Default Annual Servicing Report",
        "description": (
            "Annual roll-up of defaulted loans and total payments collected. "
            "Used by Data Analytics team for year-over-year default trend analysis."
        ),
        "system": "SSRS",
        "owner_team": "data_analytics",
        "datasets": [
            {
                "dataset_id": "rpt-loan-default-annual-servicing-ds1",
                "name": "Defaulted loans by year",
                "command_type": "SQL",
                "command": (
                    "SELECT pa.period_year AS year, "
                    "       COUNT(DISTINCT pa.loan_id) AS defaulted_loans, "
                    "       SUM(pa.pmt_amt) AS total_annual_payments "
                    "FROM pmos_servicing.payments_annual pa "
                    "JOIN pmos_servicing.defaults d ON d.loan_id = pa.loan_id "
                    "GROUP BY pa.period_year ORDER BY pa.period_year DESC"
                ),
                "source_uri_substr": "pmos_servicing",
            }
        ],
        "uses_attributes": [
            "Servicing.Default.default_status",
            "Servicing.Loan.loan_status",
            "Servicing.Payment.actual_paid_amount",
        ],
    },
    {
        "report_id": "rpt-monthly-payment-trends",
        "name": "Monthly Payment Trends",
        "description": (
            "Total and average payments per month across all loans. "
            "Used by Servicing Ops for cash-flow forecasting."
        ),
        "system": "POWERBI",
        "owner_team": "servicing_ops",
        "datasets": [
            {
                "dataset_id": "rpt-monthly-payment-trends-ds1",
                "name": "Monthly aggregate",
                "command_type": "SQL",
                "command": (
                    "SELECT period_month, "
                    "       SUM(payment_amount) AS total_paid, "
                    "       AVG(payment_amount) AS avg_per_loan, "
                    "       SUM(payment_count)  AS payments_observed "
                    "FROM pmos_servicing.payments_monthly "
                    "GROUP BY period_month ORDER BY period_month DESC"
                ),
                "source_uri_substr": "pmos_servicing",
            }
        ],
        "uses_attributes": [
            "Servicing.Payment.actual_paid_amount",
            "Servicing.Payment.payment_date",
        ],
    },
    {
        "report_id": "rpt-origination-income-distribution",
        "name": "Origination Income Distribution",
        "description": (
            "Distribution of applicant annual household income across income bands. "
            "Used by Risk team for affordability segmentation."
        ),
        "system": "COGNOS",
        "owner_team": "risk_team",
        "datasets": [
            {
                "dataset_id": "rpt-origination-income-distribution-ds1",
                "name": "Income band distribution",
                "command_type": "SQL",
                "command": (
                    "SELECT FLOOR(anl_hsld_inc/10000)*10000 AS income_band_min, "
                    "       COUNT(*) AS application_count "
                    "FROM pmos_origination_consumer.consumer_applications "
                    "WHERE anl_hsld_inc IS NOT NULL "
                    "GROUP BY income_band_min ORDER BY income_band_min"
                ),
                "source_uri_substr": "pmos_origination_consumer",
            }
        ],
        "uses_attributes": [
            "Origination.LoanApplication.annual_household_income",
            "Origination.LoanApplication.application_status",
        ],
    },
    {
        "report_id": "rpt-quarterly-marketing-clv",
        "name": "Quarterly Marketing CLV Report",
        "description": (
            "Customer Lifetime Value totals and counts per quarter, per campaign. "
            "Used by Marketing team for campaign ROI review."
        ),
        "system": "TABLEAU",
        "owner_team": "marketing",
        "datasets": [
            {
                "dataset_id": "rpt-quarterly-marketing-clv-ds1",
                "name": "CLV per quarter",
                "command_type": "SQL",
                "command": (
                    "SELECT period_quarter, "
                    "       SUM(cust_lt_val) AS total_clv, "
                    "       COUNT(*) AS campaign_rows, "
                    "       AVG(cust_lt_val) AS avg_clv "
                    "FROM pmos_marketing.campaigns_quarterly "
                    "GROUP BY period_quarter ORDER BY period_quarter DESC"
                ),
                "source_uri_substr": "pmos_marketing",
            }
        ],
        "uses_attributes": [],
    },
    {
        "report_id": "rpt-correspondent-yearly-income",
        "name": "Correspondent Yearly Household Income",
        "description": (
            "Yearly view of household income at origination from correspondent "
            "purchases. Used by Data Analytics team for borrower mix studies."
        ),
        "system": "SSRS",
        "owner_team": "data_analytics",
        "datasets": [
            {
                "dataset_id": "rpt-correspondent-yearly-income-ds1",
                "name": "Yearly household income",
                "command_type": "SQL",
                "command": (
                    "SELECT period_year, "
                    "       AVG(yearly_household_income) AS avg_income, "
                    "       MIN(yearly_household_income) AS min_income, "
                    "       MAX(yearly_household_income) AS max_income, "
                    "       COUNT(*) AS purchase_count "
                    "FROM pmos_origination_correspondent.purchases_annual "
                    "WHERE yearly_household_income IS NOT NULL "
                    "GROUP BY period_year ORDER BY period_year DESC"
                ),
                "source_uri_substr": "pmos_origination_correspondent",
            }
        ],
        "uses_attributes": [
            "Origination.CorrespondentPurchase.borrower_annual_income",
        ],
    },
]


async def main() -> None:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    pw = os.environ["NEO4J_PASSWORD"]

    drv = AsyncGraphDatabase.driver(uri, auth=(user, pw))
    async with drv.session() as s:
        # Constraints (idempotent)
        await s.run(
            "CREATE CONSTRAINT report_id IF NOT EXISTS "
            "FOR (r:Report) REQUIRE r.report_id IS UNIQUE"
        )
        await s.run(
            "CREATE CONSTRAINT report_dataset_id IF NOT EXISTS "
            "FOR (rd:ReportDataset) REQUIRE rd.dataset_id IS UNIQUE"
        )

        for rpt in REPORTS:
            # Report node
            await s.run(
                """
                MERGE (r:Report {report_id: $rid})
                SET r.name = $name,
                    r.description = $desc,
                    r.system = $system,
                    r.owner_team = $team,
                    r.updated_at = datetime(),
                    r.created_at = coalesce(r.created_at, datetime())
                """,
                rid=rpt["report_id"], name=rpt["name"], desc=rpt["description"],
                system=rpt["system"], team=rpt["owner_team"],
            )

            # Datasets + RUNS_ON
            for ds in rpt["datasets"]:
                await s.run(
                    """
                    MATCH (r:Report {report_id: $rid})
                    MERGE (rd:ReportDataset {dataset_id: $did})
                    SET rd.name = $name,
                        rd.command = $cmd,
                        rd.command_type = $ctype,
                        rd.updated_at = datetime()
                    MERGE (r)-[:HAS_DATASET]->(rd)
                    WITH rd
                    MATCH (ds:DataSource)
                    WHERE ds.source_uri CONTAINS $sub
                    MERGE (rd)-[ro:RUNS_ON]->(ds)
                    SET ro.bound_at = coalesce(ro.bound_at, datetime())
                    """,
                    rid=rpt["report_id"], did=ds["dataset_id"], name=ds["name"],
                    cmd=ds["command"], ctype=ds["command_type"],
                    sub=ds["source_uri_substr"],
                )

            # USES_ATTRIBUTE
            for attr_fq in rpt["uses_attributes"]:
                await s.run(
                    """
                    MATCH (r:Report {report_id: $rid})
                    MATCH (ba:BusinessAttribute {fq_name: $afq})
                    MERGE (r)-[:USES_ATTRIBUTE]->(ba)
                    """,
                    rid=rpt["report_id"], afq=attr_fq,
                )
            print(f"  seeded: {rpt['name']}")

        # Verify
        r = await s.run("""
            MATCH (rep:Report)
            OPTIONAL MATCH (rep)-[:HAS_DATASET]->(rd:ReportDataset)
            OPTIONAL MATCH (rd)-[:RUNS_ON]->(src:DataSource)
            OPTIONAL MATCH (rep)-[:USES_ATTRIBUTE]->(ba:BusinessAttribute)
            RETURN rep.name AS name, rep.owner_team AS team,
                   count(DISTINCT rd) AS datasets,
                   count(DISTINCT src) AS sources,
                   count(DISTINCT ba)  AS attributes
            ORDER BY name
        """)
        print("\n=== Reports in graph ===")
        for row in await r.data():
            print(
                f"  {row['name']:50s} team={row['team']:18s} "
                f"datasets={row['datasets']} sources={row['sources']} "
                f"attrs={row['attributes']}"
            )

    await drv.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
