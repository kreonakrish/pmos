"""Generate the 'Skills, Scripts, Subagents, and RAG' agent-knowledge-strategy deck.

A pragmatic engineering brief comparing four ways to give AI agents
domain-specific knowledge or capability: dedicated scripts, skills
(markdown instruction files), subagents (isolated specialist sessions),
and RAG knowledge bases. Covers tradeoffs, when to use each, staleness
behavior, and a recommended layered architecture.
"""

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

# Per-approach accent colors (used on column headers / chips)
COLOR_SCRIPT = RGBColor(0x1F, 0x80, 0x55)    # green — deterministic
COLOR_SKILL = RGBColor(0xC2, 0x6E, 0x1A)     # amber — judgment under uncertainty
COLOR_SUBAGENT = RGBColor(0x6B, 0x3D, 0xB5)  # violet — isolated specialist
COLOR_RAG = RGBColor(0x1B, 0x55, 0xE0)       # blue — recall over corpus
COLOR_SCRIPT_BG = RGBColor(0xE9, 0xF5, 0xEE)
COLOR_SKILL_BG = RGBColor(0xFB, 0xF1, 0xE2)
COLOR_SUBAGENT_BG = RGBColor(0xF1, 0xEC, 0xF8)
COLOR_RAG_BG = RGBColor(0xEC, 0xF3, 0xFF)


# ── Helpers ───────────────────────────────────────────────────────────────────
def add_blank_slide(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


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
                *, size=14, color=INK, bullet_color=None):
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
        p.space_after = Pt(5)
    return tb


def add_header_bar(slide, title, subtitle=None, *, slide_num=None):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                 Inches(0), Inches(0), Inches(13.333), Inches(0.18))
    bar.fill.solid(); bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()
    add_textbox(slide, Inches(0.55), Inches(0.32), Inches(11), Inches(0.6),
                title, size=28, bold=True, color=INK)
    if subtitle:
        add_textbox(slide, Inches(0.55), Inches(0.85), Inches(11), Inches(0.4),
                    subtitle, size=14, color=INK_MUTED)
    if slide_num is not None:
        add_textbox(slide, Inches(12.5), Inches(7.05), Inches(0.7), Inches(0.3),
                    str(slide_num), size=10, color=INK_MUTED, align=PP_ALIGN.RIGHT)
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                  Inches(0.55), Inches(7.0), Inches(12.2), Inches(0.02))
    rule.fill.solid(); rule.fill.fore_color.rgb = RULE
    rule.line.fill.background()


def add_table(slide, left, top, width, height,
              headers: Sequence[str], rows: Sequence[Sequence[str]],
              *, header_bg=HEADER_BG, header_fg=HEADER_FG,
              col_widths_in: Sequence[float] = None,
              cell_size=12,
              header_colors: Sequence[RGBColor] = None):
    n_cols = len(headers)
    n_rows = len(rows) + 1
    tbl_shape = slide.shapes.add_table(n_rows, n_cols, left, top, width, height)
    tbl = tbl_shape.table
    if col_widths_in:
        for i, w in enumerate(col_widths_in):
            tbl.columns[i].width = Inches(w)
    for j, h in enumerate(headers):
        cell = tbl.cell(0, j)
        bg = header_colors[j] if header_colors else header_bg
        cell.fill.solid(); cell.fill.fore_color.rgb = bg
        tf = cell.text_frame
        tf.margin_left = Emu(60000); tf.margin_right = Emu(60000)
        tf.margin_top = Emu(40000); tf.margin_bottom = Emu(40000)
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT
        run = p.add_run(); run.text = h
        run.font.size = Pt(cell_size + 1); run.font.bold = True
        run.font.color.rgb = header_fg; run.font.name = "Calibri"
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
        width = Inches(max(1.0, 0.13 * len(text)))
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


def add_panel(slide, left, top, width, height, *,
              title: str, body_lines: List[str],
              accent: RGBColor, bg: RGBColor,
              title_size=15, body_size=12):
    """A coloured-edge panel with a heading and bullet-style lines."""
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    box.fill.solid(); box.fill.fore_color.rgb = bg
    box.line.color.rgb = accent
    box.line.width = Pt(1.25)
    add_textbox(slide, left + Inches(0.18), top + Inches(0.12),
                width - Inches(0.3), Inches(0.4),
                title, size=title_size, bold=True, color=accent)
    add_bullets(slide, left + Inches(0.18), top + Inches(0.55),
                width - Inches(0.3), height - Inches(0.7),
                [(line, 0) for line in body_lines],
                size=body_size, color=INK)


