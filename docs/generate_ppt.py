"""Generate PMOS Executive Presentation + Architecture Diagrams."""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
import os

# Colors
DARK_BG = RGBColor(0x1A, 0x1A, 0x2E)
BLUE = RGBColor(0x00, 0x7B, 0xFF)
LIGHT_BLUE = RGBColor(0x4D, 0xA6, 0xFF)
GREEN = RGBColor(0x00, 0xC8, 0x53)
ORANGE = RGBColor(0xFF, 0x9F, 0x00)
RED = RGBColor(0xF4, 0x43, 0x36)
PURPLE = RGBColor(0xAB, 0x47, 0xBC)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRAY = RGBColor(0xB0, 0xB0, 0xB0)
LIGHT_BG = RGBColor(0x2D, 0x2D, 0x44)
CARD_BG = RGBColor(0x35, 0x35, 0x55)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)


def add_dark_bg(slide):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = DARK_BG


def add_textbox(slide, left, top, width, height, text, font_size=14,
                color=WHITE, bold=False, alignment=PP_ALIGN.LEFT, font_name="Segoe UI"):
    txBox = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.name = font_name
    p.alignment = alignment
    return txBox


def add_card(slide, left, top, width, height, title, body, accent=BLUE):
    # Card background
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top),
                                    Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = CARD_BG
    shape.line.fill.background()
    # Accent bar
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top),
                                  Inches(0.06), Inches(height))
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    # Title
    add_textbox(slide, left + 0.2, top + 0.1, width - 0.3, 0.35, title, 13, accent, True)
    # Body
    add_textbox(slide, left + 0.2, top + 0.45, width - 0.3, height - 0.55, body, 10, GRAY)


def add_box(slide, left, top, width, height, text, fill_color=BLUE, font_size=9, text_color=WHITE):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top),
                                    Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    shape.line.fill.background()
    tf = shape.text_frame
    tf.word_wrap = True
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = text_color
    p.font.bold = True
    p.font.name = "Segoe UI"
    return shape


def add_arrow(slide, x1, y1, x2, y2, color=GRAY):
    connector = slide.shapes.add_connector(1, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    connector.line.color.rgb = color
    connector.line.width = Pt(1.5)


# ==========================================
# SLIDE 1: Title
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 1, 1.5, 11, 1.2, "PMOS", 60, BLUE, True, PP_ALIGN.CENTER)
add_textbox(slide, 1, 2.8, 11, 0.8, "Perpetual Multi-Agent Orchestration System", 28, WHITE, False, PP_ALIGN.CENTER)
add_textbox(slide, 2, 4.0, 9, 0.6, "Self-extending AI orchestration that connects structured & unstructured data sources\nthrough collaborative agents for instant cross-domain analytics", 16, GRAY, False, PP_ALIGN.CENTER)
add_textbox(slide, 4, 5.5, 5, 0.4, "Architecture & Value Proposition", 14, LIGHT_BLUE, False, PP_ALIGN.CENTER)

# ==========================================
# SLIDE 2: The Problem
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.8, 0.4, 11, 0.6, "The Problem", 32, BLUE, True)
add_textbox(slide, 0.8, 1.1, 11, 0.5, "Analysts spend 70% of their time finding data, not analyzing it", 18, WHITE, False)

add_card(slide, 0.8, 2.0, 3.7, 1.4, "Data Silos",
         "SQL databases, graph stores, documents,\nAPIs, and code repos — all disconnected.\nNo unified query layer.", RED)
add_card(slide, 4.7, 2.0, 3.7, 1.4, "Manual Integration",
         "Copy-paste between tools. Context\nswitching. Reformatting. Hours spent\non plumbing, not insights.", ORANGE)
add_card(slide, 8.6, 2.0, 3.7, 1.4, "No Learning",
         "Every query starts from scratch.\nNo memory of past analyses.\nNo quality feedback loop.", PURPLE)

add_card(slide, 0.8, 3.8, 5.6, 2.5, "A Typical Cross-Domain Analysis Today",
         "1. Log into MySQL Workbench, write SQL, export CSV\n"
         "2. Open Neo4j Browser, write Cypher, copy results\n"
         "3. Read 20-page DOCX report manually for context\n"
         "4. Open Jupyter, write Python, run calculations\n"
         "5. Search GitHub for reference implementations\n"
         "6. Copy everything into PowerPoint\n\n"
         "Time: 2-4 hours per analysis", RED)

add_card(slide, 6.6, 3.8, 5.6, 2.5, "With PMOS",
         "Ask a single natural language question.\n\n"
         "The system automatically:\n"
         "- Decomposes into sub-tasks\n"
         "- Selects the right agents & tools\n"
         "- Queries all data sources in parallel\n"
         "- Synthesizes into a unified report\n\n"
         "Time: 15 seconds - 3 minutes", GREEN)

# ==========================================
# SLIDE 3: Value Proposition
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.8, 0.4, 11, 0.6, "Value Proposition", 32, BLUE, True)

add_card(slide, 0.8, 1.4, 3.7, 2.0, "For Business Analysts",
         "- Ask questions in plain English\n"
         "- No SQL/Cypher/Python needed\n"
         "- Upload docs, get instant answers\n"
         "- Cross-domain reports in seconds\n"
         "- Full audit trail of reasoning", GREEN)

add_card(slide, 4.7, 1.4, 3.7, 2.0, "For Data Scientists",
         "- Rapid hypothesis testing\n"
         "- Python agent for calculations\n"
         "- RAG pipeline for any document\n"
         "- Memory learns from past queries\n"
         "- RL feedback improves over time", BLUE)

add_card(slide, 8.6, 1.4, 3.7, 2.0, "For Decision Makers",
         "- Consolidated cross-domain reports\n"
         "- No waiting for multiple teams\n"
         "- Confidence scores on every answer\n"
         "- Audit trail for compliance\n"
         "- Self-extending capabilities", PURPLE)

