<div align="center">

![Elephantasm](lightfinder.png)

# 🐘 Elephantasm

**Long-Term Agentic Memory for AI systems that remember, learn, and evolve.**

[![Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14+-blue.svg)](https://www.postgresql.org)

[**Website**](https://elephantasm.dev) • [**Documentation**](https://elephantasm.dev/docs) • [**GitHub**](https://github.com/hejijunhao/elephantasm-core) • [**Twitter**](https://twitter.com/elephantasm)

</div>

---

## 🌟 From Context to Continuity

Current AI systems are **stateless**. Each interaction begins from scratch, with no genuine memory beyond what fits in a context window. RAG retrieves documents; caches replay tokens. Neither remembers. Neither learns. Neither becomes.

The problem is architectural. We've treated memory as retrieval—nearest neighbors in vector space, keyword matches in databases. But **memory is not search**. Memory is **transformation**: sensation becomes experience, experience becomes understanding, understanding shapes identity.

Elephantasm is a **structured cognitive substrate**. It transforms raw events into layered memory through deterministic, auditable processes:

```
Events → Memories → Lessons → Knowledge → Identity
```

This is not a cache. It is an **architecture for continuity**.

---

## 📦 What This Is

Elephantasm is an open-source framework for **Long-Term Agentic Memory (LTAM)**.

### Core Features

| Feature | Description |
|---------|-------------|
| 🧠 **Layered Memory** | Five-tier transformation: Events → Memories → Lessons → Knowledge → Identity |
| 🔗 **Provenance Tracking** | Every memory traces back to source events via junction tables |
| 📊 **Four-Factor Recall** | Importance, confidence, recency, decay—deterministic scoring |
| ⚙️ **Dreamer Curation** | Background process that evolves memory over time (Phase 2) |
| 🔌 **Composable Design** | Works with LangChain, LlamaIndex, or raw Python—no vendor lock-in |
| 🚀 **Production Ready** | Docker, health checks, migrations, deployed on Fly.io |

**This is the backend API.** Self-hostable. Framework-agnostic. Production-ready.

---

## 🏗️ Architecture

### Memory Layers

| Layer | What It Represents | Status |
|-------|-------------------|--------|
| **Event** | Raw interaction (message, tool call, API response) | ✅ Phase 1 |
| **Memory** | Structured reflection on one or more events | ✅ Phase 1 |
| **Lesson** | Extracted pattern or insight from memories | 📅 Phase 2 |
| **Knowledge** | Canonicalized truth distilled from lessons | 📅 Phase 2 |
| **Identity** | Emergent behavioral fingerprint | 📅 Phase 2 |

### System Flow

```mermaid
graph TD
    A[Event Ingestion] --> B[Cortex]
    B --> C[Pack Compiler]
    C --> D[Planner/Tools]
    D --> E[Dreamer]
    E --> F[Memory Evolution]

    B -.-> G[Filters signal from noise]
    C -.-> H[Deterministic retrieval]
    E -.-> I[Background curation]
```

```
┌──────────────────┐
│ Event Ingestion  │
└────────┬─────────┘
         ↓
    ┌─────────┐
    │ Cortex  │  ← Filters signal from noise
    └────┬────┘
         ↓
┌────────────────┐
│ Pack Compiler  │  ← Assembles deterministic memory packs
└───────┬────────┘
        ↓
   ┌─────────┐
   │ Planner │  ← Executes, updates, learns
   └────┬────┘
        ↓
   ┌─────────┐
   │ Dreamer │  ← Background curation loop
   └────┬────┘
        ↓
┌──────────────────┐
│ Memory Evolution │
└──────────────────┘
```

### Core Principles

<table>
<tr>
<td width="50%">

**🔄 Continuity ≠ Context**

Context is what you know *now*. Continuity is what you've *learned before*.

**🧱 Structure + Similarity**

Vector search accelerates discovery. Structured metadata defines meaning.

**🎯 Determinism as Frame, Not Cage**

Memory organization is predictable. Recall priority is adaptive.

</td>
<td width="50%">

**📥 Accumulation → Curation**

Record everything. Distill later. The Dreamer refines what matters.

**🧩 Composability**

Integrate into any agentic runtime without vendor lock-in.

**🌱 Identity as Emergence**

Over time, accumulated memory defines behavioral disposition.

</td>
</tr>
</table>

### Four-Factor Recall System

Memories are scored across **four dimensions**:

| Factor | Range | Purpose |
|--------|-------|---------|
| **Importance** | 0.0–1.0 | How significant this memory is |
| **Confidence** | 0.0–1.0 | Stability and certainty of the memory |
| **Recency Score** | Computed | Time-based decay function |
| **Decay Score** | Computed | Contextual relevance erosion |

**Memory States**: `ACTIVE` → `DECAYING` → `ARCHIVED`

### Provenance Graph

Every memory links back to source events via the `MemoryEvent` junction table:

```
Spirit (Agent)
    ├── Events (Raw interactions)
    │   ├── MESSAGE_IN
    │   ├── MESSAGE_OUT
    │   ├── TOOL_CALL
    │   └── API_RESPONSE
    └── Memories (Reflections)
        └── MemoryEvent Links (Provenance)
            └── → Source Events
```

**Trace lineage. Audit transformations. Understand why the agent believes what it believes.**

---

## 🛠️ Technology Stack

<table>
<tr>
<td width="50%">

### Backend

- **FastAPI** 0.115+ — Web framework
- **SQLModel** 0.0.22 — ORM + Pydantic validation
- **PostgreSQL** 14+ — Database with JSONB
- **Alembic** 1.13+ — Migration management
- **Uvicorn** 0.32+ — ASGI server
- **Psycopg3** 3.2+ — Async PostgreSQL driver

</td>
<td width="50%">

### Design Pattern

**Marlin Hybrid** (Async-to-Sync)

- API routes: `async` (FastAPI requirement)
- Domain operations: `sync` (simpler, cleaner)
- FastAPI thread pool handles concurrency
- Benefits: pgBouncer compatibility, easier transactions

</td>
</tr>
</table>

### Database

- **PostgreSQL 14+** with JSONB for flexible metadata
- **Supabase** (managed) or self-hosted
- **Dual connection URLs**: Transaction pooler (6543) for runtime, direct (5432) for migrations
- **NullPool strategy**: Let pgBouncer handle pooling

### Deployment

- **Production**: Fly.io (Singapore region) — https://elephantasm.fly.dev
- **Alternatives**: Railway, Render, self-hosted Docker
- **Health checks**: `/api/health`, `/healthz`
- **Auto-scaling**: 2 machines, suspend mode (~200ms wake-up)

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+** ([download](https://www.python.org/downloads/))
- **PostgreSQL 14+** or [Supabase account](https://supabase.com) (recommended)
- **Git** (for cloning)

### Installation

```bash
# 1. Clone repository
git clone https://github.com/hejijunhao/elephantasm-core.git
cd elephantasm-core

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your database URLs (see Configuration section below)

# 5. Run migrations
alembic upgrade head

# 6. Start server
python main.py
```

**API available at**: `http://localhost:8000`
**Interactive docs**: `http://localhost:8000/docs` (Swagger UI)
**Alternative docs**: `http://localhost:8000/redoc`

### Docker (Alternative)

```bash
# Build image
docker build -t elephantasm-core .

# Run container
docker run -p 8000:8000 --env-file .env elephantasm-core
```

**Image size**: 87 MB (multi-stage build)

### Verification

Test the API:

```bash
# Health check
curl http://localhost:8000/api/health

# Create a spirit
curl -X POST http://localhost:8000/api/spirits \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Agent", "description": "My first spirit"}'
```

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the `backend/` directory:

```env
# ============================================================================
# Database Configuration
# ============================================================================

# Runtime database URL (transaction pooler on port 6543)
DATABASE_URL=postgresql://postgres.[project-ref]:[password]@aws-0-us-east-1.pooler.supabase.com:6543/postgres

# Migration database URL (direct connection on port 5432)
MIGRATION_DATABASE_URL=postgresql://postgres.[project-ref]:[password]@aws-0-us-east-1.pooler.supabase.com:5432/postgres

# ============================================================================
# API Configuration
# ============================================================================

PROJECT_NAME=Elephantasm API
VERSION=0.1.0
API_PREFIX=/api

# CORS origins (comma-separated)
BACKEND_CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# ============================================================================
# Supabase (Optional - for RLS and auth integration)
# ============================================================================

SUPABASE_URL=https://[project-ref].supabase.co
SUPABASE_ANON_KEY=eyJhbG...
SUPABASE_SERVICE_ROLE_KEY=eyJhbG...
```

### Database Setup

#### Option 1: Supabase (Recommended)

1. Create project at [supabase.com](https://supabase.com)
2. Go to **Settings** → **Database**
3. Copy **Connection Pooling** URL → Use for `DATABASE_URL` (port 6543)
4. Copy **Direct Connection** URL → Use for `MIGRATION_DATABASE_URL` (port 5432)
5. Replace `[password]` with your database password

**Why two URLs?**
- **Transaction pooler (6543)**: High performance, limited features (runtime)
- **Direct connection (5432)**: Full PostgreSQL features (migrations)

#### Option 2: Self-Hosted PostgreSQL

```bash
docker run -d \
  --name elephantasm-db \
  -e POSTGRES_DB=elephantasm \
  -e POSTGRES_USER=elephantasm \
  -e POSTGRES_PASSWORD=changeme \
  -p 5432:5432 \
  -v elephantasm_data:/var/lib/postgresql/data \
  postgres:16

# Then set:
# DATABASE_URL=postgresql://elephantasm:changeme@localhost:5432/elephantasm
# MIGRATION_DATABASE_URL=postgresql://elephantasm:changeme@localhost:5432/elephantasm
```

---

## 📡 API Reference

### Core Endpoints

#### Spirits (Agent Entities)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/spirits` | Create new spirit |
| `GET` | `/api/spirits` | List all spirits (paginated) |
| `GET` | `/api/spirits/search?name={query}` | Search spirits by name |
| `GET` | `/api/spirits/{id}` | Get spirit by ID |
| `GET` | `/api/spirits/{id}/with-events` | Get spirit with events (eager-loaded) |
| `PATCH` | `/api/spirits/{id}` | Update spirit |
| `DELETE` | `/api/spirits/{id}` | Soft delete spirit |
| `POST` | `/api/spirits/{id}/restore` | Restore soft-deleted spirit |

#### Events (Raw Interactions)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/events` | Create new event |
| `GET` | `/api/events?spirit_id={uuid}` | List events for spirit |
| `GET` | `/api/events/{id}` | Get event by ID |
| `GET` | `/api/events/{id}/memories` | Get memories created from event |
| `PATCH` | `/api/events/{id}` | Update event |
| `DELETE` | `/api/events/{id}` | Soft delete event |

**Query Parameters**: `spirit_id` (required), `limit`, `offset`, `event_type`, `session_id`, `min_importance`, `include_deleted`

#### Memories (Structured Reflections)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/memories` | Create new memory |
| `GET` | `/api/memories?spirit_id={uuid}` | List memories for spirit |
| `GET` | `/api/memories/search?spirit_id={uuid}&q={query}` | Search memories by summary |
| `GET` | `/api/memories/stats?spirit_id={uuid}` | Get memory statistics |
| `GET` | `/api/memories/{id}` | Get memory by ID |
| `GET` | `/api/memories/{id}/events` | Get source events for memory |
| `PATCH` | `/api/memories/{id}` | Update memory |
| `DELETE` | `/api/memories/{id}` | Soft delete memory |
| `POST` | `/api/memories/{id}/restore` | Restore soft-deleted memory |

**Query Parameters**: `spirit_id` (required), `limit`, `offset`, `state`, `include_deleted`, `q` (search)

#### Provenance (Memory-Event Links)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/memories-events` | Create link between memory and event |
| `POST` | `/api/memories-events/bulk` | Create multiple links at once |
| `GET` | `/api/memories-events/memory/{id}` | Get all links for memory |
| `GET` | `/api/memories-events/memory/{id}/count` | Count events for memory |
| `DELETE` | `/api/memories-events/{id}` | Delete link |
| `DELETE` | `/api/memories-events/memory/{id}` | Delete all links for memory |
| `DELETE` | `/api/memories-events/event/{id}` | Delete all links for event |

### Example Workflow

```bash
# 1. Create a spirit (agent)
SPIRIT=$(curl -s -X POST http://localhost:8000/api/spirits \
  -H "Content-Type: application/json" \
  -d '{"name": "Research Assistant", "description": "Literature review agent"}' \
  | jq -r '.id')

echo "Created spirit: $SPIRIT"

# 2. Ingest an event
EVENT=$(curl -s -X POST http://localhost:8000/api/events \
  -H "Content-Type: application/json" \
  -d "{
    \"spirit_id\": \"$SPIRIT\",
    \"event_type\": \"MESSAGE_IN\",
    \"content\": \"Explain transformer architectures in NLP\",
    \"occurred_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }" \
  | jq -r '.id')

echo "Created event: $EVENT"

# 3. Create a memory from the event
MEMORY=$(curl -s -X POST http://localhost:8000/api/memories \
  -H "Content-Type: application/json" \
  -d "{
    \"spirit_id\": \"$SPIRIT\",
    \"summary\": \"User asking about transformer architectures in NLP context\",
    \"importance\": 0.85,
    \"confidence\": 0.9,
    \"time_start\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
  }" \
  | jq -r '.id')

echo "Created memory: $MEMORY"

# 4. Link memory to event (provenance)
curl -X POST http://localhost:8000/api/memories-events \
  -H "Content-Type: application/json" \
  -d "{
    \"memory_id\": \"$MEMORY\",
    \"event_id\": \"$EVENT\",
    \"link_strength\": 1.0
  }"

echo "Linked memory to event"

# 5. Retrieve memory with provenance
curl "http://localhost:8000/api/memories/$MEMORY/events" | jq
```

### Response Formats

**Success (200/201)**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Research Assistant",
  "description": "Literature review agent",
  "meta": {},
  "is_deleted": false,
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z"
}
```

**Error (4xx/5xx)**:
```json
{
  "detail": "Spirit with id=... not found"
}
```

**List**:
```json
[
  { "id": "...", "name": "Spirit 1", ... },
  { "id": "...", "name": "Spirit 2", ... }
]
```

---

## 📂 Project Structure

```
backend/
├── app/
│   ├── api/                      # HTTP layer
│   │   ├── router.py            # Main API router
│   │   └── routes/               # Endpoint modules
│   │       ├── health.py        # Health checks
│   │       ├── spirits.py       # Spirit CRUD
│   │       ├── events.py        # Event CRUD
│   │       ├── memories.py      # Memory CRUD + search + stats
│   │       └── memory_event_links.py  # Provenance links
│   ├── core/                     # Infrastructure
│   │   ├── config.py            # Pydantic Settings
│   │   └── database.py          # Engine, sessions, dependency injection
│   ├── domain/                   # Business logic (sync, static methods)
│   │   ├── spirit_operations.py
│   │   ├── event_operations.py
│   │   ├── memory_operations.py
│   │   └── memory_event_operations.py
│   ├── models/
│   │   ├── database/             # SQLModel ORM models
│   │   │   ├── spirits.py
│   │   │   ├── events.py
│   │   │   ├── memories.py
│   │   │   ├── memory_events.py
│   │   │   └── users.py
│   │   └── dto/                  # Data transfer objects (DTO)
│   └── services/                 # External integrations (future)
├── migrations/                   # Alembic database migrations
│   └── versions/
├── tests/                        # Pytest test suite
│   ├── core/
│   │   └── database_connection.py
│   └── models/
│       ├── spirits_crud_test.py
│       └── events_crud_test.py
├── main.py                       # Application entry point
├── requirements.txt              # Python dependencies
├── Dockerfile                    # Multi-stage Docker build
├── .dockerignore                 # Build context optimization
├── fly.toml                      # Fly.io deployment config
├── alembic.ini                   # Alembic configuration
├── .env.example                  # Environment variable template
└── README.md                     # This file
```

### Architecture Pattern

```
┌─────────────────────────────────────────────────────┐
│                   API Layer (Async)                 │
│  FastAPI routes, HTTP handling, validation          │
│  Files: app/api/routes/*.py                         │
└──────────────────┬──────────────────────────────────┘
                   │ Calls domain operations
                   ↓
┌─────────────────────────────────────────────────────┐
│                Domain Layer (Sync)                  │
│  Business logic, static methods, no HTTP awareness  │
│  Files: app/domain/*_operations.py                  │
└──────────────────┬──────────────────────────────────┘
                   │ Uses ORM models
                   ↓
┌─────────────────────────────────────────────────────┐
│              Database Layer (SQLModel)              │
│  ORM models, session management, queries            │
│  Files: app/models/database/*.py                    │
└─────────────────────────────────────────────────────┘
```

**Why this pattern?**
- **Separation of concerns**: HTTP ≠ Business Logic ≠ Data Access
- **Testability**: Domain logic isolated from framework
- **pgBouncer compatibility**: Sync operations avoid prepared statement issues
- **Simpler transactions**: Routes handle commit/rollback explicitly

---

## 🗄️ Database Schema

### Entity-Relationship Diagram

```
┌──────────┐
│   User   │  (Supabase Auth integration)
│──────────│
│ id (PK)  │
│ auth_uid │◄─── Synced from auth.users
│ email    │
└──────────┘
     │
     │ 1:N
     ↓
┌──────────┐
│  Spirit  │  (Agent entity)
│──────────│
│ id (PK)  │
│ name     │
│ meta     │  (JSONB - flexible metadata)
└──────────┘
     │
     ├── 1:N ───────────────────┐
     │                          │
     ↓                          ↓
┌──────────┐              ┌──────────┐
│  Event   │              │  Memory  │
│──────────│              │──────────│
│ id (PK)  │              │ id (PK)  │
│ spirit_id│              │ spirit_id│
│ type     │              │ summary  │
│ content  │              │ importance (0-1)
│ occurred │              │ confidence (0-1)
│ dedupe_key              │ state (ACTIVE/DECAYING/ARCHIVED)
└──────────┘              └──────────┘
     │                          │
     └────────── N:M ───────────┘
              (via MemoryEvent)

         ┌──────────────┐
         │ MemoryEvent  │  (Provenance junction)
         │──────────────│
         │ id (PK)      │
         │ memory_id (FK)
         │ event_id (FK)│
         │ link_strength│  (0.0-1.0)
         └──────────────┘
```

### Schema Details

<details>
<summary><strong>Spirit (Agent Entity)</strong></summary>

```python
class Spirit(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    meta: dict = Field(default_factory=dict, sa_column=Column(JSONB))
    is_deleted: bool = Field(default=False)
    created_at: datetime
    updated_at: datetime
```

**Indexes**: `name` (for search queries)

</details>

<details>
<summary><strong>Event (Raw Interaction)</strong></summary>

```python
class Event(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    spirit_id: UUID = Field(foreign_key="spirits.id")
    event_type: EventType  # MESSAGE_IN, MESSAGE_OUT, TOOL_CALL, etc.
    content: str
    meta_summary: Optional[str] = None  # Cortex-generated summary
    occurred_at: datetime  # When event actually happened
    session_id: Optional[str] = None  # Groups related events
    source_uri: Optional[str] = None  # Source system identifier
    dedupe_key: Optional[str] = None  # SHA256 hash for deduplication
    importance_score: Optional[float] = None  # 0.0-1.0
    is_deleted: bool = Field(default=False)
    created_at: datetime
    updated_at: datetime
```

**Unique constraint**: `dedupe_key` (prevents duplicate events)
**Indexes**: `spirit_id`, `event_type`, `session_id`, `occurred_at`

</details>

<details>
<summary><strong>Memory (Structured Reflection)</strong></summary>

```python
class Memory(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    spirit_id: UUID = Field(foreign_key="spirits.id")
    summary: str  # Compact narrative essence
    importance: Optional[float] = None  # 0.0-1.0 (recall priority)
    confidence: Optional[float] = None  # 0.0-1.0 (stability/certainty)
    state: MemoryState = Field(default=MemoryState.ACTIVE)
    recency_score: Optional[float] = None  # Cached score (future)
    decay_score: Optional[float] = None  # Cached score (future)
    time_start: datetime  # Event timespan start
    time_end: Optional[datetime] = None  # Event timespan end
    meta: dict = Field(default_factory=dict, sa_column=Column(JSONB))
    is_deleted: bool = Field(default=False)
    created_at: datetime
    updated_at: datetime
```

**State machine**: `ACTIVE` → `DECAYING` → `ARCHIVED`
**Indexes**: `spirit_id`, `state`, `importance`

</details>

<details>
<summary><strong>MemoryEvent (Provenance Junction)</strong></summary>

```python
class MemoryEvent(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    memory_id: UUID = Field(foreign_key="memories.id")
    event_id: UUID = Field(foreign_key="events.id")
    link_strength: Optional[float] = None  # 0.0-1.0 (contribution weight)
    created_at: datetime  # Immutable timestamp

    __table_args__ = (
        UniqueConstraint("memory_id", "event_id"),
        CheckConstraint("link_strength >= 0.0 AND link_strength <= 1.0"),
    )
```

**Unique constraint**: `(memory_id, event_id)` prevents duplicate links
**Hard delete**: Links are hard-deleted (not soft-deleted)

</details>

### Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "add new field to memories"

# Review generated migration in migrations/versions/

# Apply migration
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Show current version
alembic current

# Show migration history
alembic history
```

**Important**: Always review autogenerated migrations! Alembic can't detect renames (sees as drop + add), data migrations, or complex constraint changes.

---

## 🚀 Deployment

### Production Checklist

- [ ] **Environment variables** configured via secrets manager (not `.env`)
- [ ] **Database connection pooling** (pgBouncer on port 6543)
- [ ] **SSL/TLS** for database connections
- [ ] **Health checks** configured (`/api/health`, `/healthz`)
- [ ] **Database backups** automated (daily at minimum)
- [ ] **Error monitoring** (Sentry, Rollbar, etc.)
- [ ] **Performance monitoring** (New Relic, DataDog, etc.)
- [ ] **Structured logging** (JSON format)
- [ ] **Rate limiting** (per-IP or per-user)
- [ ] **CORS** configured for production origins only

### Deployment Options

<details>
<summary><strong>Fly.io (Recommended)</strong></summary>

**Current Production**: https://elephantasm.fly.dev

```bash
# 1. Install Fly CLI
curl -L https://fly.io/install.sh | sh

# 2. Authenticate
fly auth login

# 3. Launch app (first time)
fly launch
# Choose: organization, app name, region

# 4. Set secrets
fly secrets set \
  DATABASE_URL="postgresql://..." \
  MIGRATION_DATABASE_URL="postgresql://..." \
  SUPABASE_URL="https://..." \
  SUPABASE_SERVICE_ROLE_KEY="..." \
  SUPABASE_ANON_KEY="..."

# 5. Deploy
fly deploy

# 6. Monitor
fly logs
fly status
fly dashboard
```

**Configuration**: See `fly.toml` for VM size, scaling, health checks.

</details>

<details>
<summary><strong>Railway / Render</strong></summary>

**Railway**:
1. Connect GitHub repo
2. Select `backend/` as root path
3. Add environment variables
4. Auto-deploy on push

**Render**:
1. Connect GitHub repo
2. Select `backend/` as root path
3. Build command: `pip install -r requirements.txt`
4. Start command: `python main.py`
5. Add environment variables

</details>

<details>
<summary><strong>Docker Compose (Self-Hosted)</strong></summary>

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://elephantasm:${DB_PASSWORD}@db:5432/elephantasm
      MIGRATION_DATABASE_URL: postgresql://elephantasm:${DB_PASSWORD}@db:5432/elephantasm
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: elephantasm
      POSTGRES_USER: elephantasm
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres_data:
```

```bash
# Deploy
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop
docker-compose down
```

</details>

---

## 🗺️ Roadmap

### Phase 1 — Core LTAM (v0.1) **~70% Complete**

- [x] Spirit, Event, Memory models
- [x] REST API with CRUD operations
- [x] Provenance tracking (MemoryEvent junction)
- [x] Database migrations (Alembic)
- [x] Four-factor recall schema
- [x] Production deployment (Fly.io)
- [x] Health checks and monitoring
- [ ] **Pack Compiler** (deterministic memory retrieval)
- [ ] **Dreamer Loop** (background curation)
- [ ] **Python SDK** (`elephantasm-py`)
- [ ] **TypeScript SDK** (`@elephantasm/client`)

### Phase 2 — Intelligence & Growth (v1.0)

- [ ] **Layered Promotion**: Memory → Lesson → Knowledge → Identity
- [ ] **Cortex**: Event filtering and importance scoring
- [ ] **Vector Search**: pgvector integration for similarity retrieval
- [ ] **Evaluation Tools**: Memory quality metrics, drift detection
- [ ] **Configurable Curation**: Custom Dreamer rules per spirit
- [ ] **RLS Authorization**: Row-level security with Supabase Auth
- [ ] **Advanced Search**: Full-text search, semantic queries

### Phase 3 — Ecosystem (v2.0+)

- [ ] **Multi-Agent Memory**: Shared memory networks across spirits
- [ ] **Memory Pack Marketplace**: Export/import trained memory packs
- [ ] **LLM Integrations**: OpenAI, Anthropic, HuggingFace adapters
- [ ] **Plugin System**: Custom curators, transformers, scorers
- [ ] **WebSocket Updates**: Real-time memory evolution
- [ ] **Collaborative Editing**: Multi-user memory curation
- [ ] **Observability Dashboard**: Rich UI for memory exploration

---

## 🧪 Testing

### Run Tests

```bash
# All tests
pytest

# Verbose output
pytest -v

# Specific test file
pytest tests/models/spirits_crud_test.py

# With coverage
pytest --cov=app --cov-report=html

# Open coverage report
open htmlcov/index.html
```

### Test Structure

```
tests/
├── core/
│   └── database_connection.py    # Database connectivity
├── models/
│   ├── spirits_crud_test.py      # Spirit CRUD operations
│   └── events_crud_test.py       # Event CRUD operations
└── conftest.py                    # Shared fixtures
```

**Test Database**: Configured in `conftest.py` with isolated test session.

---

## 🤝 Contributing

**Current Status**: Phase 1 stabilization. Not accepting external PRs yet.

### Welcome

- 🐛 **Bug reports** via GitHub Issues
- 💡 **Feature requests** via GitHub Discussions
- 🎨 **Design feedback** on architecture, patterns, naming

### Code Style

- **PEP 8** style guide
- **Type hints** on all functions
- **Docstrings** for public APIs
- **Import order**: stdlib → third-party → local
- **Linting**: `ruff check .` (backend)
- **Formatting**: `black .` (backend)

### Testing Requirements

- Unit tests for domain operations
- Integration tests for API routes
- Coverage target: 80%+

**Full contributions enabled in v0.5+ (Q2 2025).**

---

## 📄 License

**Apache License 2.0**. See [LICENSE](LICENSE).

**Patent protection. Corporate-friendly. Permissive for commercial use.**

Key permissions:
- ✅ Commercial use
- ✅ Modification
- ✅ Distribution
- ✅ Patent use
- ✅ Private use

---

## 🔗 Links

| Resource | URL |
|----------|-----|
| **Production API** | https://elephantasm.fly.dev |
| **GitHub Repository** | https://github.com/hejijunhao/elephantasm-core |
| **Website** | https://elephantasm.dev |
| **Documentation** | https://elephantasm.dev/docs |
| **Issues** | https://github.com/hejijunhao/elephantasm-core/issues |
| **Twitter** | https://twitter.com/elephantasm |

---

## 🙏 Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com) — Modern, fast web framework
- [SQLModel](https://sqlmodel.tiangolo.com) — ORM + Pydantic validation
- [Supabase](https://supabase.com) — Managed PostgreSQL + Auth
- [Alembic](https://alembic.sqlalchemy.org) — Database migrations
- [PostgreSQL](https://www.postgresql.org) — Robust relational database

Inspired by:
- [MemGPT](https://memgpt.ai) — Virtual context management for LLMs
- [LangChain Memory](https://python.langchain.com/docs/modules/memory/) — Agent memory patterns
- [Zep](https://www.getzep.com) — Long-term memory for LLM apps

---

<div align="center">

*"Memory is not what happened. It's the story we tell ourselves about what mattered."*

**[⭐ Star on GitHub](https://github.com/hejijunhao/elephantasm-core)** • **[🐦 Follow on Twitter](https://twitter.com/elephantasm)** • **[📖 Read the Docs](https://elephantasm.dev/docs)**

</div>