# ── Slides ────────────────────────────────────────────────────────────────────
def slide_title(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                              Inches(0), Inches(0), Inches(13.333), Inches(3.0))
    band.fill.solid(); band.fill.fore_color.rgb = ACCENT_DARK
    band.line.fill.background()
    add_textbox(s, Inches(0.7), Inches(0.7), Inches(11.5), Inches(0.5),
                "ENGINEERING BRIEF", size=14, bold=True,
                color=RGBColor(0xCB, 0xD8, 0xF7))
    add_textbox(s, Inches(0.7), Inches(1.2), Inches(11.5), Inches(1.4),
                "Scripts, Skills, Subagents, RAG", size=40, bold=True,
                color=RGBColor(0xFF, 0xFF, 0xFF))
    add_textbox(s, Inches(0.7), Inches(2.2), Inches(11.5), Inches(0.6),
                "Choosing the right knowledge surface for AI agents",
                size=22, bold=True,
                color=RGBColor(0xCB, 0xD8, 0xF7))
    add_textbox(s, Inches(0.7), Inches(3.5), Inches(11.5), Inches(0.5),
                "Four tools. Four shapes of knowledge. One pragmatic rule.",
                size=22, bold=True, color=INK)
    add_textbox(s, Inches(0.7), Inches(4.1), Inches(11.5), Inches(0.5),
                "When to write a script, a skill, a subagent — and when to reach for RAG.",
                size=18, color=INK_MUTED)
    add_textbox(s, Inches(0.7), Inches(6.7), Inches(11.5), Inches(0.4),
                "Internal · For engineering review",
                size=11, color=INK_MUTED)


def slide_problem(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "The Problem We Are Trying to Solve",
                   "Teams ship skills like Confluence pages — and the bill comes due later.",
                   slide_num=2)
    add_textbox(s, Inches(0.55), Inches(1.45), Inches(12.2), Inches(0.4),
                "What we keep seeing", size=16, bold=True, color=ACCENT_DARK)
    add_bullets(s, Inches(0.7), Inches(1.85), Inches(12.0), Inches(2.0), [
        ("Skills proliferate as the default unit of \"sharing knowledge with the agent.\"", 0),
        ("They behave like Confluence docs: easy to write, easy to forget, hard to verify.", 0),
        ("Drift is silent — the code changes, the markdown does not, and the agent confidently follows the stale instructions.", 0),
        ("Retrieval is probabilistic — the agent may pick the wrong skill, or none at all, on a given query.", 0),
    ], size=14)
    add_textbox(s, Inches(0.55), Inches(4.3), Inches(12.2), Inches(0.4),
                "What this brief argues", size=16, bold=True, color=ACCENT_DARK)
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(4.75), Inches(12.2), Inches(1.95))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xEC, 0xF3, 0xFF)
    box.line.color.rgb = ACCENT; box.line.width = Pt(1.0)
    add_textbox(s, Inches(0.85), Inches(4.9), Inches(11.6), Inches(0.4),
                "Skills are not wrong — they are misused.",
                size=15, bold=True, color=ACCENT_DARK)
    add_bullets(s, Inches(0.85), Inches(5.35), Inches(11.6), Inches(1.4), [
        ("Most \"skill-shaped\" needs are actually script-shaped — promote them only when judgment is required.", 0),
        ("RAG is the most probabilistic of the three, not the least. It is not the staleness fix.", 0),
        ("The honest answer is layered: scripts where you can, skills where you must, RAG only when corpus size or volatility forces it.", 0),
    ], size=13)


