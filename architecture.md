# Pecan Architecture

## System Overview

Pecan is a two-loop autonomous multi-agent system built with LangGraph. It takes a single event brief and executes an entire alumni engagement campaign without human intervention.

## Two-Loop Design

### Loop 1: Understand → Match (Human-in-the-loop for brief only)

The Brief Analyst runs as a separate conversational agent outside the LangGraph pipeline. Once the user confirms their brief, the parsed output is passed into the pipeline.

```
Brief Analyst (conversation)
        │
        ▼ confirmed parsed brief
┌─── LOOP 1 ──────────────────────────────────────┐
│                                                   │
│  Data Integrator ──► Matching Agent ──► Quality   │
│                                         Checker   │
│                                                   │
│  • Salesforce API     • ChromaDB vector    • Dup  │
│  • Eventbrite API       search               check│
│  • CSV/Excel/PDF      • Algorithmic        • GDPR │
│  • Deduplication        scoring (0-100)      check│
│  • ChromaDB embed     • LLM reasoning      • Over-│
│                         on top candidates    rep   │
│                                              check │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼ 5X alumni pool, quality-checked
```

**Data Integrator** pulls from all configured sources (Salesforce, Eventbrite, file uploads), normalises records to a common schema, deduplicates by email, filters by GDPR consent, and loads into SQLite + ChromaDB.

**Matching Agent** runs three stages: (1) ChromaDB semantic search for initial candidates, (2) deterministic algorithmic scoring across 5 dimensions, (3) LLM reasoning on anonymised top candidates. Saves all matches with scores and reasoning.

**Quality Checker** reviews the selected pool for duplicates, company over-representation, low-confidence matches, GDPR compliance, and outreach fatigue. Returns pass/fail with detailed flags.

### Loop 2: Personalise → Outreach → Track → Adapt (Fully autonomous, up to 4 cycles)

```
┌─── LOOP 2 (up to 4 cycles) ─────────────────────┐
│                                                   │
│  Calculate    ──► Personalisation ──► Outreach    │
│  Batch            Agent               Agent       │
│  (Scenario                            (Send +     │
│   A or B)                              bounce)    │
│       ▲                                   │       │
│       │                                   ▼       │
│       │                              Response     │
│       │                              Tracker      │
│       │                              (Accept/     │
│       │                               open/none)  │
│       │                                   │       │
│       └── if goal not met ◄───────────────┘       │
│                                                   │
└──────────────────────┬───────────────────────────┘
                       │ goal met OR max cycles
                       ▼
```

**Calculate Batch** determines how many alumni to contact this cycle. Cycle 1 sends top 2X. Later cycles use Scenario A (aggressive, 2X more) or Scenario B (moderate, 1.5X) based on progress toward the acceptance target.

**Personalisation Agent** generates unique emails per alumnus using the LLM. Each email references 2+ profile details. On cycle 2+, it adjusts based on the Response Tracker's diagnosis (e.g., "rewrite subject lines", "add urgency"). Also generates follow-up emails for warm leads.

**Outreach Agent** simulates email delivery. Marks messages as SENT or BOUNCED (weighted by engagement score). No LLM needed.

**Response Tracker** simulates responses using declining acceptance rates per cycle (35% → 25% → 18% → 12%). Categorises responses as ACCEPTED (counts toward target), OPENED (warm lead for follow-up), or NO_RESPONSE. If the goal isn't met, it diagnoses the issue via LLM and determines the scenario for the next cycle.

### Phase 3: Report → Learn

```
┌─── PHASE 3 ──────────────────────────────────────┐
│                                                   │
│  Campaign Reporter                                │
│  • Full funnel analysis (pool → sent → accepted)  │
│  • Per-cycle metrics vs expected rates             │
│  • Segment breakdown (dept, year, industry, city)  │
│  • LLM-generated insights and recommendations     │
│  • Stores to campaign_memory for future campaigns  │
│                                                   │
└──────────────────────────────────────────────────┘
```

**Campaign Reporter** analyses the complete campaign, generates an LLM-powered report with insights, identifies best-performing segments, and stores lessons in campaign_memory. Future campaigns read this memory to improve targeting.

## Agent Roster