add_card(slide, 0.8, 3.8, 5.6, 2.5, "Key Differentiators vs ChatGPT/Copilot",
         "ChatGPT: Single LLM, no tool access, no memory, hallucinations\n\n"
         "PMOS:\n"
         "  - Multiple specialized agents with dedicated tools\n"
         "  - Direct SQL, Cypher, API access to YOUR systems\n"
         "  - 4-tier memory (short/long/reasoning/episodic)\n"
         "  - RL-trained scoring with adaptive quality bands\n"
         "  - Every claim backed by tool call + audit trail\n"
         "  - Self-extends: detects gaps, generates new tools", ORANGE)

add_card(slide, 6.6, 3.8, 5.6, 2.5, "Proven Results",
         "Test: 5-part cross-domain question requiring\n"
         "MySQL + Neo4j + DOCX + GitHub + Python\n\n"
         "  73 task nodes decomposed\n"
         "  43 sub-agents spawned (depth 3)\n"
         "  213 agent interactions logged\n"
         "  86 capability bids evaluated\n"
         "  4 agents coordinated automatically\n"
         "  Score: 0.70 (within adaptive band)\n"
         "  Full audit trail in Neo4j graph", BLUE)

# ==========================================
# SLIDE 4: C1 - System Context
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.8, 0.3, 11, 0.5, "C1 — System Context Diagram", 28, BLUE, True)
add_textbox(slide, 0.8, 0.8, 11, 0.4, "How PMOS fits in the enterprise ecosystem", 14, GRAY)

# Users
add_box(slide, 1.5, 1.8, 2.2, 0.8, "Business Analysts\n& Data Scientists", RGBColor(0x2E, 0x7D, 0x32))
add_box(slide, 5.5, 1.8, 2.2, 0.8, "Decision Makers\n& Managers", RGBColor(0x2E, 0x7D, 0x32))
add_box(slide, 9.5, 1.8, 2.2, 0.8, "Developers &\nArchitects", RGBColor(0x2E, 0x7D, 0x32))

# PMOS System
shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(3.5), Inches(3.2), Inches(6), Inches(1.5))
shape.fill.solid()
shape.fill.fore_color.rgb = BLUE
shape.line.fill.background()
tf = shape.text_frame
tf.word_wrap = True
tf.paragraphs[0].alignment = PP_ALIGN.CENTER
tf.paragraphs[0].text = "PMOS — Perpetual Multi-Agent Orchestration System"
tf.paragraphs[0].font.size = Pt(14)
tf.paragraphs[0].font.color.rgb = WHITE
tf.paragraphs[0].font.bold = True
p2 = tf.add_paragraph()
p2.text = "Natural language → Cross-domain analysis → Structured reports"
p2.font.size = Pt(10)
p2.font.color.rgb = RGBColor(0xCC, 0xDD, 0xFF)
p2.alignment = PP_ALIGN.CENTER

# External Systems
add_box(slide, 0.5, 5.5, 1.8, 0.9, "MySQL\nDatabases", RGBColor(0x1B, 0x5E, 0x20))
add_box(slide, 2.7, 5.5, 1.8, 0.9, "Neo4j\nGraph DB", RGBColor(0x1B, 0x5E, 0x20))
add_box(slide, 4.9, 5.5, 1.8, 0.9, "Document\nStore (Qdrant)", RGBColor(0x1B, 0x5E, 0x20))
add_box(slide, 7.1, 5.5, 1.8, 0.9, "External APIs\n(GitHub, REST)", RGBColor(0x1B, 0x5E, 0x20))
add_box(slide, 9.3, 5.5, 1.8, 0.9, "LLM Providers\n(OpenAI, etc.)", RGBColor(0x1B, 0x5E, 0x20))
add_box(slide, 11.3, 5.5, 1.5, 0.9, "Redis\nStreams", RGBColor(0x1B, 0x5E, 0x20))

# Arrows
add_arrow(slide, 2.6, 2.6, 5.5, 3.2, GRAY)
add_arrow(slide, 6.6, 2.6, 6.5, 3.2, GRAY)
add_arrow(slide, 10.6, 2.6, 7.5, 3.2, GRAY)
for x in [1.4, 3.6, 5.8, 8.0, 10.2, 12.0]:
    add_arrow(slide, x, 5.5, x, 4.7, GRAY)

# ==========================================
# SLIDE 5: C2 - Container Diagram
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.8, 0.2, 11, 0.5, "C2 — Container Diagram", 28, BLUE, True)
add_textbox(slide, 0.8, 0.65, 11, 0.35, "7 microservices + React frontend + 4 backing stores", 13, GRAY)

# Frontend
add_box(slide, 0.5, 1.3, 2.5, 0.7, "React Frontend\nPort 3000 | Vite + MUI", RGBColor(0x00, 0x97, 0xA7), 9)
# Gateway
add_box(slide, 3.5, 1.3, 2.5, 0.7, "API Gateway\nPort 4000 | Express + JWT", RGBColor(0x01, 0x57, 0x9B), 9)

# Backend Services Row 1
add_box(slide, 0.3, 2.6, 2.0, 1.0, "Orchestrator\nPort 8000\nFastAPI\nPipeline + Graph", BLUE, 8)
add_box(slide, 2.5, 2.6, 2.0, 1.0, "Agent-Mgmt\nPort 4001\nExpress\nCRUD + Execution", RGBColor(0x28, 0x63, 0x8A), 8)
add_box(slide, 4.7, 2.6, 2.0, 1.0, "Memory\nPort 8001\nFastAPI\n4-Tier Memory", PURPLE, 8)
add_box(slide, 6.9, 2.6, 2.0, 1.0, "RAG\nPort 8002\nFastAPI\nChunk + Embed", RGBColor(0x00, 0x69, 0x5C), 8)
add_box(slide, 9.1, 2.6, 2.0, 1.0, "Scoring\nPort 8003\nFastAPI\nRL + Bands", ORANGE, 8)
add_box(slide, 11.3, 2.6, 1.7, 1.0, "Meta-Assembly\nPort 8004\nFastAPI\nGap Detection", RGBColor(0x6A, 0x1B, 0x9A), 8)

