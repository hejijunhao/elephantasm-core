<div align="center">

![Elephantasm](lightfinder.png)

# Elephantasm

**Long-term memory for AI agents.**
Structured. Deterministic. Auditable.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776AB.svg)](https://www.python.org)
[![PyPI](https://img.shields.io/pypi/v/elephantasm)](https://pypi.org/project/elephantasm/)
[![npm](https://img.shields.io/npm/v/@elephantasm/client)](https://www.npmjs.com/package/@elephantasm/client)

[Website](https://elephantasm.com) &middot; [Docs](https://elephantasm.com/docs) &middot; [PyPI](https://pypi.org/project/elephantasm/) &middot; [npm](https://www.npmjs.com/package/@elephantasm/client)

</div>

---

## The Problem

AI agents are stateless. Every conversation starts from scratch, every context window eventually overflows, every interaction is forgotten.

Current approaches don't solve this:

| Approach | What it does | Where it falls short |
|----------|-------------|----------------------|
| **Context windows** | Stuff recent messages in | Fixed size, no distillation, cost grows linearly |
| **RAG** | Retrieve documents by similarity | No transformation — finds text, doesn't form understanding |
| **Vector stores** | Nearest-neighbor lookup | No lifecycle, no curation, no structure beyond embeddings |
| **Chat history** | Log everything to a database | No synthesis — 10,000 messages is not memory, it's a log file |

Memory is not retrieval. Memory is *transformation* — sensation becomes experience, experience becomes understanding, understanding shapes identity.

Elephantasm is an open-source framework for **Long-Term Agentic Memory (LTAM)**. It transforms raw agent interactions into layered, evolving understanding through deterministic, auditable processes.

---

## How It Works

Elephantasm builds a layered memory hierarchy. Each layer transforms into the next — raw signals become structured understanding over time:

```
              ┌─────────┐
              │  Event   │  Raw interactions (messages, tool calls, system events)
              └────┬─────┘
                   │
                   │  threshold-gated LLM synthesis
                   │
              ┌────▼─────┐
              │  Memory   │  Structured reflections with four-factor scoring
              └────┬─────┘
                   │
                   │  automatic knowledge extraction
                   │
              ┌────▼──────┐
              │ Knowledge  │  Canonicalized truths (facts, concepts, methods, principles)
              └────┬──────┘
                   │
                   │  emergent over time via Dreamer curation
                   │
              ┌────▼──────┐
              │  Identity  │  Behavioral fingerprint — personality, style, self-awareness
              └───────────┘
```

Every memory traces back to its source events. Every knowledge item traces back to its source memory. Nothing is a black box.

---

### Memory Synthesis

Events don't immediately become memories. Elephantasm uses an **accumulation score** to decide *when* synthesis should trigger — preventing both wasted LLM calls on noise and important context slipping away.

```
score = (hours_elapsed x time_weight) + (new_events x event_weight) + (new_tokens x token_weight)
```

When the score crosses a configurable threshold, a LangGraph workflow collects pending events, calls an LLM to synthesize them into a structured memory, generates a vector embedding, and links the new memory back to its source events for provenance.

```
Default weights (configurable per agent):

  time_weight   = 1.0       1 point per hour since last synthesis
  event_weight  = 0.5       0.5 points per new event
  token_weight  = 0.0003    ~1 point per 3,333 tokens
  threshold     = 10.0      trigger when score reaches 10

Scenario A:  10 hours × 1.0  +  0 events × 0.5  =  10.0  →  synthesize
Scenario B:   3 hours × 1.0  + 14 events × 0.5  =  10.0  →  synthesize
Scenario C:   2 hours × 1.0  +  5 events × 0.5  =   4.5  →  wait
```

Zero-event periods are detected and skipped — the system won't hallucinate memories from silence.

```
                              ┌──────────────────────┐
                              │ calculate_accumulation│
                              │       _score          │
                              └──────────┬───────────┘
                                         │
                              ┌──────────▼───────────┐
                              │   check_threshold     │
                              └──────┬─────────┬─────┘
                                     │         │
                          score >= threshold   score < threshold
                                     │         │
                          ┌──────────▼──┐   ┌──▼──┐
                          │   collect    │   │ END │  skip, reset checkpoint
                          │   events    │   └─────┘
                          └──────┬──────┘
                                 │
                          ┌──────▼──────┐
                          │ synthesize  │  LLM generates structured memory
                          │  (LLM)     │  with importance + confidence scores
                          └──────┬──────┘
                                 │
                          ┌──────▼──────┐
                          │   persist   │  store memory, embedding, provenance links
                          └──────┬──────┘
                                 │
                               ┌─▼──┐
                               │END │
                               └────┘
```

---

### Knowledge Extraction

When a memory is created, a second workflow automatically extracts knowledge. Knowledge is typed across five **epistemic categories**, enabling structured retrieval beyond simple similarity search:

```
Memory: "User explained they're migrating from MongoDB to PostgreSQL
         because they need ACID transactions for their payment system."

Extracted knowledge:

  FACT        User is migrating from MongoDB to PostgreSQL
  PRINCIPLE   ACID transactions are required for payment systems
  METHOD      Database migration as a reliability improvement strategy
```

| Type | What it represents |
|------|--------------------|
| **Fact** | Verifiable truth about the external world |
| **Concept** | Abstract framework or mental model |
| **Method** | Procedural or causal understanding |
| **Principle** | Guiding belief or normative rule |
| **Experience** | Personal, lived knowledge |

Knowledge items carry their own embeddings and confidence scores. Each traces back to the memory it was extracted from.

---

### The Dreamer

The Dreamer is a background curation loop — inspired by how biological memory consolidation works during sleep. It runs in two phases:

```
┌─────────────────────────────────────────────────────────────┐
│                       DREAMER LOOP                          │
│                                                             │
│  Phase 1: Light Sleep (Algorithmic)                         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Update decay and recency scores across all memories   │ │
│  │  Transition stale memories:  ACTIVE  →  DECAYING       │ │
│  │  Pure math — no LLM calls, no token cost               │ │
│  └────────────────────────────────────────────────────────┘ │
│                            │                                │
│                            ▼                                │
│  Phase 2: Deep Sleep (LLM-Powered)                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Merge overlapping memories             (N → 1)        │ │
│  │  Split compound memories                (1 → N)        │ │
│  │  Refine content, importance, confidence                │ │
│  │  Archive or retire stale entries                       │ │
│  │                                                        │ │
│  │  Every mutation records a DreamAction:                  │ │
│  │    · source memory IDs                                 │ │
│  │    · result memory IDs (for merges/splits)             │ │
│  │    · before/after state snapshots                      │ │
│  │    · LLM reasoning                                     │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

The Dreamer ensures the memory system doesn't just grow — it *evolves*. Noise is retired. Overlaps are consolidated. Important patterns are reinforced. And every transformation is recorded in a full audit trail, so you can inspect exactly why the Dreamer merged two memories, what they looked like before and after, and what reasoning it used.

---

### Pack Compiler

When your agent needs context, the Pack Compiler assembles a **memory pack** — a structured, token-budgeted context bundle built from four layers:

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Identity                        ~150 tokens   │
│  Personality type, communication style, self-reflection  │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Session Memories                 25% budget   │
│  Recent memories, scored by recency                      │
├─────────────────────────────────────────────────────────┤
│  Layer 3: Knowledge                        35% budget   │
│  Semantic retrieval, scored by confidence × similarity   │
├─────────────────────────────────────────────────────────┤
│  Layer 4: Long-Term Memories               40% budget   │
│  Hybrid scoring across all four recall factors +         │
│  semantic similarity                                     │
└─────────────────────────────────────────────────────────┘
```

Packs are deterministic — same inputs produce the same output. No randomness, no hidden reranking. Every included memory is tagged with *why* it was selected (recency, semantic match, high importance, or hybrid).

The compiled pack renders as structured markdown, ready for system prompt injection:

```markdown
## Your Identity
You are a research assistant with an analytical communication style.
You value precision and depth over breadth.

## Current Session
- User is exploring database migration strategies for their payment system
- Previous discussion covered NoSQL vs relational trade-offs

## Relevant Knowledge
- [FACT] User's payment system requires ACID transactions
- [METHOD] Database migration involves schema mapping, data validation, and incremental rollout
- [PRINCIPLE] Financial systems should prioritize consistency over availability

## Relevant Memories
- [2 days ago] User explained they're migrating from MongoDB to PostgreSQL
- [1 week ago] User asked about transaction isolation levels in PostgreSQL
- [3 weeks ago] Initial onboarding — user described their fintech startup context
```

---

### Four-Factor Recall

Every memory is scored across four dimensions that together determine recall priority:

```
  importance ──── How significant is this memory?               0.0 → 1.0
  confidence ──── How certain are we it's accurate?             0.0 → 1.0
  recency ─────── How recently was it formed?                   exponential decay
  decay ───────── Has it been reinforced or neglected?          access-weighted
```

Memories follow a defined lifecycle:

```
  ACTIVE  ──→  DECAYING  ──→  ARCHIVED
     ↑                            │
     └──── restore (manual) ──────┘
```

Active memories participate fully in pack assembly. Decaying memories are deprioritized. Archived memories are preserved for provenance but rarely surfaced. The Dreamer manages these transitions automatically.

---

## Quick Start

### Install the SDK

```bash
pip install elephantasm
```

```bash
npm install @elephantasm/client
```

### Basic Usage

**Python:**
```python
from elephantasm import Elephantasm

client = Elephantasm(api_key="sk_live_...")

# Ingest an event
client.ingest(
    anima_id="your-agent-id",
    content="User asked about transformer architectures",
    event_type="message.in"
)

# Retrieve a memory pack
pack = client.inject(anima_id="your-agent-id")
print(pack.asPrompt())
```

**TypeScript:**
```typescript
import { Elephantasm } from '@elephantasm/client'

const client = new Elephantasm({ apiKey: 'sk_live_...' })

await client.ingest({
  animaId: 'your-agent-id',
  content: 'User asked about transformer architectures',
  eventType: 'message.in'
})

const pack = await client.inject({ animaId: 'your-agent-id' })
console.log(pack.asPrompt())
```

### Integration Example

Add long-term memory to any LLM call:

```python
from elephantasm import Elephantasm
from anthropic import Anthropic

memory = Elephantasm(api_key="sk_live_...")
llm = Anthropic()

def chat(agent_id: str, user_message: str) -> str:
    # Inject memory context into system prompt
    pack = memory.inject(anima_id=agent_id)

    response = llm.messages.create(
        model="claude-sonnet-4-5-20250514",
        system=pack.asPrompt(),
        messages=[{"role": "user", "content": user_message}]
    )

    reply = response.content[0].text

    # Ingest both sides of the conversation
    memory.ingest(anima_id=agent_id, content=user_message, event_type="message.in")
    memory.ingest(anima_id=agent_id, content=reply, event_type="message.out")

    return reply
```

Works with any LLM provider. The memory layer is model-agnostic.

---

## Self-Hosting

### Docker

```bash
git clone https://github.com/hejijunhao/elephantasm-core.git
cd elephantasm-core

docker compose up -d
```

API at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Manual Setup

```bash
git clone https://github.com/hejijunhao/elephantasm-core.git
cd elephantasm-core

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # configure database connection
alembic upgrade head           # run migrations
python main.py                 # start server
```

### Configuration

| Variable | Purpose | Required |
|----------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection (runtime via pgBouncer, port 6543) | Yes |
| `MIGRATION_DATABASE_URL` | PostgreSQL connection (direct, port 5432) | Yes |
| `ANTHROPIC_API_KEY` | LLM for memory synthesis and Dreamer curation | Yes |
| `OPENAI_API_KEY` | Embeddings via text-embedding-3-small | Yes |
| `SUPABASE_URL` | JWT/JWKS validation for dashboard auth | For auth |
| `ENABLE_BACKGROUND_JOBS` | Enable Dreamer scheduler and auto-synthesis | Default: true |

For self-hosted PostgreSQL without pgBouncer, use the same direct connection URL for both variables.

---

## Architecture

Three-layer backend with async/sync split:

```
┌───────────────────────────────────────────────────────┐
│                  API Layer (async)                     │
│  FastAPI routes · dependency injection · RLS context   │
└──────────────────────────┬────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────┐
│                Domain Layer (sync)                     │
│  Static methods · business rules · domain exceptions   │
│  No HTTP imports · session passed explicitly            │
└──────────────────────────┬────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────┐
│              Database Layer (SQLModel)                  │
│  ORM models · soft deletes · JSONB metadata · RLS      │
└───────────────────────────────────────────────────────┘
```

Async API routes call sync domain operations via FastAPI's thread pool. Domain code raises domain exceptions (`EntityNotFoundError`, `DomainValidationError`), never `HTTPException`. Global exception handlers map these to HTTP responses.

### Technology

| Component | Technology |
|-----------|------------|
| Framework | FastAPI |
| ORM | SQLModel + SQLAlchemy 2.0 |
| Database | PostgreSQL with pgvector |
| Workflows | LangGraph (memory synthesis + knowledge extraction) |
| LLM | Anthropic Claude (configurable) |
| Embeddings | OpenAI text-embedding-3-small (1536-dim) |
| Auth | JWT (JWKS) + API keys (bcrypt) |
| Migrations | Alembic |
| Scheduling | APScheduler |

### Security

All tables enforce PostgreSQL Row-Level Security. Dual authentication — JWT for dashboards, API keys (`sk_live_` prefix) for SDKs — both resolve to an internal user ID. Every query is automatically scoped to the authenticated user. Background jobs use `SECURITY DEFINER` functions to bypass RLS where necessary.

---

## API

Full REST API with ~60 authenticated endpoints. The SDK surface (7 endpoints) is host-restricted to `api.elephantasm.com`:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/events` | Ingest events |
| `GET` | `/api/events` | List events |
| `POST` | `/api/animas` | Create agent |
| `GET` | `/api/animas` | List agents |
| `PATCH` | `/api/animas/{id}` | Update agent |
| `GET` | `/api/animas/{id}/memory-packs/latest` | Retrieve memory pack |
| `GET` | `/api/health` | Health check |

Interactive API documentation available at `/docs` (Swagger) and `/redoc` when self-hosting.

---

## Testing

```bash
pytest -v                     # full suite
pytest -v -k "test_name"     # single test by name
pytest tests/integration/     # end-to-end flows
ruff check . && black .       # lint and format
```

---

## Contributing

Bug reports and feature requests via [GitHub Issues](https://github.com/hejijunhao/elephantasm-core/issues).

Code contributions: fork, branch, PR. Format with `black`, lint with `ruff`. Domain operations should be sync static methods that raise domain exceptions, never `HTTPException`.

---

## License

[Apache License 2.0](LICENSE) — commercial use, modification, distribution, and patent use permitted.

---

<div align="center">

*"Memory is not what happened. It's the story we tell ourselves about what mattered."*

[Star on GitHub](https://github.com/hejijunhao/elephantasm-core) &middot; [Read the Docs](https://elephantasm.com/docs)

</div>