| Agent | LLM Used | Key Responsibility |
|---|---|---|
| Brief Analyst | Yes (Kimi K2) | Conversational brief collection via multi-turn chat |
| Data Integrator | No | Multi-source ingestion, normalisation, deduplication |
| Matching Agent | Yes (Kimi K2) | Vector search + algorithmic scoring + LLM reasoning |
| Quality Checker | Yes (Kimi K2) | Pre-outreach QA with 5 automated checks |
| Personalisation Agent | Yes (Kimi K2) | Per-alumnus personalised email generation |
| Outreach Agent | No | Simulated send with engagement-weighted bounce modelling |
| Response Tracker | Yes (Kimi K2) | Acceptance tracking, warm lead identification, cycle diagnosis |
| Campaign Reporter | Yes (Kimi K2) | Full funnel analysis, segment breakdown, memory storage |

## Matching Algorithm

### Stage 1: Vector Search
ChromaDB semantic search using event description (type + topic + location + constraints) to find the most relevant alumni profiles. Returns up to 5X + 50 candidates.

### Stage 2: Algorithmic Scoring (0-100)
Deterministic Python scoring across 5 dimensions:
- **Topic/industry alignment (40%)**: Keyword overlap between event topic and alumni's industry + interests
- **Location match (20%)**: Does the alumni's city match the event city?
- **Graduation recency (15%)**: Scaled by audience constraints (e.g., "recent graduates" favours last 3 years)
- **Engagement score (15%)**: Direct use of the alumni's historical engagement score
- **Vector similarity (10%)**: Normalised ChromaDB distance score

### Stage 3: LLM Reasoning
Top candidates (capped at 20) are anonymised via the GDPR layer, sent to Kimi K2 in batches, and each receives a one-sentence reasoning explanation. Identities are re-attached after LLM processing.

## Outreach Algorithm

- **Target acceptances**: 1.2× target attendance (20% buffer for no-shows)
- **Total pool**: 5× target attendance
- **Cycle 1**: Top 2X from pool, expected 35% acceptance rate
- **Cycle 2+**: Scenario A (≤50% of target met → aggressive 2X batch) or Scenario B (>50% → moderate 1.5X)
- **Acceptance rates decline**: 35% → 25% → 18% → 12% (best matches contacted first)
- **Only full RSVPs count as acceptances** — opens and clicks are warm leads, not acceptances

## GDPR Design

1. **Anonymisation before LLM**: `anonymise_for_llm()` strips name and email before any data reaches the LLM. The model only sees: id, graduation_year, degree, department, location, industry, interests, engagement_score.
2. **Identity re-attachment**: `reattach_identity()` restores PII after LLM processing, only at the email generation step.
3. **Consent filtering**: Every pipeline stage filters by `gdpr_consent=1` and `email_valid=1`.
4. **Audit trail**: Every GDPR action is logged to `agent_log` with agent_name="GDPR Compliance".
5. **Data sovereignty**: Open-source model (Kimi K2) can be self-hosted. SQLite database stays local. No alumni data leaves the infrastructure.

## Database Schema

### Core Tables
- **alumni**: 250 mock profiles with name, email, graduation_year, degree, department, location, job_title, company, industry, interests, engagement_score, gdpr_consent, email_valid, past_events
- **events**: Event records with type, topic, date, location, capacity
- **campaigns**: Campaign lifecycle with status, brief, target metrics, cycle tracking, phase
- **matches**: Per-alumnus match scores and LLM reasoning
- **outreach_messages**: Personalised emails with delivery status tracking

### Cycle Tracking
- **cycles**: Per-cycle metrics (batch size, sent, bounced, accepted, expected vs actual rates)
- **warm_leads**: Alumni who opened/clicked but didn't accept (prioritised for follow-up)

### Intelligence
- **agent_log**: Every agent decision, timestamped, with reasoning (47+ entries per campaign)
- **campaign_memory**: Cross-campaign insights for continuous improvement

## Smart Rate Limiting

The `SmartLLMRouter` manages Groq API calls:
- Tracks timestamps of all calls in a sliding 60-second window
- Fires at full speed until approaching 28 calls/minute (leaving headroom below Groq's 30 RPM limit)
- When at capacity, pauses for the minimum time needed before the oldest call expires
- 4-second cooldown between calls to respect token-per-minute limits
- All agents share one singleton router instance

## Technology Choices

| Component | Technology | Rationale |
|---|---|---|
| LLM | Kimi K2 via Groq | Open-source, 1T params, built for agentic tool-calling, 200 tok/sec on Groq LPU |
| Orchestration | LangGraph | Conditional routing, state management, two-loop architecture |
| Structured DB | SQLite (WAL mode) | Local-first, GDPR-friendly, no external dependencies |
| Vector DB | ChromaDB | Built-in embeddings, semantic search, zero configuration |
| API | FastAPI | Async Python, auto-docs, WebSocket support |
| Rate Limiting | Custom SmartLLMRouter | Token bucket algorithm with automatic pacing |