# Backing Stores
add_box(slide, 0.3, 4.3, 2.5, 0.8, "MySQL 8.0\nPort 3306\n23 tables | Host-installed", RGBColor(0x33, 0x69, 0x1E), 8)
add_box(slide, 3.1, 4.3, 2.5, 0.8, "Neo4j AuraDB\nCloud (TLS)\nGraph: Tasks, Agents", RGBColor(0x33, 0x69, 0x1E), 8)
add_box(slide, 5.9, 4.3, 2.5, 0.8, "Qdrant\nPort 6333\nVector Store (RAG)", RGBColor(0x33, 0x69, 0x1E), 8)
add_box(slide, 8.7, 4.3, 2.5, 0.8, "Redis 7\nPort 6379\n7 Streams + Rate Limit", RGBColor(0x33, 0x69, 0x1E), 8)

# Data flow labels
add_textbox(slide, 0.3, 5.4, 12, 1.8,
    "Data Flow:\n"
    "User → Frontend → Gateway (auth + rate-limit) → Orchestrator → Pipeline\n"
    "Pipeline: Decompose → Negotiate (agents bid) → Execute (tool-use loop + sub-agents) → Score → Aggregate → Learn\n"
    "Streams: memory:writes (103) | scoring:feedback (30) | events:telemetry (210) | events:tool_health (41) | events:documents",
    10, GRAY)

# ==========================================
# SLIDE 6: C3 - Orchestrator Components
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.8, 0.2, 11, 0.5, "C3 — Orchestrator Component Diagram", 28, BLUE, True)
add_textbox(slide, 0.8, 0.65, 11, 0.35, "The brain of the system: 10-step pipeline with recursive sub-agent spawning", 13, GRAY)

# Pipeline steps
steps = [
    ("Step 0", "Load Team\nHierarchy", RGBColor(0x45, 0x5A, 0x64)),
    ("Steps 1-2", "LLM Task\nDecomposition", BLUE),
    ("Step 3", "Capability\nNegotiation", ORANGE),
    ("Steps 4-7", "Agentic\nTool Loop", GREEN),
    ("Step 8", "Result\nAggregation", PURPLE),
    ("Step 9", "Memory +\nRL Learning", RGBColor(0xC6, 0x28, 0x28)),
]

x = 0.4
for label, desc, color in steps:
    add_box(slide, x, 1.3, 2.0, 0.5, label, color, 9)
    add_box(slide, x, 1.9, 2.0, 0.6, desc, CARD_BG, 8)
    if x < 10.4:
        add_arrow(slide, x + 2.0, 1.55, x + 2.15, 1.55, GRAY)
    x += 2.1

# Component boxes
add_card(slide, 0.4, 3.0, 3.0, 1.5, "Capability Negotiation",
         "- Broadcast bid to all agents\n"
         "- LLM self-assessment per agent\n"
         "- Rank: 60% conf + 25% mem + 15% lat\n"
         "- Assign winner + fallback chain", ORANGE)

add_card(slide, 3.6, 3.0, 3.0, 1.5, "Agentic Tool-Use Loop",
         "- Max 5 iterations per agent\n"
         "- Tools: DB, Graph, API, Python, GitHub\n"
         "- spawn_sub_agent for delegation\n"
         "- Auto-continue truncated responses", GREEN)

add_card(slide, 6.8, 3.0, 3.0, 1.5, "Sub-Agent Spawning",
         "- Recursive (max depth 3)\n"
         "- Own context, tools, memory\n"
         "- Negotiated from team specialists\n"
         "- Result → parent as tool_result", BLUE)

add_card(slide, 10.0, 3.0, 3.0, 1.5, "Scoring & Correction",
         "- S = w1·R + w2·A + w3·P + w4·L + ...\n"
         "- Adaptive band: mean ± std × k\n"
         "- Below band → fallback agent\n"
         "- RL weight updates (Q-learning)", RED)

# Neo4j Graph
add_card(slide, 0.4, 4.8, 6.0, 2.0, "Neo4j Execution Graph",
         "TaskGraph → TaskNode (ROOT/SUBTASK/SUB_AGENT)\n"
         "  └─ SPAWNED_BY → parent TaskNode\n"
         "  └─ PRODUCED_EVENT → ExecutionEvent (BID_WON, SCORE, etc.)\n"
         "  └─ HAS_INTERACTION → AgentInteraction\n"
         "Agent → MEMBER_OF → Team\n\n"
         "Every execution creates a live, queryable graph", RGBColor(0x00, 0x69, 0x5C))

add_card(slide, 6.6, 4.8, 6.0, 2.0, "Memory Architecture",
         "SHORT_TERM:  Redis hash, TTL-based, session context\n"
         "LONG_TERM:   MySQL + FAISS, persistent knowledge\n"
         "REASONING:   MySQL JSON, distilled patterns\n"
         "EPISODIC:    MySQL + FAISS, full execution episodes\n\n"
         "All 4 tiers assembled into system prompt before every\n"
         "agent execution. Agents learn from past conversations.", PURPLE)

# ==========================================
# SLIDE 7: C4 - Code Level (Pipeline Flow)
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.8, 0.2, 11, 0.5, "C4 — Code-Level: Pipeline Execution Flow", 28, BLUE, True)

# Flow diagram using boxes and arrows
add_box(slide, 0.5, 1.2, 2.3, 0.6, "User Message\n(natural language)", RGBColor(0x2E, 0x7D, 0x32), 9)
add_arrow(slide, 2.8, 1.5, 3.1, 1.5, GRAY)
add_box(slide, 3.1, 1.2, 2.3, 0.6, "LLM Decompose\n→ TaskGraph", BLUE, 9)
add_arrow(slide, 5.4, 1.5, 5.7, 1.5, GRAY)
add_box(slide, 5.7, 1.2, 2.3, 0.6, "Negotiate\n(parallel bids)", ORANGE, 9)
add_arrow(slide, 8.0, 1.5, 8.3, 1.5, GRAY)
add_box(slide, 8.3, 1.2, 2.3, 0.6, "Winner Agent\n+ Fallback Chain", RGBColor(0x28, 0x63, 0x8A), 9)

add_arrow(slide, 9.45, 1.8, 9.45, 2.2, GRAY)

# Agent execution loop
shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.5), Inches(2.2), Inches(12), Inches(4.5))
shape.fill.solid()
shape.fill.fore_color.rgb = RGBColor(0x25, 0x25, 0x40)
shape.line.color.rgb = BLUE
shape.line.width = Pt(1)