def slide_at_a_glance(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Four Approaches at a Glance",
                   "Same goal — giving the agent capability or knowledge. Four different shapes.",
                   slide_num=3)
    headers = ["Approach", "Shape", "Determinism", "Best for"]
    rows = [
        ["Script (executable)",
         "Sequence of steps with fixed inputs / outputs",
         "Deterministic",
         "Operations the team already knows how to do"],
        ["Skill (instruction file)",
         "Pattern of decisions, composable building blocks merged into the calling agent's prompt",
         "Probabilistic at selection — fixed once injected",
         "Judgment + composition inside the main thread"],
        ["Subagent (isolated session)",
         "Specialist with its own context, tool allowlist, and model — invoked as a tool",
         "Probabilistic at selection AND inside the subagent's own decisions",
         "Heavy intermediate work, tool guardrails, parallelism"],
        ["RAG / knowledge base",
         "Large corpus indexed for similarity recall",
         "Probabilistic at retrieval (most uncertain of the four)",
         "Volatile or volume-heavy reference material"],
    ]
    add_table(s, Inches(0.55), Inches(1.55), Inches(12.2), Inches(4.4),
              headers, rows, col_widths_in=[2.4, 4.2, 2.6, 3.0],
              cell_size=11,
              header_colors=[HEADER_BG, COLOR_SCRIPT, COLOR_SKILL, COLOR_SUBAGENT])
    # Override fourth header bg to RAG color (we have 4 cols but 4 colored rows, so the
    # header_colors above colors the four COLUMNS; since col 1 is generic we set HEADER_BG,
    # then the four approaches share scoping by row colour — we'll add chips instead).
    # Add four small chips under the table, one per approach, to reinforce colour coding.
    add_chip(s, Inches(0.55),  Inches(6.1), "SCRIPT",   color=COLOR_SCRIPT,   size=10, width=Inches(1.4))
    add_chip(s, Inches(2.05),  Inches(6.1), "SKILL",    color=COLOR_SKILL,    size=10, width=Inches(1.4))
    add_chip(s, Inches(3.55),  Inches(6.1), "SUBAGENT", color=COLOR_SUBAGENT, size=10, width=Inches(1.6))
    add_chip(s, Inches(5.25),  Inches(6.1), "RAG",      color=COLOR_RAG,      size=10, width=Inches(1.4))
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(6.55), Inches(12.2), Inches(0.55))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xEC, 0xF3, 0xFF)
    box.line.color.rgb = ACCENT; box.line.width = Pt(1.0)
    add_textbox(s, Inches(0.75), Inches(6.65), Inches(11.85), Inches(0.4),
                "Steps enumerable → script. Judgment in-thread → skill. Heavy isolated work or tool guardrails → subagent. Volatile / large corpus → RAG.",
                size=12, bold=True, color=ACCENT_DARK)


def slide_script_deepdive(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Approach 1 — Scripts",
                   "An executable artifact is the cleanest possible specification of \"how to do X.\"",
                   slide_num=4)
    add_chip(s, Inches(0.55), Inches(1.45), "DETERMINISTIC", color=COLOR_SCRIPT)
    add_panel(s, Inches(0.55), Inches(2.0), Inches(6.0), Inches(2.6),
              title="Strengths",
              body_lines=[
                  "Fully deterministic — same inputs, same outputs.",
                  "Drift is loud: the script breaks when the world changes.",
                  "Testable: unit + integration tests gate every change.",
                  "Single source of truth — runnable, not just readable.",
                  "Reviewable in code review — diffs are concrete.",
              ],
              accent=COLOR_SCRIPT, bg=COLOR_SCRIPT_BG)
    add_panel(s, Inches(6.75), Inches(2.0), Inches(6.0), Inches(2.6),
              title="Weaknesses",
              body_lines=[
                  "Rigid — 90% of cases solved, 10% fail or need code change.",
                  "No judgment under uncertainty.",
                  "Authoring cost is real engineer-time, not minutes.",
                  "Skill ceiling is the author's foresight at write-time.",
              ],
              accent=WARN, bg=RGBColor(0xFE, 0xF6, 0xE6))
    add_textbox(s, Inches(0.55), Inches(4.85), Inches(12.2), Inches(0.4),
                "Use when…", size=15, bold=True, color=COLOR_SCRIPT)
    add_bullets(s, Inches(0.7), Inches(5.25), Inches(12.0), Inches(1.5), [
        ("The steps are known and stable: deploys, migrations, seeds, validations, regression harnesses.", 0),
        ("The cost of getting it wrong is high: drop tables, rotate keys, push to prod.", 0),
        ("You want drift to surface as a build/test failure rather than a silent agent mistake.", 0),
    ], size=13)
    add_textbox(s, Inches(0.55), Inches(6.6), Inches(12.2), Inches(0.4),
                "Examples in PMOS today: scripts/seed_tool_datasource_links.py · scripts/cross_system_query.py · scripts/deploy.sh",
                size=11, color=INK_MUTED)


