# Tech Stack Decisions – Support IQ

This document explains which technologies we chose for Support IQ and why. For each part of
the system we note the alternatives we looked at and what tipped the decision. The design
choices behind the features themselves are in `DESIGN_DECISIONS.md`.

Our guiding constraints were:

- **Runs on a normal laptop** with no paid services and no API key required.
- **Python for the AI side**, because that is where the embedding and ranking libraries are.
- **A real web front end** that looks like a production help center and admin console.
- **A path to production** (PostgreSQL, Docker) without making local setup harder.
- **Testable end to end**, with repeatable results for evaluation.

---

## Overview

| Layer | Choice | Version |
|---|---|---|
| Backend language | Python | 3.12 (Docker), 3.11+ supported |
| Web framework | FastAPI + Uvicorn | FastAPI ≥ 0.111, Uvicorn ≥ 0.30 |
| Data validation | Pydantic 2 + pydantic-settings | ≥ 2.7 / ≥ 2.3 |
| ORM | SQLAlchemy 2 | ≥ 2.0.30 |
| Database (production) | PostgreSQL 16 + pgvector | `pgvector/pgvector:pg16` |
| Database (local) | SQLite | built into Python |
| Embeddings | sentence-transformers, `all-MiniLM-L6-v2` | ≥ 3.0 |
| Reranker | Cross-encoder `ms-marco-MiniLM-L-6-v2` | via sentence-transformers |
| Keyword search | BM25, implemented in-house | – |
| Numerics | NumPy | ≥ 1.26 |
| LLM | Google Gemini `gemini-2.5-flash` (optional), REST via httpx | httpx ≥ 0.27 |
| Front end | React 18 + TypeScript | React 18.3, TS 5.6 |
| Build tool | Vite | 5.4 |
| Routing | React Router | 6.27 |
| Server state | TanStack Query | 5.59 |
| Voice input | Web Speech API (browser) | – |
| Backend tests / lint | pytest, Ruff | ≥ 8.0 / ≥ 0.5 |
| Front-end tests / lint | Vitest, Testing Library, jsdom, ESLint | Vitest 2.1, ESLint 9 |
| Containers | Docker, docker-compose, Nginx | node:20-alpine, nginx:1.27-alpine |

---

## 1. Backend language: Python

**Alternatives:** Node.js, Java/Spring.

**Why Python.** The core of this project is retrieval and ranking: embeddings,
cross-encoders, vector maths and dataset processing. The best libraries for this
(sentence-transformers, NumPy) are Python-first. Keeping the API in the same language as the
AI code avoids a second service and a network hop between them.

---

## 2. Web framework: FastAPI

**Alternatives:** Flask, Django.

**Why FastAPI**
- Request and response models with Pydantic give automatic validation and clear error
  messages. We use strict schemas that reject unknown fields.
- Built-in OpenAPI docs at `/docs`, which helped while building the front end.
- Streaming responses, which we use to show the live "how this answer was found" steps
  (NDJSON over `/resolve/stream`).
- Dependency injection keeps the services (retrieval, classifier, pipeline) testable.

**Why not Django.** Its admin, ORM and templating are useful for CRUD sites, but we were
building our own React admin and needed flexible async and streaming behaviour.

**Server:** Uvicorn (ASGI), the standard pairing for FastAPI.

---

## 3. Configuration: pydantic-settings + `.env`

**Why.** All settings are typed and validated at start-up: thresholds, weights, model names,
paths and the API key. The key is stored as a `SecretStr`, so it is never printed in logs.
`.env.example` documents every setting without exposing secrets.

---

## 4. ORM: SQLAlchemy 2

**Alternatives:** raw SQL, SQLModel, Django ORM.

**Why**
- The same models work on both PostgreSQL and SQLite (see the next decision).
- A custom column type (`EmbeddingType`) stores embeddings as `VECTOR(384)` on PostgreSQL
  and as binary on SQLite, so the rest of the code does not care which database is used.
- SQLAlchemy 2's typed `Mapped[...]` models are clear and work well with editors and type
  checkers.

---

## 5. Database: PostgreSQL + pgvector in production, SQLite locally

**Alternatives:** a dedicated vector database (Pinecone, Weaviate, Qdrant, Chroma), FAISS
files, Elasticsearch.

**Why PostgreSQL + pgvector**
- One database holds everything: tickets, articles, cases, attempts, feedback, chats and
  vectors. Joins between cases and their sources are simple.
- No separate vector service to deploy, secure or keep in sync.
- pgvector is mature and fast enough for tens of thousands of chunks.

**Why SQLite locally**
- Zero setup: the project runs with only Python and Node installed.
- If PostgreSQL is configured but unreachable, the backend retries and then falls back to
  SQLite automatically.

**Trade-off.** With SQLite, vector search runs in memory with NumPy instead of in the
database. At our data size (a de-duplicated index of templates and article chunks) this is
fast, but a much larger corpus would need PostgreSQL.

**Why not a dedicated vector DB.** For this scale it would add infrastructure without a real
benefit, and we would lose transactional consistency between cases and their evidence.

---

## 6. Embeddings: sentence-transformers `all-MiniLM-L6-v2`

**Alternatives:** OpenAI or Gemini embedding APIs, larger local models (e.g. `bge-large`,
`all-mpnet-base-v2`).

**Why MiniLM**
- Small (about 80 MB) and fast on a CPU; 384-dimension vectors keep storage small.
- Works offline with no API key or per-request cost.
- Good quality for short, single-topic texts such as support complaints.

**Fallback.** If sentence-transformers is not installed, a hashing-based embedding is used so
the app still starts. Thresholds have separate values for each backend because their score
ranges differ.