add_textbox(slide, 0.7, 2.3, 3, 0.3, "AGENTIC TOOL-USE LOOP (max 5 iterations)", 11, BLUE, True)

add_box(slide, 0.8, 2.8, 2.2, 0.7, "Assemble Prompt\nMemory (4-tier)\n+ RAG docs", PURPLE, 8)
add_arrow(slide, 3.0, 3.15, 3.3, 3.15, GRAY)
add_box(slide, 3.3, 2.8, 2.2, 0.7, "LLM Call\n(with tools as\nfunction defs)", BLUE, 8)
add_arrow(slide, 5.5, 3.15, 5.8, 3.15, GRAY)

# Decision
add_box(slide, 5.8, 2.8, 2.0, 0.7, "LLM Response\nText or\nTool Calls?", ORANGE, 8)

# Text path
add_arrow(slide, 7.8, 2.95, 8.2, 2.95, GREEN)
add_box(slide, 8.2, 2.8, 1.8, 0.7, "Text Response\n→ Done\n→ Score", GREEN, 8)
add_arrow(slide, 10.0, 3.15, 10.3, 3.15, GRAY)
add_box(slide, 10.3, 2.8, 2.0, 0.7, "Score & Band\nCheck\n→ proceed/fix", RGBColor(0xC6, 0x28, 0x28), 8)

# Tool call path
add_arrow(slide, 6.8, 3.5, 6.8, 3.9, ORANGE)
add_textbox(slide, 6.2, 3.55, 1.5, 0.3, "tool calls", 8, ORANGE)

# Tool types
add_box(slide, 0.8, 4.0, 1.6, 0.7, "DATABASE\nMySQL query", RGBColor(0x33, 0x69, 0x1E), 8)
add_box(slide, 2.6, 4.0, 1.6, 0.7, "GRAPH\nNeo4j Cypher", RGBColor(0x33, 0x69, 0x1E), 8)
add_box(slide, 4.4, 4.0, 1.6, 0.7, "API / GITHUB\nHTTP calls", RGBColor(0x33, 0x69, 0x1E), 8)
add_box(slide, 6.2, 4.0, 1.6, 0.7, "PYTHON\nSandbox exec", RGBColor(0x33, 0x69, 0x1E), 8)

# spawn_sub_agent
add_box(slide, 8.0, 4.0, 2.2, 0.7, "spawn_sub_agent\n→ Negotiate\n→ Recurse (depth+1)", RGBColor(0xFF, 0x70, 0x43), 8)

add_arrow(slide, 9.1, 4.7, 9.1, 5.1, RGBColor(0xFF, 0x70, 0x43))
add_box(slide, 8.0, 5.1, 2.2, 0.7, "Sub-Agent Loop\n(own tools+memory)\nmax depth 3", RGBColor(0xBF, 0x36, 0x0C), 8)

# Result back
add_box(slide, 10.5, 4.0, 1.8, 0.7, "tool_result\n→ back to LLM\n→ next iteration", RGBColor(0x28, 0x63, 0x8A), 8)

# Bottom: output
add_box(slide, 3.0, 5.8, 3.0, 0.7, "Memory Write\n(episodic + Redis stream)", PURPLE, 8)
add_box(slide, 6.3, 5.8, 3.0, 0.7, "RL Feedback\n(scoring:feedback stream)", ORANGE, 8)
add_box(slide, 9.6, 5.8, 3.0, 0.7, "Final Response\n→ Gateway → User", GREEN, 8)

# ==========================================
# SLIDE 8: Use Cases
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.8, 0.4, 11, 0.6, "High-Value Use Cases", 32, BLUE, True)

cases = [
    ("Portfolio Risk Analysis", "\"How does our loan portfolio risk compare\nto the MBA industry forecast?\"", "Graph + Document (RAG)", GREEN),
    ("Compliance Cross-Check", "\"Which loans in CA and NY need enhanced\nTRID/TILA review per our policy memo?\"", "Graph + Document + MySQL", BLUE),
    ("Stress Testing", "\"Run a stress test on HELOC portfolio\nassuming rates increase 200bps\"", "Graph + Python + Policies", ORANGE),
    ("Market Intelligence", "\"Find open-source amortization tools and\ncompare their approaches to our models\"", "GitHub + Python + Database", PURPLE),
    ("Borrower 360", "\"Give me everything about LOAN001 —\nborrower, property, payments, compliance\"", "Neo4j Graph (single query)", RGBColor(0x00, 0x69, 0x5C)),
    ("Cross-Domain Report", "\"Top film revenues vs mortgage portfolio\nperformance with Python projections\"", "MySQL + Graph + Python + RAG", RED),
]

for i, (title, question, sources, color) in enumerate(cases):
    row = i // 3
    col = i % 3
    x = 0.5 + col * 4.2
    y = 1.4 + row * 2.8
    add_card(slide, x, y, 3.9, 2.4, title, f"{question}\n\nSources: {sources}", color)

# ==========================================
# SLIDE 9: Tech Stack
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.8, 0.4, 11, 0.6, "Technology Stack", 32, BLUE, True)

add_card(slide, 0.5, 1.3, 4.0, 2.5, "Frontend",
         "React 18 + TypeScript\n"
         "Vite (dev server, port 3000)\n"
         "Material UI 5\n"
         "D3.js (sequence diagrams, force graphs)\n"
         "React Query (data fetching)\n"
         "Zustand (state management)\n"
         "15 pages: Chat, Agent Studio, Monitors", BLUE)

add_card(slide, 4.7, 1.3, 4.0, 2.5, "Backend Services",
         "2 Node.js (Express 5 + TypeScript)\n"
         "  - Gateway (auth, routing, WebSocket)\n"
         "  - Agent-Mgmt (CRUD, tool execution)\n\n"
         "5 Python (FastAPI 0.109)\n"
         "  - Orchestrator, Memory, RAG,\n"
         "    Scoring, Meta-Assembly\n"
         "  - All Dockerized", GREEN)