def slide_skill_deepdive(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Approach 2 — Skills",
                   "Compressed judgment merged into the calling agent's prompt.",
                   slide_num=5)
    add_chip(s, Inches(0.55), Inches(1.45), "JUDGMENT UNDER UNCERTAINTY", color=COLOR_SKILL)
    add_panel(s, Inches(0.55), Inches(2.0), Inches(6.0), Inches(2.6),
              title="Strengths",
              body_lines=[
                  "Composable — agent picks patterns and recombines.",
                  "Cheap to author — markdown, not code.",
                  "Lives in a fixed slot once invoked (less probabilistic than RAG).",
                  "Right home for \"how to think about X here\" knowledge.",
              ],
              accent=COLOR_SKILL, bg=COLOR_SKILL_BG)
    add_panel(s, Inches(6.75), Inches(2.0), Inches(6.0), Inches(2.6),
              title="Weaknesses",
              body_lines=[
                  "Silent staleness — no test fails when the system drifts.",
                  "Selection is probabilistic — agent may not pick the right skill.",
                  "Quality scales with curation discipline; sprawl is the default failure mode.",
                  "No execution guarantees — instructions, not invariants.",
              ],
              accent=WARN, bg=RGBColor(0xFE, 0xF6, 0xE6))
    add_textbox(s, Inches(0.55), Inches(4.85), Inches(12.2), Inches(0.4),
                "Use when…", size=15, bold=True, color=COLOR_SKILL)
    add_bullets(s, Inches(0.7), Inches(5.25), Inches(12.0), Inches(1.5), [
        ("The work requires composition under judgment, not a sequence — code review, refactor scoping, design tradeoffs.", 0),
        ("You can link the skill to source-of-truth files and add a test that fails if those files move.", 0),
        ("The audience is the agent itself, not a human reader (otherwise it is just a doc).", 0),
    ], size=13)
    add_textbox(s, Inches(0.55), Inches(6.6), Inches(12.2), Inches(0.4),
                "Treat skills like code: version with the codebase, link to live paths, write tests that catch drift.",
                size=11, bold=True, color=INK_MUTED)


def slide_subagent_deepdive(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Approach 3 — Subagents",
                   "An isolated specialist session invoked as a tool. Different problem than skills solve.",
                   slide_num=6)
    add_chip(s, Inches(0.55), Inches(1.45),
             "ISOLATION + GUARDRAILS", color=COLOR_SUBAGENT,
             size=11, width=Inches(2.4))
    add_panel(s, Inches(0.55), Inches(2.0), Inches(6.0), Inches(2.6),
              title="Strengths",
              body_lines=[
                  "Context isolation — intermediate tool noise stays out of the main thread.",
                  "Tool allowlist enforced — read-only reviewer cannot accidentally edit.",
                  "Per-task model selection (cheap model for search, strong model for reasoning).",
                  "Parallelism — multiple subagents can run simultaneously.",
                  "Reusable across calling agents.",
              ],
              accent=COLOR_SUBAGENT, bg=COLOR_SUBAGENT_BG)
    add_panel(s, Inches(6.75), Inches(2.0), Inches(6.0), Inches(2.6),
              title="Weaknesses",
              body_lines=[
                  "Probabilistic on TWO axes — selection AND the subagent's own decisions.",
                  "Briefing overhead — calling agent must write a self-contained prompt.",
                  "Indirection — main thread sees the summary, not the steps.",
                  "Latency cost vs inline tool use; over-spawning amplifies it.",
                  "Same silent-rot risk as skills if the definition drifts from reality.",
              ],
              accent=WARN, bg=RGBColor(0xFE, 0xF6, 0xE6))
    add_textbox(s, Inches(0.55), Inches(4.85), Inches(12.2), Inches(0.4),
                "Use when…", size=15, bold=True, color=COLOR_SUBAGENT)
    add_bullets(s, Inches(0.7), Inches(5.25), Inches(12.0), Inches(1.5), [
        ("The work produces heavy intermediate tool output the main thread does not need to see (codebase exploration, multi-file research).", 0),
        ("You need an enforced tool guardrail — a reviewer that physically cannot Edit, an explorer that cannot Write.", 0),
        ("You can run several in parallel and the outputs are summarizable in a few hundred tokens.", 0),
    ], size=13)
    add_textbox(s, Inches(0.55), Inches(6.6), Inches(12.2), Inches(0.4),
                "Examples: code-reviewer (Read+Grep only), explore (codebase search), security-review (read-only audit), Plan (architect-style scoping).",
                size=11, color=INK_MUTED)


