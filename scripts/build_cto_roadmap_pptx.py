"""Generate the CTO Data Engineering Roadmap 2026-2030 PowerPoint deck."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Sequence, Tuple

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE


# ── Theme tokens ──────────────────────────────────────────────────────────────
BG = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x1F, 0x2A, 0x44)
INK_MUTED = RGBColor(0x55, 0x60, 0x7A)
ACCENT = RGBColor(0x1B, 0x55, 0xE0)
ACCENT_DARK = RGBColor(0x14, 0x40, 0xA8)
WARN = RGBColor(0xC1, 0x46, 0x2C)
GOOD = RGBColor(0x1F, 0x80, 0x55)
RULE = RGBColor(0xE3, 0xE7, 0xEF)
HEADER_BG = RGBColor(0x1F, 0x2A, 0x44)
HEADER_FG = RGBColor(0xFF, 0xFF, 0xFF)
ROW_ALT = RGBColor(0xF5, 0xF7, 0xFB)


# ── Helpers ───────────────────────────────────────────────────────────────────
def add_blank_slide(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])  # 6 = Blank


def set_slide_bg(slide, color=BG):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_textbox(slide, left, top, width, height, text, *,
                size=18, bold=False, color=INK, align=PP_ALIGN.LEFT,
                anchor=MSO_ANCHOR.TOP, font_name="Calibri"):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = Emu(0)
    tf.margin_right = Emu(0)
    tf.margin_top = Emu(0)
    tf.margin_bottom = Emu(0)
    p = tf.paragraphs[0]
    p.alignment = align
    if isinstance(text, list):
        first = True
        for t in text:
            if first:
                run = p.add_run()
                first = False
            else:
                p2 = tf.add_paragraph()
                p2.alignment = align
                run = p2.add_run()
            run.text = t
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = color
            run.font.name = font_name
    else:
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = font_name
    return tb


def add_bullets(slide, left, top, width, height, items: List[Tuple[str, int]],
                *, size=16, color=INK):
    """items = list of (text, indent_level)."""
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Emu(0)
    tf.margin_right = Emu(0)
    tf.margin_top = Emu(0)
    tf.margin_bottom = Emu(0)
    for i, (text, level) in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.level = level
        bullet = "•" if level == 0 else "–"
        run = p.add_run()
        run.text = f"{bullet}  {text}"
        run.font.size = Pt(size)
        run.font.color.rgb = color
        run.font.name = "Calibri"
        p.space_after = Pt(6)
    return tb


def add_header_bar(slide, title, subtitle=None, *, slide_num=None):
    """Standard slide header: thin colored bar + title + optional subtitle + slide num."""
    # Top accent bar
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                 Inches(0), Inches(0), Inches(13.333), Inches(0.18))
    bar.fill.solid(); bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()

    # Title
    add_textbox(slide, Inches(0.55), Inches(0.32), Inches(11), Inches(0.6),
                title, size=28, bold=True, color=INK)
    if subtitle:
        add_textbox(slide, Inches(0.55), Inches(0.85), Inches(11), Inches(0.4),
                    subtitle, size=14, color=INK_MUTED)
    # Page number
    if slide_num is not None:
        add_textbox(slide, Inches(12.5), Inches(7.05), Inches(0.7), Inches(0.3),
                    str(slide_num), size=10, color=INK_MUTED, align=PP_ALIGN.RIGHT)
    # Footer rule
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                  Inches(0.55), Inches(7.0), Inches(12.2), Inches(0.02))
    rule.fill.solid(); rule.fill.fore_color.rgb = RULE
    rule.line.fill.background()


def add_table(slide, left, top, width, height,
              headers: Sequence[str], rows: Sequence[Sequence[str]],
              *, header_bg=HEADER_BG, header_fg=HEADER_FG,
              col_widths_in: Sequence[float] = None,
              cell_size=12):
    n_cols = len(headers)
    n_rows = len(rows) + 1
    tbl_shape = slide.shapes.add_table(n_rows, n_cols, left, top, width, height)
    tbl = tbl_shape.table

    if col_widths_in:
        for i, w in enumerate(col_widths_in):
            tbl.columns[i].width = Inches(w)

    # Header
    for j, h in enumerate(headers):
        cell = tbl.cell(0, j)
        cell.fill.solid(); cell.fill.fore_color.rgb = header_bg
        tf = cell.text_frame
        tf.margin_left = Emu(60000); tf.margin_right = Emu(60000)
        tf.margin_top = Emu(40000); tf.margin_bottom = Emu(40000)
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
        run = p.add_run(); run.text = h
        run.font.size = Pt(cell_size + 1); run.font.bold = True
        run.font.color.rgb = header_fg; run.font.name = "Calibri"

    # Body
    for i, row in enumerate(rows):
        bg = BG if i % 2 == 0 else ROW_ALT
        for j, val in enumerate(row):
            cell = tbl.cell(i + 1, j)
            cell.fill.solid(); cell.fill.fore_color.rgb = bg
            tf = cell.text_frame
            tf.margin_left = Emu(60000); tf.margin_right = Emu(60000)
            tf.margin_top = Emu(30000); tf.margin_bottom = Emu(30000)
            tf.word_wrap = True
            p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
            run = p.add_run(); run.text = str(val)
            run.font.size = Pt(cell_size); run.font.color.rgb = INK
            run.font.name = "Calibri"
    return tbl_shape


def add_chip(slide, left, top, text, *, color=ACCENT, fg=RGBColor(0xFF, 0xFF, 0xFF),
             size=11, width=None, height=Inches(0.32)):
    if width is None:
        width = Inches(max(1.0, 0.12 * len(text)))
    chip = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    chip.fill.solid(); chip.fill.fore_color.rgb = color
    chip.line.fill.background()
    tf = chip.text_frame
    tf.margin_left = Emu(80000); tf.margin_right = Emu(80000)
    tf.margin_top = Emu(20000); tf.margin_bottom = Emu(20000)
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    run = p.add_run(); run.text = text
    run.font.size = Pt(size); run.font.bold = True
    run.font.color.rgb = fg; run.font.name = "Calibri"
    return chip


# ── Slides ────────────────────────────────────────────────────────────────────
def slide_title(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    # Big colored band
    band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                              Inches(0), Inches(0), Inches(13.333), Inches(3.0))
    band.fill.solid(); band.fill.fore_color.rgb = ACCENT_DARK
    band.line.fill.background()
    add_textbox(s, Inches(0.7), Inches(0.7), Inches(11.5), Inches(0.5),
                "CTO STRATEGY BRIEF", size=14, bold=True,
                color=RGBColor(0xCB, 0xD8, 0xF7))
    add_textbox(s, Inches(0.7), Inches(1.2), Inches(11.5), Inches(1.4),
                "Data Engineering Roadmap", size=44, bold=True,
                color=RGBColor(0xFF, 0xFF, 0xFF))
    add_textbox(s, Inches(0.7), Inches(2.2), Inches(11.5), Inches(0.6),
                "2026 — 2030", size=28, bold=True,
                color=RGBColor(0xCB, 0xD8, 0xF7))
    # Subtitle
    add_textbox(s, Inches(0.7), Inches(3.5), Inches(11.5), Inches(0.5),
                "The role is not disappearing. It is splitting.",
                size=22, bold=True, color=INK)
    add_textbox(s, Inches(0.7), Inches(4.1), Inches(11.5), Inches(0.5),
                "Here is how we lead our team through the transition.",
                size=18, color=INK_MUTED)
    # Footer
    add_textbox(s, Inches(0.7), Inches(6.7), Inches(11.5), Inches(0.4),
                "Prepared for executive review · Confidential",
                size=11, color=INK_MUTED)


def slide_exec_summary(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Executive Summary",
                   "One-slide read for CFO / CEO. Three numbers, one ask.",
                   slide_num=2)

    # The shift in three lines
    add_textbox(s, Inches(0.55), Inches(1.45), Inches(12.2), Inches(0.4),
                "The shift in three lines",
                size=16, bold=True, color=ACCENT_DARK)
    add_bullets(s, Inches(0.7), Inches(1.85), Inches(12.0), Inches(1.6), [
        ("Vendors and agentic catalogs absorb ~30% of today's DE work by 2028.", 0),
        ("Domain modeling, privacy, agent ops, and cross-vendor reasoning grow ~30%.", 0),
        ("The middle 40% (contracts, semantic layers, DQ) stays human but turns declarative.", 0),
    ], size=15)

    # Net effect
    add_textbox(s, Inches(0.55), Inches(3.55), Inches(12.2), Inches(0.4),
                "Net effect on our team",
                size=16, bold=True, color=ACCENT_DARK)
    add_bullets(s, Inches(0.7), Inches(3.95), Inches(12.0), Inches(1.6), [
        ("Headcount: flat for ~3 years, then specialization-driven growth.", 0),
        ("Skill mix: ~60% turnover required across the 5-year window.", 0),
        ("Comp: top-tier rises, bottom-tier flattens — the team polarizes.", 0),
    ], size=15)

    # Ask
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(5.7), Inches(12.2), Inches(1.0))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xFE, 0xF6, 0xE6)
    box.line.color.rgb = WARN; box.line.width = Pt(1.5)
    add_textbox(s, Inches(0.85), Inches(5.85), Inches(11.6), Inches(0.4),
                "Decision asked of leadership",
                size=14, bold=True, color=WARN)
    add_textbox(s, Inches(0.85), Inches(6.2), Inches(11.6), Inches(0.5),
                "Approve a 5-year reskilling + hiring shift. Freeze hiring on legacy pipeline roles starting Q1 2026.",
                size=14, color=INK)


def slide_forces(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Forces Reshaping the Role",
                   "Five disruption vectors converging now.", slide_num=3)
    headers = ["Force", "Status", "Time horizon"]
    rows = [
        ["Operational apps shift-left to lake (Iceberg / Delta)", "Active", "2-3 yrs to mainstream"],
        ["Vendor agentic cataloging (Snowflake / Databricks / Microsoft)", "Live in beta", "12-18 mo to GA"],
        ["LLM-driven NL-to-SQL + semantic layer", "Live", "Already eroding routine SQL roles"],
        ["Data contracts as the new primitive", "Emerging", "2-3 yrs to standardize"],
        ["Privacy + sovereignty regulation", "Tightening", "Continuous through 2030"],
    ]
    add_table(s, Inches(0.55), Inches(1.6), Inches(12.2), Inches(3.6),
              headers, rows, col_widths_in=[6.0, 2.5, 3.7], cell_size=13)
    # Implication
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(5.6), Inches(12.2), Inches(1.0))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xEC, 0xF3, 0xFF)
    box.line.color.rgb = ACCENT; box.line.width = Pt(1.0)
    add_textbox(s, Inches(0.85), Inches(5.75), Inches(11.6), Inches(0.4),
                "Implication", size=14, bold=True, color=ACCENT_DARK)
    add_textbox(s, Inches(0.85), Inches(6.1), Inches(11.6), Inches(0.5),
                "Every routine pipeline / catalog / KPI-SQL task is on a 36-month decline curve.",
                size=14, color=INK)


def slide_30_40_30(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "The 30 / 40 / 30 Split",
                   "Where the work goes over the next 5 years.", slide_num=4)
    headers = ["Tier", "Today's work", "5-year direction"]
    rows = [
        ["Bottom 30% — at risk",
         "Pipeline plumbing, manual schema mapping, routine SQL transforms, doc writing",
         "Mostly automated. Headcount declines."],
        ["Middle 40% — reshape",
         "Semantic layer, data contracts, DQ governance, lineage",
         "Stays human; shifts procedural to declarative. Headcount flat."],
        ["Top 30% — grow",
         "Streaming, privacy, cross-vendor reasoning, agent ops, cost engineering, domain modeling",
         "Demand exceeds supply. Headcount + comp grow."],
    ]
    add_table(s, Inches(0.55), Inches(1.6), Inches(12.2), Inches(3.6),
              headers, rows, col_widths_in=[2.6, 5.8, 3.8], cell_size=13)
    add_textbox(s, Inches(0.55), Inches(5.5), Inches(12.2), Inches(0.4),
                "Strategic move", size=16, bold=True, color=ACCENT_DARK)
    add_textbox(s, Inches(0.55), Inches(5.9), Inches(12.2), Inches(0.6),
                "Actively migrate people up the tiers. Stop hiring at the bottom.",
                size=16, color=INK)


def slide_timeline(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "5-Year Timeline at a Glance",
                   "One page. One arc. Five mile-markers.", slide_num=5)

    years = [
        ("2026", "Foundation",
         "Data contracts spec'd · Semantic layer chosen · Privacy hire #1 · Hiring freeze on pipeline roles."),
        ("2027", "Reskill + Agent Ops",
         "50% of team trained on declarative + AI ops · LLM eval harness live · Domain Product Owners embedded in 2 domains."),
        ("2028", "Cross-Vendor Reasoning",
         "Bridge layer in production · 2 vendor catalogs federated · Vendor agentic features evaluated for buy-vs-build."),
        ("2029", "Specialization",
         "Streaming + privacy + agent ops form 3 named tracks · Steward labor scaled · Top 100 questions fully automated."),
        ("2030", "Steady State",
         "Team is 60% top-tier roles · Cross-vendor moat established · DE = AI-governed data product engineering."),
    ]

    # Horizontal timeline
    rail_y = Inches(2.0)
    rail_left = Inches(0.55); rail_right = Inches(12.78)
    rail = s.shapes.add_connector(1, rail_left, rail_y, rail_right, rail_y)
    rail.line.color.rgb = ACCENT; rail.line.width = Pt(3)

    n = len(years); usable = 12.78 - 0.55
    step = usable / (n - 1)

    for i, (yr, name, body) in enumerate(years):
        cx_in = 0.55 + step * i
        # Marker
        circ = s.shapes.add_shape(MSO_SHAPE.OVAL,
                                  Inches(cx_in - 0.18), Inches(1.82),
                                  Inches(0.36), Inches(0.36))
        circ.fill.solid(); circ.fill.fore_color.rgb = ACCENT_DARK
        circ.line.color.rgb = ACCENT_DARK
        # Year label above
        add_textbox(s, Inches(cx_in - 0.6), Inches(1.4), Inches(1.2), Inches(0.4),
                    yr, size=14, bold=True, color=ACCENT_DARK,
                    align=PP_ALIGN.CENTER)
        # Card below
        card_w = 2.32; card_left = cx_in - card_w / 2
        if card_left < 0.4: card_left = 0.4
        if card_left + card_w > 12.93: card_left = 12.93 - card_w
        card_top_in = 2.6 + (0.45 if i % 2 == 1 else 0.0)
        card = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                  Inches(card_left), Inches(card_top_in),
                                  Inches(card_w), Inches(3.4))
        card.fill.solid(); card.fill.fore_color.rgb = ROW_ALT
        card.line.color.rgb = RULE
        # Card title
        add_textbox(s, Inches(card_left + 0.12), Inches(card_top_in + 0.15),
                    Inches(card_w - 0.24), Inches(0.45),
                    name, size=14, bold=True, color=INK)
        add_textbox(s, Inches(card_left + 0.12), Inches(card_top_in + 0.7),
                    Inches(card_w - 0.24), Inches(2.55),
                    body, size=11, color=INK)


def _year_slide(prs, num, year, theme, actions, challenges, constraints, decisions):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, f"{year}: {theme.split(': ',1)[0]}",
                   theme if ': ' not in theme else theme.split(': ', 1)[1],
                   slide_num=num)

    # Two columns
    col_w = Inches(5.95)
    left_col = Inches(0.55); right_col = Inches(6.85)
    top = Inches(1.45); col_h = Inches(5.4)

    # Actions (left)
    add_textbox(s, left_col, top, col_w, Inches(0.4),
                "Actions", size=15, bold=True, color=GOOD)
    add_bullets(s, left_col, Inches(1.9), col_w, Inches(2.8),
                [(a, 0) for a in actions], size=13)

    # Constraints (left, lower)
    add_textbox(s, left_col, Inches(4.85), col_w, Inches(0.4),
                "Constraints", size=15, bold=True, color=INK_MUTED)
    add_bullets(s, left_col, Inches(5.3), col_w, Inches(1.6),
                [(c, 0) for c in constraints], size=13)

    # Challenges (right)
    add_textbox(s, right_col, top, col_w, Inches(0.4),
                "Challenges", size=15, bold=True, color=WARN)
    add_bullets(s, right_col, Inches(1.9), col_w, Inches(2.8),
                [(c, 0) for c in challenges], size=13)

    # Decisions (right, lower)
    add_textbox(s, right_col, Inches(4.85), col_w, Inches(0.4),
                "Decisions needed", size=15, bold=True, color=ACCENT_DARK)
    add_bullets(s, right_col, Inches(5.3), col_w, Inches(1.6),
                [(d, 0) for d in decisions], size=13)


def slide_2026(prs):
    _year_slide(prs, 6, 2026, "Foundation Year: Lay the rails before the train arrives.",
        actions=[
            "Adopt one semantic layer org-wide (Cube / dbt-MetricFlow / build) by Q1.",
            "Spec data contracts (Open Data Contract Standard) for top 20 producer-consumer pairs.",
            "Hire one privacy engineer — non-negotiable.",
            "Freeze hiring on pure-pipeline roles.",
        ],
        challenges=[
            "Existing teams resist process change — \"we already have Airflow.\"",
            "Vendor pressure to commit early to Cortex / Genie.",
            "Privacy talent supply is thin and expensive.",
        ],
        constraints=[
            "$X M reskilling budget required.",
            "6-month productivity dip during transition.",
        ],
        decisions=[
            "Approve hiring freeze on pipeline-only JDs.",
            "Approve $X M training budget.",
        ])


def slide_2027(prs):
    _year_slide(prs, 7, 2027, "Reskill + Agent Operations: Stand up agent ops as a discipline.",
        actions=[
            "Build LLM eval harness — regression test for prompt / model swaps.",
            "Stand up vector DB + feature store as a platform service.",
            "Promote 2-3 senior DEs to Data Product Owner roles, embed in domain teams.",
            "Re-train 50% of team on semantic layer + graph + agent ops.",
        ],
        challenges=[
            "Eval harness is hard — no industry standard yet.",
            "Senior DEs may resist becoming \"the catalog steward.\"",
            "AI vendor pricing volatility (~3x swings expected).",
        ],
        constraints=[
            "Cost-per-query budget enforcement needed.",
            "Off-ramp plan for engineers who can't reskill.",
        ],
        decisions=[
            "Allocate 1-2 FTE to agent platform team.",
            "Approve embedded-DE org model.",
        ])


def slide_2028(prs):
    _year_slide(prs, 8, 2028, "Cross-Vendor Reasoning Bridge: Build the moat vendors won't.",
        actions=[
            "Deploy cross-vendor ontology + translator service to production.",
            "Federate top 3 source systems into the bridge.",
            "Re-evaluate buy-vs-build per Snowflake / Databricks GA features.",
            "Stand up steward labor (3-5 FTE or outsourced) to keep ontology current.",
        ],
        challenges=[
            "Vendors may ship \"good enough\" cross-warehouse features.",
            "Steward labor cost is sustained, not one-time.",
            "Cross-vendor latency (10-30s) hard to defend vs static reports.",
        ],
        constraints=[
            "Bridge cannot replace existing catalog (Collibra / Alation) — must augment.",
            "Multi-vendor SLA orchestration required.",
        ],
        decisions=[
            "Build bridge or wait for vendor — re-decide each quarter.",
            "Steward FTE count + level.",
        ])


def slide_2029(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "2029: Specialization Tracks",
                   "Three named career tracks emerge — supply chases demand.",
                   slide_num=9)
    tracks = [
        ("A", "Streaming + Reliability",
         "Exactly-once, watermarking, schema evolution, data SLOs.",
         "~20%", "Hardest to automate. Highest comp.", GOOD),
        ("B", "Privacy + Governance",
         "Differential privacy, tokenization, federated compute, residency routing.",
         "~15%", "Demand exceeds supply through decade.", ACCENT),
        ("C", "Agent + Platform Ops",
         "LLM ops, ontology stewardship, semantic-layer engineering, cost optimization.",
         "~25%", "Newest discipline; promote-from-within bias.", ACCENT_DARK),
    ]
    y_in = 1.5; card_h = 1.3
    for letter, name, body, share, sub, color in tracks:
        # Track letter badge
        badge = s.shapes.add_shape(MSO_SHAPE.OVAL,
                                   Inches(0.55), Inches(y_in + 0.15),
                                   Inches(0.65), Inches(0.65))
        badge.fill.solid(); badge.fill.fore_color.rgb = color
        badge.line.fill.background()
        add_textbox(s, Inches(0.55), Inches(y_in + 0.16), Inches(0.65), Inches(0.6),
                    f"Track {letter}", size=10, bold=True,
                    color=RGBColor(0xFF, 0xFF, 0xFF), align=PP_ALIGN.CENTER,
                    anchor=MSO_ANCHOR.MIDDLE)
        # Card
        card = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                  Inches(1.35), Inches(y_in),
                                  Inches(11.4), Inches(card_h))
        card.fill.solid(); card.fill.fore_color.rgb = ROW_ALT
        card.line.color.rgb = RULE
        add_textbox(s, Inches(1.55), Inches(y_in + 0.1), Inches(8.5), Inches(0.4),
                    name, size=15, bold=True, color=INK)
        add_textbox(s, Inches(1.55), Inches(y_in + 0.55), Inches(8.5), Inches(0.5),
                    body, size=12, color=INK_MUTED)
        add_textbox(s, Inches(1.55), Inches(y_in + 0.95), Inches(8.5), Inches(0.4),
                    sub, size=11, color=color)
        # Share badge on right
        add_chip(s, Inches(11.5), Inches(y_in + 0.4),
                 share, color=color, width=Inches(1.1))
        y_in += card_h + 0.2

    # Bottom line
    add_textbox(s, Inches(0.55), Inches(5.8), Inches(12.2), Inches(0.4),
                "Plus", size=14, bold=True, color=INK_MUTED)
    add_bullets(s, Inches(0.55), Inches(6.2), Inches(12.2), Inches(0.8), [
        ("Domain Product Owners (~15%) — embedded, not central.", 0),
        ("Routine pipeline + DQ (~25%) — outsourced or auto-managed by 2030.", 0),
    ], size=13)


def slide_2030(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "2030: Steady-State Org",
                   "What the team looks like at the end of the arc.",
                   slide_num=10)

    # Composition table
    headers = ["Role bucket", "Share", "Notes"]
    rows = [
        ["Streaming + Reliability", "20%", "Hardest to automate. Top comp."],
        ["Privacy + Governance", "15%", "Supply-constrained through decade."],
        ["Agent + Platform Ops", "25%", "Largest growth tier."],
        ["Domain Product Owners", "15%", "Embedded with business."],
        ["Pipeline Ops (lean)", "25%", "Mostly auto-managed by then."],
    ]
    add_table(s, Inches(0.55), Inches(1.5), Inches(7.2), Inches(3.6),
              headers, rows, col_widths_in=[3.4, 1.3, 2.5], cell_size=13)

    # Right-side narrative box
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(8.0), Inches(1.5), Inches(4.78), Inches(5.0))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xEC, 0xF3, 0xFF)
    box.line.color.rgb = ACCENT
    add_textbox(s, Inches(8.2), Inches(1.65), Inches(4.5), Inches(0.4),
                "Defining trait", size=14, bold=True, color=ACCENT_DARK)
    add_textbox(s, Inches(8.2), Inches(2.05), Inches(4.5), Inches(1.0),
                "The team's primary job is making AI behave responsibly on our data.",
                size=14, color=INK)
    add_textbox(s, Inches(8.2), Inches(3.2), Inches(4.5), Inches(0.4),
                "What we own", size=14, bold=True, color=ACCENT_DARK)
    add_textbox(s, Inches(8.2), Inches(3.6), Inches(4.5), Inches(1.5),
                "The bridge between business intent and physical data, the governance loop around it, and the cost of running both.",
                size=13, color=INK)
    add_textbox(s, Inches(8.2), Inches(5.2), Inches(4.5), Inches(0.4),
                "What we don't", size=14, bold=True, color=WARN)
    add_textbox(s, Inches(8.2), Inches(5.6), Inches(4.5), Inches(1.0),
                "Writing pipelines, writing routine SQL, hand-cataloging.",
                size=13, color=INK)


def slide_hiring(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Hiring & Skill Matrix",
                   "Where to hire over the next three years.", slide_num=11)
    headers = ["Role", "2026", "2027", "2028", "Comp band"]
    rows = [
        ["Privacy Engineer", "+1", "+1", "+1", "High, growing"],
        ["Streaming Engineer", "+0", "+1", "+1", "Highest, scarce"],
        ["Data Product Owner (senior DE)", "+2", "+3", "+3", "High"],
        ["Agent Platform Engineer", "+0", "+2", "+2", "High, fastest-growing"],
        ["Semantic Layer Engineer", "+1", "+1", "+0", "Mid-high"],
        ["Pipeline Engineer", "0 (freeze)", "0 (freeze)", "−2 (attrition)", "Flat / declining"],
    ]
    add_table(s, Inches(0.55), Inches(1.45), Inches(12.2), Inches(3.5),
              headers, rows, col_widths_in=[4.4, 1.4, 1.4, 1.6, 3.4], cell_size=12)

    add_textbox(s, Inches(0.55), Inches(5.15), Inches(12.2), Inches(0.4),
                "Skills to build internally (training budget)",
                size=14, bold=True, color=ACCENT_DARK)
    add_bullets(s, Inches(0.55), Inches(5.55), Inches(12.2), Inches(1.4), [
        ("Graph databases (Neo4j or similar) · Iceberg / Delta open table formats", 0),
        ("Prompt eval + regression testing · cost-per-query telemetry", 0),
        ("Differential privacy basics · entitlements + row-level RBAC", 0),
    ], size=13)


def slide_buy_vs_build(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Build vs Buy Framework",
                   "Re-decide every quarter against the vendor roadmap.",
                   slide_num=12)

    # Three columns
    cols = [
        ("Default to BUY", GOOD, [
            "Single-warehouse (Snowflake-only) → Cortex Analyst",
            "Single-lakehouse (Databricks-only) → Genie + AI/BI",
            "Routine NL-to-SQL → vendor",
        ]),
        ("BUILD / open-source", ACCENT_DARK, [
            "Heterogeneous estate (Oracle + warehouse + SaaS + mainframe)",
            "Domain meaning is regulatory-loaded (HMDA, RESPA, SOX, GDPR)",
            "Cross-vendor ontology / lineage required",
            "Steward governance loop must be customizable",
        ]),
        ("HYBRID — likely answer", WARN, [
            "Buy warehouse-native NL-to-SQL piece",
            "Build cross-vendor ontology + governance on top",
            "Open-source the contract + semantic spec to avoid lock-in",
        ]),
    ]
    col_w = 4.0; gap = 0.15
    start_left = 0.55
    for i, (title, color, items) in enumerate(cols):
        left = start_left + i * (col_w + gap)
        card = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                  Inches(left), Inches(1.5),
                                  Inches(col_w), Inches(5.2))
        card.fill.solid(); card.fill.fore_color.rgb = ROW_ALT
        card.line.color.rgb = color; card.line.width = Pt(2)
        # Header strip
        strip = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                   Inches(left), Inches(1.5),
                                   Inches(col_w), Inches(0.55))
        strip.fill.solid(); strip.fill.fore_color.rgb = color
        strip.line.fill.background()
        add_textbox(s, Inches(left + 0.15), Inches(1.55), Inches(col_w - 0.3), Inches(0.5),
                    title, size=14, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        add_bullets(s, Inches(left + 0.15), Inches(2.2), Inches(col_w - 0.3), Inches(4.4),
                    [(t, 0) for t in items], size=12)


def slide_risks(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Risks & Constraints",
                   "What can break the plan, and what's already non-negotiable.",
                   slide_num=13)

    add_textbox(s, Inches(0.55), Inches(1.4), Inches(12.2), Inches(0.4),
                "Top 5 risks", size=15, bold=True, color=WARN)
    headers = ["Risk", "Mitigation"]
    rows = [
        ["Vendor closes the gap faster than expected (12-mo earlier shipping).",
         "Design bridge layer to be portable; reevaluate quarterly."],
        ["Reskilling fails — bottom-tier engineers can't or won't level up.",
         "Explicit 12-month ramp + off-ramp; honest conversations early."],
        ["Steward labor cost balloons.",
         "Outsource to managed service or domain-team embedment."],
        ["AI cost volatility — LLM provider raises prices 3x.",
         "Multi-provider abstraction; cost-per-trace budgets enforced in code."],
        ["Regulatory shock (EU AI Act / state laws) forces rearchitecture.",
         "Invest in privacy engineering early; multi-region routing in design."],
    ]
    add_table(s, Inches(0.55), Inches(1.85), Inches(12.2), Inches(3.4),
              headers, rows, col_widths_in=[6.3, 5.9], cell_size=12)

    add_textbox(s, Inches(0.55), Inches(5.45), Inches(12.2), Inches(0.4),
                "Hard constraints", size=15, bold=True, color=INK_MUTED)
    add_bullets(s, Inches(0.55), Inches(5.85), Inches(12.2), Inches(1.4), [
        ("Cannot fire pipeline engineers en masse — reputational + execution risk.", 0),
        ("Cannot replace Collibra / Alation if already deployed — must augment.", 0),
        ("Cannot send PII to external LLMs without enterprise agreements + redaction.", 0),
    ], size=13)


def slide_decisions(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Decisions Needed Now",
                   "Three in 30 days. Three in 90. Three deferred but tracked.",
                   slide_num=14)

    cols = [
        ("Next 30 days", ACCENT_DARK, [
            "Approve the hiring shift — freeze pipeline-only roles, open privacy + product-owner reqs.  CTO + CHRO",
            "Pick the semantic layer (Cube / dbt-MetricFlow / build) — decide by end of Q1.  CTO + Head of Platform",
            "Approve reskilling investment — $X M training budget + 6-month productivity dip.  CTO + CFO",
        ]),
        ("Next 90 days", ACCENT, [
            "Embed Data Product Owners in 2 domain teams as pilot",
            "Stand up agent ops platform team — 2 FTE seed",
            "Build vs buy quarterly review cadence with vendor-roadmap dashboard",
        ]),
        ("Deferred but tracked", INK_MUTED, [
            "Cross-vendor bridge — build vs wait — decision Q3 2026",
            "Steward labor model (embedded vs central vs outsourced) — decision 2027",
            "Multi-LLM provider strategy (single vs multi) — decision 2027",
        ]),
    ]
    col_w = 4.0; gap = 0.15; start_left = 0.55
    for i, (title, color, items) in enumerate(cols):
        left = start_left + i * (col_w + gap)
        strip = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                   Inches(left), Inches(1.5),
                                   Inches(col_w), Inches(0.55))
        strip.fill.solid(); strip.fill.fore_color.rgb = color
        strip.line.fill.background()
        add_textbox(s, Inches(left + 0.15), Inches(1.55), Inches(col_w - 0.3), Inches(0.5),
                    title, size=14, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        card = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                  Inches(left), Inches(2.05),
                                  Inches(col_w), Inches(4.65))
        card.fill.solid(); card.fill.fore_color.rgb = ROW_ALT
        card.line.color.rgb = color
        add_bullets(s, Inches(left + 0.15), Inches(2.2), Inches(col_w - 0.3), Inches(4.4),
                    [(t, 0) for t in items], size=12)


def slide_close(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "The Bet We Are Making",
                   "Closing slide.", slide_num=15)

    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(1.5), Inches(12.2), Inches(2.0))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xEC, 0xF3, 0xFF)
    box.line.color.rgb = ACCENT
    add_textbox(s, Inches(0.85), Inches(1.65), Inches(11.6), Inches(0.5),
                "Data Engineering doesn't shrink — it specializes.",
                size=20, bold=True, color=ACCENT_DARK)
    add_textbox(s, Inches(0.85), Inches(2.15), Inches(11.6), Inches(1.3),
                "Teams that thrive in 2030 will be smaller in plumbing, larger in domain modeling + privacy + agent ops, and indispensable in the multi-vendor + governed-AI space no single vendor will own end-to-end.",
                size=14, color=INK)

    add_textbox(s, Inches(0.55), Inches(3.85), Inches(12.2), Inches(0.5),
                "Our job as leadership",
                size=18, bold=True, color=INK)
    add_bullets(s, Inches(0.55), Inches(4.4), Inches(12.2), Inches(2.0), [
        ("Move people up the value curve faster than the market commoditizes the bottom.", 0),
        ("Spend 2026 on foundations.  Spend 2027–2028 absorbing agent ops and cross-vendor reasoning.", 0),
        ("By 2030, the team should be unrecognizable from today — and indispensable.", 0),
    ], size=15)

    box2 = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                              Inches(0.55), Inches(6.05), Inches(12.2), Inches(0.7))
    box2.fill.solid(); box2.fill.fore_color.rgb = RGBColor(0xFE, 0xF6, 0xE6)
    box2.line.color.rgb = WARN
    add_textbox(s, Inches(0.85), Inches(6.15), Inches(11.6), Inches(0.5),
                "Ask of leadership: approve the hiring shift, training budget, and quarterly build-vs-buy cadence today.",
                size=14, bold=True, color=WARN)


# ── Build ─────────────────────────────────────────────────────────────────────
def build(out_path: Path) -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    slide_title(prs)
    slide_exec_summary(prs)
    slide_forces(prs)
    slide_30_40_30(prs)
    slide_timeline(prs)
    slide_2026(prs)
    slide_2027(prs)
    slide_2028(prs)
    slide_2029(prs)
    slide_2030(prs)
    slide_hiring(prs)
    slide_buy_vs_build(prs)
    slide_risks(prs)
    slide_decisions(prs)
    slide_close(prs)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    print(f"  Wrote {out_path}  ({out_path.stat().st_size / 1024:.1f} KB, {len(prs.slides)} slides)")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/cto_roadmap_2026_2030.pptx")
    build(out)