add_card(slide, 8.9, 1.3, 4.0, 2.5, "Data Stores",
         "MySQL 8.0 — 23 tables\n"
         "  Agents, tools, scores, memory, docs\n\n"
         "Neo4j AuraDB — Cloud graph\n"
         "  Tasks, execution events, interactions\n\n"
         "Qdrant — Vector store (RAG)\n"
         "Redis 7 — Streams + rate limiting\n"
         "FAISS — Local vector backup", ORANGE)

add_card(slide, 0.5, 4.2, 4.0, 2.5, "AI & ML",
         "LLM: OpenAI GPT-4o / GPT-4o-mini\n"
         "  (pluggable: Anthropic, Google, Ollama)\n\n"
         "Embeddings: sentence-transformers\n"
         "  all-mpnet-base-v2 (768-dim)\n\n"
         "Re-ranking: cross-encoder/ms-marco\n\n"
         "RL: Q-learning weight updates\n"
         "Scoring: 6-factor weighted formula", PURPLE)

add_card(slide, 4.7, 4.2, 4.0, 2.5, "Document Processing",
         "PDF: PyPDF2 (text extraction)\n"
         "DOCX: python-docx (paragraphs + tables)\n"
         "XLSX: openpyxl (multi-sheet)\n"
         "HTML: BeautifulSoup4\n"
         "CSV, JSON, Markdown, TXT\n\n"
         "Chunking: fixed / sentence / paragraph\n"
         "Configurable chunk size + overlap\n"
         "Selectable embedding model", RGBColor(0x00, 0x69, 0x5C))

add_card(slide, 8.9, 4.2, 4.0, 2.5, "Infrastructure",
         "Docker Compose — 7 containers\n"
         "pmos.sh — service manager\n\n"
         "Observability:\n"
         "  Structured JSON logs (trace_id)\n"
         "  Prometheus metrics on every service\n"
         "  OpenTelemetry spans\n\n"
         "Circuit breakers + retry (tenacity)\n"
         "Redis Streams for async events", RGBColor(0x45, 0x5A, 0x64))

# ==========================================
# SLIDE 11: Business Domain Data (home lending)
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.5, 0.3, 12, 0.6, "Business Domain Data — Home Lending Lifecycle", 28, BLUE, True, PP_ALIGN.CENTER)
add_textbox(slide, 0.5, 0.9, 12, 0.4,
            "Six MySQL schemas modeling the full customer → origination → servicing journey, "
            "queryable end-to-end via registered DATABASE tools",
            13, GRAY, False, PP_ALIGN.CENTER)

# Lifecycle pipeline row
pipeline = [
    ("Chase My Home", "Explore / Buy / Manage", GREEN),
    ("Marketing", "Campaigns, leads, attribution", LIGHT_BLUE),
    ("Sales", "Officers, pipeline, commissions", LIGHT_BLUE),
    ("Origination", "Consumer + Correspondent", ORANGE),
    ("Servicing", "Loans, defaults, FC, REDS", PURPLE),
]
x = 0.35
w = 2.5
for i, (t, sub, c) in enumerate(pipeline):
    add_box(slide, x, 1.7, w, 1.1, f"{t}\n\n{sub}", fill_color=c, font_size=11)
    if i < len(pipeline) - 1:
        add_arrow(slide, x + w, 2.25, x + w + 0.1, 2.25, color=WHITE)
    x += w + 0.1

# Stats band
add_textbox(slide, 0.5, 3.2, 12, 0.5,
            "27 tables • 230 seed rows • 6 DATABASE tools registered in pmos.tools • cross-schema referential integrity",
            14, WHITE, True, PP_ALIGN.CENTER)

# Example insight cards
add_card(slide, 0.5, 4.0, 4.0, 2.9,
         "LIVE EXAMPLE",
         "Q: Which loans are in DEFAULT or FORECLOSURE?\n\n"
         "• L0007 Northern Light — $790K — Annaly REIT\n"
         "• L0009 Atlas — $340K — AGNC REIT\n\n"
         "Agent used servicing_db tool, returned deterministic SQL answer in 21s.",
         accent=PURPLE)

add_card(slide, 4.7, 4.0, 4.0, 2.9,
         "CROSS-SYSTEM QUERY",
         "Neo4j TaskGraphs joined with MySQL home-lending data.\n\n"
         "5 illustrative questions answered by scripts/cross_system_query.py:\n"
         "risk lifecycle, marketing funnel, investor distress exposure, agent routing.",
         accent=LIGHT_BLUE)

add_card(slide, 8.9, 4.0, 4.0, 2.9,
         "7 LAWS ENFORCED",
         "• LLM decomposes every request\n"
         "• Scoring bands adapt via RL\n"
         "• Prompts assembled at runtime\n"
         "• Every tool defined in MySQL\n"
         "• trace_id on every path",
         accent=GREEN)


# ==========================================
# SLIDE 12: Model Governance (inference traceability)
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.5, 0.3, 12, 0.6, "Model Governance — Inference Traceability", 28, BLUE, True, PP_ALIGN.CENTER)
add_textbox(slide, 0.5, 0.9, 12, 0.4,
            "For any answer the system produces, show the full layered reasoning chain",
            13, GRAY, False, PP_ALIGN.CENTER)

# Layered timeline mock
layers = [
    ("USER MESSAGE", BLUE),
    ("TASK NODE", PURPLE),
    ("PIPELINE STEP", LIGHT_BLUE),
    ("TOOL CALL", GREEN),
    ("SCORING", ORANGE),
    ("RL FEEDBACK", RED),
    ("AGENT INTERACTION", CARD_BG),
    ("ASSISTANT RESPONSE", GREEN),
]
y = 1.6
for lab, col in layers:
    add_box(slide, 1.0, y, 3.0, 0.4, lab, fill_color=col, font_size=11)
    add_textbox(slide, 4.3, y + 0.05, 8, 0.3,
                f"→ tracked in MySQL + Neo4j, joined on trace_id", 11, GRAY)
    y += 0.55