def slide_rag_deepdive(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Approach 4 — RAG / Knowledge Base",
                   "Recall over a corpus too big to fit in context and too volatile to hard-code.",
                   slide_num=7)
    add_chip(s, Inches(0.55), Inches(1.45), "VOLATILE / HIGH-VOLUME RECALL", color=COLOR_RAG)
    add_panel(s, Inches(0.55), Inches(2.0), Inches(6.0), Inches(2.6),
              title="Strengths",
              body_lines=[
                  "Scales to large corpora the model cannot hold in context.",
                  "Indexer can refresh from live sources — freshness by design.",
                  "Single retrieval surface across many document types.",
                  "Decouples knowledge growth from prompt engineering.",
              ],
              accent=COLOR_RAG, bg=COLOR_RAG_BG)
    add_panel(s, Inches(6.75), Inches(2.0), Inches(6.0), Inches(2.6),
              title="Weaknesses",
              body_lines=[
                  "Most probabilistic of the three — retrieval ranking can miss.",
                  "Wrong-chunk failures are silent and hard to detect downstream.",
                  "Infra cost: index, embed, refresh, evaluate — non-trivial.",
                  "Garbage-in is amplified — a stale corpus degrades every answer.",
              ],
              accent=WARN, bg=RGBColor(0xFE, 0xF6, 0xE6))
    add_textbox(s, Inches(0.55), Inches(4.85), Inches(12.2), Inches(0.4),
                "Use when…", size=15, bold=True, color=COLOR_RAG)
    add_bullets(s, Inches(0.7), Inches(5.25), Inches(12.0), Inches(1.5), [
        ("The knowledge surface is too large to encode statically: ADRs, runbooks, ontology, customer history.", 0),
        ("The content changes faster than humans can re-curate skills or scripts.", 0),
        ("You can wire freshness checks and retrieval-evaluation into CI — otherwise it rots like everything else.", 0),
    ], size=13)
    add_textbox(s, Inches(0.55), Inches(6.6), Inches(12.2), Inches(0.4),
                "Counter-intuitive: choosing RAG to fix \"probabilistic skill retrieval\" usually makes things more probabilistic, not less.",
                size=11, bold=True, color=INK_MUTED)


def slide_skill_vs_subagent(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Skills vs. Subagents — The Most Common Confusion",
                   "Both look like markdown files. They solve different problems.",
                   slide_num=8)
    headers = ["Dimension", "Skill", "Subagent"]
    rows = [
        ["Where the work runs",
         "Inside the calling agent's session — instructions merged into its prompt.",
         "In a separate session with its own context window and lifecycle."],
        ["Context budget impact",
         "Skill content stays in the main thread; intermediate tool output also stays.",
         "Only the final summary returns to the main thread."],
        ["Tool scoping",
         "Inherits whatever tools the calling agent has — guidance, not enforcement.",
         "Has its own allowlist — physically cannot use tools outside it."],
        ["Model selection",
         "Same model as the calling agent.",
         "Per-subagent model choice (Haiku for search, Opus for reasoning)."],
        ["Concurrency",
         "Serial — one skill at a time, in the main thread.",
         "Parallel — multiple subagents can run simultaneously."],
        ["Failure mode",
         "Selection probabilistic; once injected, behavior is the main agent's.",
         "Selection probabilistic AND subagent's internal decisions probabilistic."],
        ["Best for",
         "Patterns of judgment the main agent should apply itself.",
         "Heavy isolated work, enforced guardrails, parallel research."],
    ]
    add_table(s, Inches(0.55), Inches(1.55), Inches(12.2), Inches(4.7),
              headers, rows,
              col_widths_in=[2.9, 4.6, 4.7], cell_size=11,
              header_colors=[HEADER_BG, COLOR_SKILL, COLOR_SUBAGENT])
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(6.4), Inches(12.2), Inches(0.7))
    box.fill.solid(); box.fill.fore_color.rgb = COLOR_SUBAGENT_BG
    box.line.color.rgb = COLOR_SUBAGENT; box.line.width = Pt(1.25)
    add_textbox(s, Inches(0.85), Inches(6.5), Inches(11.6), Inches(0.5),
                "Promote a skill to a subagent only when context isolation or tool scoping is the actual constraint. Otherwise you are paying for indirection you do not need.",
                size=13, bold=True, color=COLOR_SUBAGENT)