**Trade-off.** Larger models would be somewhat more accurate but slower and heavier. The
model name is a setting, so it can be swapped without code changes.

---

## 7. Reranker: cross-encoder `ms-marco-MiniLM-L-6-v2`

**Why.** A cross-encoder reads the complaint and each candidate together, which ranks the
top results more accurately than vector similarity alone. We only rerank the top
candidates, so the cost stays low.

**Optional by design.** If it is unavailable, the system falls back to the hybrid score and
the evidence score is adjusted accordingly.

---

## 8. Keyword search: our own BM25

**Alternatives:** Elasticsearch/OpenSearch, PostgreSQL full-text search, the `rank_bm25`
package.

**Why in-house.** BM25 is a short, well-known formula. A small implementation in
`retrieval.py` runs in memory alongside the vector scores, needs no extra service, and lets
us return extra signals such as query-term coverage. Elasticsearch would be far more than
this project needs.

---

## 9. LLM: Gemini (optional) with a template fallback

**Alternatives:** OpenAI GPT models, a local LLM via Ollama, no LLM at all.

**Why Gemini**
- `gemini-2.5-flash` is fast and inexpensive for short, structured answers.
- It is only called through a provider interface, so other models can be added later.

**Why a REST call with httpx instead of an SDK.** It keeps dependencies small, gives us full
control over timeouts (25 s by default) and makes failures easy to catch and fall back from.

**Why the template fallback is the default (demo mode).** The project must run without any
key, give repeatable results for tests and evaluation, and never produce ungrounded text. The
grounding check runs on both paths.

---

## 10. Front end: React 18 + TypeScript

**Alternatives:** Vue, Angular, server-rendered templates (Jinja), Streamlit.

**Why React + TypeScript**
- We needed two full applications in one project: a customer help center with a chat widget
  and an admin console with many pages. React's component model makes it easy to share
  pieces between them (for example, the resolution card has a customer and an admin mode).
- TypeScript catches mismatches between the front end and the API types early.

**Why not Streamlit.** It is quick for demos but does not look or behave like a real
customer website, which was an explicit requirement.

---

## 11. Build tool: Vite

**Alternatives:** Create React App (no longer maintained), Next.js, Webpack.

**Why.** Very fast start-up and hot reload, simple configuration, and a built-in dev proxy
that forwards `/api` calls to the backend. We do not need server-side rendering, so Next.js
would add complexity without benefit.

---

## 12. Routing and data fetching: React Router + TanStack Query

**React Router** separates the two experiences cleanly: the customer site at `/` and the
admin console at `/admin/*`.

**TanStack Query** handles all server state:
- caching and automatic refetching,
- **polling every 3 seconds** for live chats and the inbox,
- invalidating data after actions (for example, refreshing the review queue after an
  approval).

This removed the need for a global state library such as Redux.

---

## 13. Styling: plain CSS with design tokens

**Alternatives:** Tailwind CSS, Material UI, Bootstrap.

**Why.** We wanted the site to look like a custom, hand-built product rather than a generic
component library. Plain CSS with variables (`theme.css`, `site.css`) gives full control
over the look, keeps the bundle small, and avoids fighting a framework's defaults. The
customer site and the admin console each have their own stylesheet. Charts are drawn with
small custom React/SVG components instead of a charting library.

---

## 14. Voice input: the browser's Web Speech API

**Alternatives:** Whisper (local or API), Google Cloud Speech-to-Text.

**Why.** It is built into Chrome and Edge, needs no server, model download or key, and the
transcript simply becomes the complaint text, so it goes through exactly the same pipeline
as typed input.

**Trade-off.** Browser support varies. Unsupported browsers show a clear message instead of
failing.

---

## 15. Testing: pytest and Vitest

**Backend:** pytest with FastAPI's `TestClient`. Tests run against an isolated temporary
SQLite database seeded from a small demo dataset and a temporary copy of the dataset file,
so they are fast and never modify real data. **Ruff** is used for linting.

**Front end:** Vitest (Vite-native, Jest-compatible) with Testing Library and jsdom. The
tests interact with the UI the way a user would (find by role and label) and mock the API
with fixtures. **ESLint** with the React Hooks rules and the TypeScript compiler run as
quality checks.

---

## 16. Packaging and deployment: Docker + docker-compose

**Why.** One command (`docker compose up --build`) starts:

- `pgvector/pgvector:pg16` – PostgreSQL with the vector extension,
- the backend on `python:3.12-slim`,
- the front end built with `node:20-alpine` and served by `nginx:1.27-alpine` on port 8080.

For local development, Docker is optional: the backend runs with Uvicorn and the front end
with `npm run dev`.

---

## Summary

| Need | Choice | Main reason |
|---|---|---|
| AI and API in one language | Python | Best ML ecosystem |
| Fast, typed API with streaming | FastAPI + Pydantic | Validation, docs, streaming |
| One data layer for two databases | SQLAlchemy 2 | Same models on PostgreSQL and SQLite |
| Vectors without extra services | PostgreSQL + pgvector / SQLite | Everything in one database |
| Offline semantic search | MiniLM embeddings | Fast, free, no key |
| Better top results | Cross-encoder reranker | Higher precision, optional |
| Exact-term matching | In-house BM25 | Simple, no extra service |
| Optional generation | Gemini via httpx + templates | Works with or without a key |
| Real website and admin UI | React + TypeScript + Vite | Shared components, type safety |
| Live data | TanStack Query polling | Simple live updates |
| Custom look | Plain CSS tokens | Hand-built feel, small bundle |
| Voice | Web Speech API | No server or key needed |
| Quality | pytest, Vitest, Ruff, ESLint | Repeatable automated checks |
| Deployment | Docker + docker-compose | One-command setup |