# Endpoint card
add_card(slide, 0.5, 6.3, 12.3, 1.0,
         "GET /v1/governance/traces/{trace_id}",
         "Aggregates messages, execution_graph_log, tool_execution_history, score_history, "
         "rl_feedback_log, TaskNodes, AgentInteractions into one time-sorted timeline. "
         "Used to diagnose the v2 'silent fallback' bug and prove v3 agents actually called servicing_db.",
         accent=GREEN)


# ==========================================
# SLIDE 13: ML Insights (learning loop observability)
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.5, 0.3, 12, 0.6, "ML Insights — Self-Improving Orchestration", 28, BLUE, True, PP_ALIGN.CENTER)
add_textbox(slide, 0.5, 0.9, 12, 0.4,
            "Four learning loops tapped into the pipeline, all visible in one operator page",
            13, GRAY, False, PP_ALIGN.CENTER)

# Four quadrants
add_card(slide, 0.5, 1.5, 6.0, 2.6,
         "1A — Contextual Bandits (SHADOW)",
         "Thompson Sampling over Beta(α, β) per (agent, context).\n"
         "Hooked into Step 3 negotiation. Logs what the bandit would pick alongside "
         "the bid winner. Flipping to LIVE is one line once arms reach 20 pulls.\n"
         "60% baseline prior per operator request.",
         accent=PURPLE)

add_card(slide, 6.8, 1.5, 6.0, 2.6,
         "2C — Node2Vec TaskNode Embeddings",
         "Real Node2Vec (networkx + gensim) over Neo4j TaskGraph.\n"
         "595 nodes embedded across 116 graphs.\n"
         "Feeds the learned scorer; reusable feature surface for future GNN work.\n"
         "Pure-Python spectral-embedding fallback for zero-dep inference.",
         accent=LIGHT_BLUE)

add_card(slide, 0.5, 4.3, 6.0, 2.6,
         "1B — Learned Quality Scorer (SHADOW)",
         "Logistic regression trained offline on thumbs-up/down + 60% bootstrap.\n"
         "val_accuracy 0.786, val_auc 0.875 on the first 70 samples.\n"
         "Pure-Python sigmoid inference in orchestrator container (no numpy/sklearn).\n"
         "22 shadow predictions logged per conversation.",
         accent=ORANGE)

add_card(slide, 6.8, 4.3, 6.0, 2.6,
         "2D — SOP Auto-Discovery",
         "TF-IDF + DBSCAN clustering of recent user messages.\n"
         "8 proposals produced from 40 real messages on first run.\n"
         "Human-in-loop review: Promote writes SOPNode into Neo4j, "
         "Reject/Correct feed reinforcement signal.",
         accent=GREEN)


# ==========================================
# SLIDE 14: Data Catalog (systems integration)
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.5, 0.3, 12, 0.6, "Data Catalog — Semantic Knowledge Graph", 28, BLUE, True, PP_ALIGN.CENTER)
add_textbox(slide, 0.5, 0.9, 12, 0.4,
            "Crawl physical metadata → LLM maps to business ontology → auditor RL feedback loop",
            13, GRAY, False, PP_ALIGN.CENTER)

# Flow row
flow = [
    ("CRAWL", "INFORMATION_SCHEMA", LIGHT_BLUE),
    ("MAP", "LLM proposes\nDomain/Entity/Attribute", ORANGE),
    ("WRITE", "Neo4j ontology\n+ MySQL audit", PURPLE),
    ("REVIEW", "Auditor:\nconfirm/correct/reject", GREEN),
    ("FEEDBACK", "RL reward\n+1 / −0.5 / −1", RED),
]
x = 0.4
w = 2.4
for i, (t, sub, c) in enumerate(flow):
    add_box(slide, x, 1.7, w, 1.2, f"{t}\n\n{sub}", fill_color=c, font_size=11)
    if i < len(flow) - 1:
        add_arrow(slide, x + w, 2.3, x + w + 0.1, 2.3, color=WHITE)
    x += w + 0.1

# Stats
add_textbox(slide, 0.5, 3.2, 12, 0.5,
            "Phase 1: MySQL crawler → pmos_servicing • 9 assets • 63 columns • 63 auto-mappings in 44s",
            14, WHITE, True, PP_ALIGN.CENTER)

# Node labels card
add_card(slide, 0.5, 4.0, 6.0, 2.9,
         "KNOWLEDGE GRAPH ONTOLOGY",
         "(:DataSource)─[HAS_ASSET]→(:DataAsset)\n"
         "           ─[HAS_COLUMN]→(:DataColumn)\n\n"
         "(:BusinessDomain)─[HAS_ENTITY]→(:BusinessEntity)\n"
         "              ─[HAS_ATTRIBUTE]→(:BusinessAttribute)\n"
         "                      ─[MAPS_TO]→(:DataColumn)\n\n"
         "(:DataColumn)─[REFERENCES]→(:DataColumn)  (physical FK)",
         accent=BLUE)

add_card(slide, 6.8, 4.0, 6.0, 2.9,
         "LIVE RESULTS",
         "• Domain: Servicing\n"
         "• Entities: Loan, Payment, Investor, Default,\n"
         "  Bankruptcy, Foreclosure, EarlyResolution,\n"
         "  RiskAssessment, RegulatoryFiling\n"
         "• avg confidence: 0.957\n"
         "• LLM enriched: term_months → loan_term_months,\n"
         "  origination_ref → origination_reference",
         accent=GREEN)


# ==========================================
# SLIDE 15: Market Category
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.5, 0.3, 12, 0.6, "Market Category — Semantic Layer for Federated Data", 26, BLUE, True, PP_ALIGN.CENTER)
add_textbox(slide, 0.5, 0.9, 12, 0.4,
            "What we're building has a name — and several marketing labels — depending on which slice the vendor is selling",
            13, GRAY, False, PP_ALIGN.CENTER)