def slide_decision_matrix(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Decision Matrix — How to Choose",
                   "A five-question gate. Default to script unless the higher-cost option earns its keep.",
                   slide_num=9)
    headers = ["Question", "If yes →", "If no →"]
    rows = [
        ["1. Can the steps be enumerated as code with stable inputs and outputs?",
         "Write a script. Stop here.",
         "Continue."],
        ["2. Does the task need composition or judgment that varies by situation?",
         "Continue — this is skill or subagent territory.",
         "Reconsider — likely a script after all."],
        ["3. Does the work generate heavy intermediate tool output, OR need an enforced tool allowlist, OR run in parallel with other work?",
         "Write a subagent. Define its tool allowlist tightly.",
         "Continue — likely a skill."],
        ["4. Will the agent need this guidance in-thread on many tasks?",
         "Write a skill. Link to source-of-truth files; add a drift test.",
         "Reconsider — maybe inline the guidance."],
        ["5. Is the relevant corpus too large to fit in context or too volatile to encode?",
         "Reach for RAG. Wire in freshness + retrieval evaluation.",
         "Stop. Pick from the previous answers."],
    ]
    add_table(s, Inches(0.55), Inches(1.55), Inches(12.2), Inches(4.7),
              headers, rows, col_widths_in=[5.2, 3.7, 3.3], cell_size=11)
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(6.4), Inches(12.2), Inches(0.7))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xEC, 0xF3, 0xFF)
    box.line.color.rgb = ACCENT; box.line.width = Pt(1.0)
    add_textbox(s, Inches(0.85), Inches(6.5), Inches(11.6), Inches(0.5),
                "Default rule: if you can write a script, write the script. The other three earn their keep — they do not get it for free.",
                size=14, bold=True, color=ACCENT_DARK)


def slide_staleness(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Staleness — Who Notices First?",
                   "How each approach behaves when the codebase changes underneath it.",
                   slide_num=10)
    headers = ["Approach", "Drift behavior", "Time to discover", "Mitigation"]
    rows = [
        ["Script",
         "Breaks loudly — exit code, test failure, type error.",
         "Minutes (next CI run).",
         "Already covered by your test pyramid."],
        ["Skill",
         "Silent rot. Agent follows stale instructions; produces a confidently-wrong action.",
         "Days to weeks — discovered via incident.",
         "Link to file paths in code; CI test asserts the paths still exist."],
        ["Subagent",
         "Silent rot in the system prompt + drift in tool allowlist (the real tools may have moved).",
         "Days to weeks — same incident-driven discovery.",
         "Same as skill, plus integration test that runs the subagent on a fixed input."],
        ["RAG",
         "Silent degradation. Retrieval picks an outdated chunk; answer drifts.",
         "Weeks to months — usually noticed via aggregate quality dip.",
         "Indexer freshness SLO + retrieval evaluation on a fixed eval set."],
    ]
    add_table(s, Inches(0.55), Inches(1.55), Inches(12.2), Inches(4.0),
              headers, rows,
              col_widths_in=[2.0, 4.4, 2.4, 3.4],
              cell_size=11,
              header_colors=[HEADER_BG, COLOR_SCRIPT, COLOR_SKILL, COLOR_RAG])
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(5.85), Inches(12.2), Inches(1.0))
    box.fill.solid(); box.fill.fore_color.rgb = COLOR_SCRIPT_BG
    box.line.color.rgb = COLOR_SCRIPT; box.line.width = Pt(1.0)
    add_textbox(s, Inches(0.85), Inches(5.95), Inches(11.6), Inches(0.4),
                "Why scripts win the staleness game",
                size=14, bold=True, color=COLOR_SCRIPT)
    add_textbox(s, Inches(0.85), Inches(6.35), Inches(11.6), Inches(0.5),
                "Loud failure beats silent rot. A script that breaks in CI is a feature — drift becomes a build error, not a production incident.",
                size=13, color=INK)


def slide_probabilistic(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Determinism vs. Probabilistic Retrieval",
                   "Stacking ranks — least probabilistic to most. Fewer flips = fewer surprises.",
                   slide_num=11)
    headers = ["Approach", "Where probability enters", "What is fixed once chosen"]
    rows = [
        ["Script",
         "Nowhere — fully deterministic.",
         "Everything."],
        ["Skill",
         "Selection: agent decides whether to invoke this skill on a given query.",
         "Once invoked, the skill content is fixed in the system prompt."],
        ["Subagent",
         "Selection AND the subagent's own internal decisions. Two coin flips stacked.",
         "Tool allowlist + system prompt are fixed; behavior within them is stochastic."],
        ["RAG",
         "Two stages: query rewrite → retrieval ranking. Both can miss.",
         "Only the chunks actually retrieved make it in — and they may be wrong."],
    ]
    add_table(s, Inches(0.55), Inches(1.55), Inches(12.2), Inches(3.6),
              headers, rows,
              col_widths_in=[2.0, 5.6, 4.6], cell_size=11,
              header_colors=[HEADER_BG, COLOR_SCRIPT, COLOR_SKILL])
    add_textbox(s, Inches(0.55), Inches(5.4), Inches(12.2), Inches(0.4),
                "The counter-intuitive takeaways", size=16, bold=True, color=ACCENT_DARK)
    add_bullets(s, Inches(0.7), Inches(5.8), Inches(12.0), Inches(1.5), [
        ("RAG is more probabilistic than skills, not less. Two ranking decisions stack on top of each other.", 0),
        ("Subagents are more probabilistic than skills, not less. The isolation is the value, not less uncertainty.", 0),
        ("If your concern is \"agent picks the wrong knowledge,\" the fix is fewer + sharper artifacts, not a heavier mechanism.", 0),
    ], size=13)


def slide_layered(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Recommended Layered Architecture",
                   "All four at once — used for what they are each best at.",
                   slide_num=12)
    # 4 panels: 0.55 / 3.65 / 6.75 / 9.85, each 2.92" wide
    add_panel(s, Inches(0.55), Inches(1.55), Inches(2.92), Inches(4.6),
              title="Operational layer",
              body_lines=[
                  "Scripts you commit + run.",
                  "Deploys, migrations, seeds.",
                  "Validation harnesses.",
                  "Cron / scheduled jobs.",
                  "—",
                  "Drift: CI / tests.",
                  "Owner: the engineer.",
                  "Default tool: code.",
              ],
              accent=COLOR_SCRIPT, bg=COLOR_SCRIPT_BG,
              title_size=14, body_size=11)
    add_panel(s, Inches(3.65), Inches(1.55), Inches(2.92), Inches(4.6),
              title="Judgment layer",
              body_lines=[
                  "Skills the agent invokes.",
                  "Code-review patterns.",
                  "Refactor scoping rubrics.",
                  "Design tradeoff playbooks.",
                  "—",
                  "Drift: linked-path tests.",
                  "Owner: the writing team.",
                  "Default tool: markdown.",
              ],
              accent=COLOR_SKILL, bg=COLOR_SKILL_BG,
              title_size=14, body_size=11)
    add_panel(s, Inches(6.75), Inches(1.55), Inches(2.92), Inches(4.6),
              title="Specialist layer",
              body_lines=[
                  "Subagents invoked as tools.",
                  "Read-only reviewer.",
                  "Codebase explorer.",
                  "Security-audit subagent.",
                  "—",
                  "Drift: pinned-input integration test.",
                  "Owner: platform / framework.",
                  "Default tool: subagent definition.",
              ],
              accent=COLOR_SUBAGENT, bg=COLOR_SUBAGENT_BG,
              title_size=14, body_size=11)
    add_panel(s, Inches(9.85), Inches(1.55), Inches(2.92), Inches(4.6),
              title="Volatile-knowledge layer",
              body_lines=[
                  "RAG / catalog / graph.",
                  "ADRs, runbooks, incidents.",
                  "Live ontology + bindings.",
                  "Domain corpora.",
                  "—",
                  "Drift: indexer SLO + eval set.",
                  "Owner: a data team.",
                  "Default tool: query, not encode.",
              ],
              accent=COLOR_RAG, bg=COLOR_RAG_BG,
              title_size=14, body_size=11)
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(6.35), Inches(12.2), Inches(0.6))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xEC, 0xF3, 0xFF)
    box.line.color.rgb = ACCENT; box.line.width = Pt(1.0)
    add_textbox(s, Inches(0.85), Inches(6.45), Inches(11.6), Inches(0.5),
                "PMOS already does three of these — scripts in /scripts, ontology + RAG queryable. The four-layer trap: letting the skill or subagent layer sprawl into the others.",
                size=12, bold=True, color=ACCENT_DARK)