# Marketing label table (left) + the common loop (right)
add_textbox(slide, 0.5, 1.6, 6.0, 0.3, "MARKETING LABELS", 12, LIGHT_BLUE, True)
labels = [
    ("Semantic layer", "dbt, Cube, AtScale, Looker, Power BI"),
    ("Universal semantic layer", "Cube, AtScale (vendor-neutral)"),
    ("Metric layer / metric store", "dbt MetricFlow"),
    ("Data catalog with AI", "Alation, Collibra, Atlan, Informatica"),
    ("Knowledge graph for data", "Stardog, data.world, Neo4j, Anzo"),
    ("Conversational analytics", "ThoughtSpot, Tableau, Hex, Mode"),
    ("Text-to-SQL", "Defog, Vanna, WrenAI, Numbers Station"),
    ("Cortex Analyst", "Snowflake (first-party, late 2024)"),
]
y = 2.0
for lbl, vendors in labels:
    add_textbox(slide, 0.5, y, 2.6, 0.32, lbl, 11, WHITE, True)
    add_textbox(slide, 3.1, y, 3.3, 0.32, vendors, 10, GRAY)
    y += 0.42

# The common loop on the right
add_textbox(slide, 7.0, 1.6, 6.0, 0.3, "THE COMMON LOOP — EVERYONE IMPLEMENTS THIS", 12, LIGHT_BLUE, True)
loop_steps = [
    ("1  CRAWL",   "physical metadata from sources",    LIGHT_BLUE),
    ("2  MAP",     "to a semantic layer (LLM + human)", ORANGE),
    ("3  STORE",   "in a graph / catalog / git",        PURPLE),
    ("4  RETRIEVE","relevant semantic context",         GREEN),
    ("5  GENERATE","SQL / SPARQL / Cypher / KQL",       BLUE),
    ("6  EXECUTE", "+ self-correct / re-rank",          GREEN),
]
y = 2.0
for t, sub, c in loop_steps:
    add_box(slide, 7.0, y, 2.0, 0.42, t, fill_color=c, font_size=11)
    add_textbox(slide, 9.15, y + 0.07, 4.0, 0.3, sub, 11, GRAY)
    y += 0.52

add_textbox(slide, 7.0, 5.4, 6.0, 1.0,
            "Differentiation lives in the details of steps 2 (mapping quality), "
            "4 (retrieval relevance), and 5 (generation grounding). "
            "PMOS shares the loop — it competes on how it implements each step.",
            11, WHITE, False)


# ==========================================
# SLIDE 16: Competitive Landscape — 6 Groups
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.5, 0.3, 12, 0.6, "Competitive Landscape — Six Groups of Players", 26, BLUE, True, PP_ALIGN.CENTER)
add_textbox(slide, 0.5, 0.9, 12, 0.4,
            "The category is real and crowded; vendors that started in different buckets are converging on the same shape",
            13, GRAY, False, PP_ALIGN.CENTER)

# 2x3 grid of cards
add_card(slide, 0.4, 1.4, 4.15, 2.7,
         "1. KNOWLEDGE-GRAPH NATIVE",
         "Closest architectural cousins to PMOS.\n\n"
         "• Stardog — RDF KG + Voicebox NL→SPARQL\n"
         "• data.world — graph-native, regulated industries\n"
         "• Anzo (Cambridge Semantics) — enterprise KG\n"
         "• Neo4j — GraphRAG framework + reference arch\n\n"
         "Years on ontology + entity resolution.",
         accent=PURPLE)

add_card(slide, 4.7, 1.4, 4.15, 2.7,
         "2. MODERN DATA CATALOGS",
         "Catalogs catching up by bolting LLMs on top.\n\n"
         "• Alation — Alation Aurora\n"
         "• Collibra — Collibra AI\n"
         "• Atlan — most aggressive AI positioning\n"
         "• Informatica — CLAIRE GPT\n\n"
         "Strong on metadata + distribution; thin AI layers.",
         accent=BLUE)

add_card(slide, 9.0, 1.4, 4.15, 2.7,
         "3. SEMANTIC / METRIC LAYER",
         "Define metrics in code, query through them.\n\n"
         "• dbt Labs — Semantic Layer + MetricFlow\n"
         "• Cube — universal semantic layer\n"
         "• AtScale — enterprise semantic layer\n"
         "• Looker (Google) — LookML + Gemini\n"
         "• Power BI / Tableau — Copilot + Pulse\n\n"
         "Strong BI; weak on cross-source federation.",
         accent=ORANGE)

add_card(slide, 0.4, 4.25, 4.15, 2.7,
         "4. TEXT-TO-SQL OSS",
         "Most directly comparable to PMOS internals.\n\n"
         "• WrenAI (Canner) — closest architecturally\n"
         "• Vanna.ai — RAG-to-SQL, simpler\n"
         "• Defog SQLCoder — fine-tuned SQL models\n"
         "• Numbers Station — foundation-model approach\n"
         "• Dataherald — pluggable NL-to-SQL\n\n"
         "Read WrenAI's codebase before adding crawlers.",
         accent=GREEN)

add_card(slide, 4.7, 4.25, 4.15, 2.7,
         "5. CLOUD PLATFORMS",
         "Late but heavy hitters; will commoditize the easy 80%.\n\n"
         "• Snowflake Cortex Analyst (late 2024)\n"
         "• Databricks Genie\n"
         "• BigQuery + Gemini\n"
         "• AWS Q for Business (laggard, fragmented)\n\n"
         "Polished for their own data; "
         "weak on legacy systems they don't own.",
         accent=RED)

add_card(slide, 9.0, 4.25, 4.15, 2.7,
         "6. IN-HOUSE ENTERPRISE",
         "Case studies, not products; prove pattern at scale.\n\n"
         "• Uber QueryGPT — multi-agent, well-documented\n"
         "• LinkedIn DARWIN / SQLGen\n"
         "• Pinterest Querybot\n"
         "• Airbnb internal text-to-SQL\n"
         "• Meta + Stripe internal versions\n\n"
         "Architectures public via papers and posts.",
         accent=LIGHT_BLUE)


# ==========================================
# SLIDE 17: Where PMOS Differentiates
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.5, 0.3, 12, 0.6, "Where PMOS Does What Others Don't", 26, BLUE, True, PP_ALIGN.CENTER)
add_textbox(slide, 0.5, 0.9, 12, 0.4,
            "Three differences that make PMOS more than yet-another text-to-SQL tool",
            13, GRAY, False, PP_ALIGN.CENTER)