def slide_antipatterns(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Anti-Patterns to Avoid",
                   "Six common ways teams over-spend on the wrong layer.",
                   slide_num=13)
    headers = ["Anti-pattern", "What it looks like", "What to do instead"]
    rows = [
        ["Skill-for-everything",
         "A markdown for \"how to deploy,\" \"how to run tests,\" \"how to seed data.\"",
         "Write the script. The skill, if needed, just says \"run scripts/X.\""],
        ["Confluence-as-a-skill",
         "Documentation ported into a /skills folder — no decision authority, no actions.",
         "Leave it as documentation. Skills are for the agent, not for humans."],
        ["Subagent-for-everything",
         "Spawning a subagent for trivial tasks — adds latency + briefing overhead with no isolation win.",
         "Inline the work, or call a tool directly. Subagents earn their keep on heavy or scoped work."],
        ["Subagent without guardrails",
         "Subagent definition with the full tool allowlist of its parent — same toolset, just slower.",
         "If you are not narrowing tools or isolating context, do not use a subagent."],
        ["RAG over the source code",
         "Indexing the repo to answer code questions — the IDE already does this better.",
         "Use the IDE / language server. Reserve RAG for non-code corpora."],
        ["Script-for-judgment",
         "review.py that grades code with regexes; estimate.py by file count.",
         "Promote to a skill or subagent — the agent can apply judgment regex cannot."],
    ]
    add_table(s, Inches(0.55), Inches(1.55), Inches(12.2), Inches(5.0),
              headers, rows,
              col_widths_in=[2.6, 5.4, 4.2], cell_size=11)
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(6.7), Inches(12.2), Inches(0.45))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xFE, 0xF6, 0xE6)
    box.line.color.rgb = WARN; box.line.width = Pt(1.0)
    add_textbox(s, Inches(0.85), Inches(6.75), Inches(11.6), Inches(0.4),
                "All six share the same root cause: picking the layer that feels easy to author rather than the one that fits the task.",
                size=12, bold=True, color=WARN)


def slide_recommendation(prs):
    s = add_blank_slide(prs); set_slide_bg(s)
    add_header_bar(s, "Recommendation",
                   "What this means for how the team writes things going forward.",
                   slide_num=14)
    add_textbox(s, Inches(0.55), Inches(1.4), Inches(12.2), Inches(0.4),
                "Default rule",
                size=16, bold=True, color=ACCENT_DARK)
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                             Inches(0.55), Inches(1.8), Inches(12.2), Inches(0.7))
    box.fill.solid(); box.fill.fore_color.rgb = COLOR_SCRIPT_BG
    box.line.color.rgb = COLOR_SCRIPT; box.line.width = Pt(1.25)
    add_textbox(s, Inches(0.85), Inches(1.9), Inches(11.6), Inches(0.55),
                "If you can write a script, write the script. Promote to a skill only when judgment is required. Promote to a subagent only when context isolation or tool guardrails are the constraint. Reach for RAG only when corpus size or volatility forces it.",
                size=13, bold=True, color=INK)
    add_textbox(s, Inches(0.55), Inches(2.75), Inches(12.2), Inches(0.4),
                "Four rules of thumb that follow",
                size=16, bold=True, color=ACCENT_DARK)
    add_bullets(s, Inches(0.7), Inches(3.15), Inches(12.0), Inches(2.4), [
        ("Fewer skills, sharper skills. Every skill should answer \"what judgment am I teaching here?\" — if the answer is a sequence of steps, write a script.", 0),
        ("Subagents earn their slot when context isolation OR tool scoping is the actual constraint. Otherwise they add indirection without value.", 0),
        ("Treat skills + subagent definitions like code. Version with the repo, link to live paths, add a CI test that catches drift.", 0),
        ("RAG only when no API exists. If data lives in a DB / catalog / graph, query it directly; RAG is the option of last resort for unstructured corpora.", 0),
    ], size=13)
    add_textbox(s, Inches(0.55), Inches(5.7), Inches(12.2), Inches(0.4),
                "What this means for our work",
                size=16, bold=True, color=ACCENT_DARK)
    add_bullets(s, Inches(0.7), Inches(6.1), Inches(12.0), Inches(1.0), [
        ("Audit existing skills + subagents — most skills demote to scripts; most subagents either tighten their tool allowlist or merge back into a skill.", 0),
        ("Keep growing the script library — cheapest, most durable, loudest on drift.", 0),
    ], size=13)


# ── Build ─────────────────────────────────────────────────────────────────────
def build(out_path: Path) -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    slide_title(prs)
    slide_problem(prs)
    slide_at_a_glance(prs)
    slide_script_deepdive(prs)
    slide_skill_deepdive(prs)
    slide_subagent_deepdive(prs)
    slide_rag_deepdive(prs)
    slide_skill_vs_subagent(prs)
    slide_decision_matrix(prs)
    slide_staleness(prs)
    slide_probabilistic(prs)
    slide_layered(prs)
    slide_antipatterns(prs)
    slide_recommendation(prs)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    print(f"  Wrote {out_path}  ({out_path.stat().st_size / 1024:.1f} KB, {len(prs.slides)} slides)")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/agent_knowledge_strategy.pptx")
    build(out)