add_card(slide, 0.5, 1.6, 4.0, 5.4,
         "1. MULTI-AGENT BIDDING + RL",
         "None of the named products treat agent selection "
         "as a contextual bandit.\n\n"
         "They have ONE LLM (or a fixed router) doing everything.\n\n"
         "PMOS has a population of agents that:\n"
         "• Compete for tasks via bidding\n"
         "• Get scored after execution\n"
         "• Receive RL feedback (rewards)\n"
         "• Converge over time\n\n"
         "Catalog vendors don't think this way at all — "
         "their world is one agent answering one question.",
         accent=PURPLE)

add_card(slide, 4.7, 1.6, 4.0, 5.4,
         "2. INFERENCE TRACEABILITY UI",
         "The Model Governance page shows the full hop-by-hop "
         "reasoning chain:\n\n"
         "user → bid → task nodes → tool calls → scoring → "
         "RL feedback → response\n\n"
         "as a layered timeline an operator can read like a "
         "flight recorder.\n\n"
         "Stardog and data.world come closest because the "
         "knowledge graph naturally records the path — "
         "but neither surfaces it as a UI the way PMOS does.",
         accent=GREEN)

add_card(slide, 8.9, 1.6, 4.0, 5.4,
         "3. AGENTS + DATA IN ONE GRAPH",
         "Most products keep the catalog (data side) and the "
         "orchestration runtime (agent side) in SEPARATE stores.\n\n"
         "PMOS puts in ONE Neo4j instance:\n"
         "• TaskNode + AgentInteraction (runtime)\n"
         "• BusinessEntity + DataAsset (catalog)\n"
         "• MAPS_TO + SPAWNED_BY edges\n\n"
         "The bet: the JOIN between 'what the agent did' "
         "and 'what the data means' is itself a useful query "
         "target — and the system that learns from its own "
         "behavior needs that join.",
         accent=ORANGE)


# ==========================================
# SLIDE 18: Honest Gaps + Strategic Positioning
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 0.5, 0.3, 12, 0.6, "Honest Gaps and Strategic Positioning", 26, BLUE, True, PP_ALIGN.CENTER)
add_textbox(slide, 0.5, 0.9, 12, 0.4,
            "What others do better than PMOS today, and where PMOS should choose to compete",
            13, GRAY, False, PP_ALIGN.CENTER)

# Two columns
add_card(slide, 0.5, 1.5, 6.0, 3.0,
         "WHAT OTHERS DO BETTER",
         "• Ontology curation tooling — Stardog, Atlan: years of "
         "entity resolution, glossary, lineage propagation\n"
         "• Connector library — Alation/Collibra/Atlan/Informatica "
         "have hundreds of connectors; PMOS has one (MySQL)\n"
         "• Enterprise security — column ACLs, masking, ABAC, "
         "audit-log compliance\n"
         "• BI tool integration — dbt/Cube/AtScale plug into "
         "Tableau, Power BI, Looker, ThoughtSpot natively",
         accent=RED)

add_card(slide, 6.8, 1.5, 6.0, 3.0,
         "WHERE PMOS SHOULD COMPETE",
         "NOT 'another text-to-SQL on Snowflake' — that race is "
         "over before it starts (Cortex Analyst already won).\n\n"
         "INSTEAD: 'Multi-agent reasoning system with KG-based "
         "semantic substrate, full inference traceability, and "
         "RL-driven self-improvement, designed for FEDERATED data "
         "estates the cloud vendors don't own.'\n\n"
         "Buyers: financial services, healthcare, government, "
         "large industrials — anywhere data sprawls across "
         "30 systems no one will migrate.",
         accent=GREEN)

# Bottom strip — three things to watch
add_textbox(slide, 0.5, 4.8, 12, 0.4, "THREE COMPETITORS TO WATCH CLOSELY", 14, LIGHT_BLUE, True, PP_ALIGN.CENTER)
add_box(slide, 0.5, 5.3, 4.1, 1.8,
        "WrenAI (open source)\n\n"
        "Architecturally closest. If they add the agent-bidding "
        "layer, they become a direct competitor.",
        fill_color=CARD_BG, font_size=11)
add_box(slide, 4.7, 5.3, 4.1, 1.8,
        "Snowflake Cortex Analyst\n\n"
        "If they make it easy to register external sources via "
        "their semantic model, they capture every Snowflake customer.",
        fill_color=CARD_BG, font_size=11)
add_box(slide, 8.9, 5.3, 4.1, 1.8,
        "Atlan (catalog vendor)\n\n"
        "Most likely catalog vendor to add a governance trace UI. "
        "If they ship it, the differentiation gap closes on that axis.",
        fill_color=CARD_BG, font_size=11)


# ==========================================
# SLIDE 19: Summary
# ==========================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_textbox(slide, 1, 0.6, 11, 1.0, "PMOS", 54, BLUE, True, PP_ALIGN.CENTER)
add_textbox(slide, 1, 1.8, 11, 0.6,
            "Connect any data source. Ask any question.\nGet deterministic answers in minutes, not hours.",
            22, WHITE, False, PP_ALIGN.CENTER)

add_textbox(slide, 1.5, 3.0, 10, 3.7,
    "7 microservices  |  4 data stores  |  6 agents  |  7 Redis streams\n\n"
    "Home-lending business domain — 6 schemas, 27 tables  |  Cross-system queries\n\n"
    "Model Governance — full inference traceability per trace_id\n\n"
    "ML Insights — bandits, Node2Vec, learned scorer, SOP discovery, shadow-mode\n\n"
    "Data Catalog — metadata crawler + semantic KG + auditor RL feedback\n\n"
    "Positioning: federated reasoning system, NOT text-to-SQL-on-Snowflake\n\n"
    "Closest cousins: Stardog, data.world, WrenAI  |  Watch: Cortex, Atlan",
    14, GRAY, False, PP_ALIGN.CENTER)

add_textbox(slide, 3, 6.85, 7, 0.5,
            "github.com/kreonakrish/pmos  |  localhost:3000",
            13, LIGHT_BLUE, False, PP_ALIGN.CENTER)

# Save
output_path = os.path.join(os.path.dirname(__file__), "..", "PMOS_Architecture_Presentation.pptx")
prs.save(output_path)
print(f"Saved: {output_path}")
