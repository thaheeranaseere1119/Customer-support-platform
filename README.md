# Customer-support-platform

**Adaptive RAG-Based Telecom Support Resolution Assistant**

An evidence-aware telecom support resolution system. It understands a customer complaint, retrieves similar
historical tickets and knowledge-base articles (hybrid vector + BM25 + metadata retrieval with reranking),
scores the evidence, and produces a **grounded, cited** resolution. When evidence is insufficient it says so, runs an
adaptive candidate → feedback → retry → escalation workflow, and evolves the knowledge base **only through human
verification**. Repeated unknown cases are clustered into emerging issues that a human can promote to a new intent.

> **SYNTHETIC / DEMO DATA** - every ticket and knowledge article in `data/` is synthetic. None of it is real
> telecom operator data.

```
GUIDED + FREE TEXT + VOICE ─► understanding ─► conversation memory ─► hybrid retrieval ─► rerank ─► evidence score
   KNOWN (≥0.70) ─► grounded RAG + citations
   UNCERTAIN / UNKNOWN ─► candidate resolution ─► feedback ─► YES: candidate knowledge ─► human approve ─► trusted KB ─► vector index
                                                             └► PARTIAL / NO: adaptive retry (alternative evidence) ─► escalate after 3
REPEATED UNKNOWN CASES ─► embeddings + clustering ─► emerging issue ─► human review ─► new intent + KB article ─► index update
```

> New here? `PROJECT_GUIDE.md` explains the project, how to run it, every page, and the client and server sides
> in plain language.

## Two portals: customer and admin

| URL | Who | What |
|---|---|---|
| `/` | **Customer** | Help center: article search, topics, popular articles, contact options, footer (with a "Staff login" link) |
| `/help/topic/:topic`, `/help/article/:id` | **Customer** | Topic pages and help articles built from the active knowledge base (agent-only notes are hidden) |
| chat widget (every customer page) | **Customer** | "Chat with us" corner widget: cited answers (sources link to help articles), Yes / Partly / No feedback, "Talk to a person" with queue position and cancel, "Your requests", live agent replies. `/user` or `/?chat=open` opens it directly |
| `/admin/...` | **Support admin** | Dashboard ("Needs attention"), Live inbox (handoff + agent replies, canned replies, j/k and ⌘Enter shortcuts), Cases, Test the assistant, Help articles, Review queue, Trending problems, Issue types, Reports, Settings (incl. your display name). The top bar searches cases, customers and articles (press `/`) |

**Workflow connecting the two (chat handoff states `bot → needs_agent → agent → bot | closed`):**

1. The customer messages → the same resolution pipeline answers with cited steps and creates a case (visible to admins).
2. Every **new** query that gets solved goes to the admin **Review queue** (a query is new unless its text is already in the dataset):
   - ✅ YES on an unverified answer → "Customer confirmed a fix"
   - ✅ YES on a verified answer to a new question → "New question, answered by an article" (approving adds a dataset example, not a duplicate article)
   - an agent marks a chat solved after replying → "Solved by an agent". The agent's replies become the proposed fix,
     cleaned for an article: greetings, apologies, the customer's name, questions asking for details and sign-offs are
     dropped; "Please restart your phone" becomes a step; work the agent did ("I've reissued your e-SIM") becomes an
     agent step ("Reissue the customer's e-SIM profile.") shown to customers as "We'll reissue your e-SIM profile."

   Approving a new fix publishes it as an **ACTIVE help article** (`KB-0xx`, source `human_verified_candidate`), titled
   with the issue type the reviewer picked. Every approved article gets a **Customer steps** section (one per
   resolution step; generated if the reviewer did not write one), so customers never see agent wording. The article is
   indexed immediately, so the next customer who describes the problem is answered from it.

   On approval the case is appended to the dataset CSV (`DATASET_PATH`, same 32 columns, `record_id` `TELCO-LIVE-…`,
   in the split its intent already belongs to), inserted into the tickets table and indexed for retrieval, so the next
   similar query is answered from it. Pick an issue type when approving; rows with no issue type cannot join the dataset. When an admin approves or
   rejects it, a notice is posted back into the customer's chat.
3. ❌ NO → automatic retry with alternative evidence; after 3 attempts the case is escalated and the chat moves to
   **Waiting** in the admin Live inbox. Critical issues (for example account takeover) and "Talk to a person"
   go there immediately.
4. An admin clicks **Assign to me** (or simply replies) → the bot stops answering, and agent messages appear live in the customer's
   chat as "<agent name> is helping you now" (3-second polling). Customer messages are routed to the agent and counted as unread in the inbox.
5. The admin clicks **Hand back to assistant** or **Mark solved & close**; open cases become `resolved_by_agent`. A new customer
   message reopens a closed chat with the bot.

**Sign-in.** Customers never log in. Staff sign in at `/admin` with a username and password (PBKDF2-hashed, signed
12-hour tokens, a 10-minute lockout after 5 failed attempts). Every agent API (inbox actions, cases, review queue,
article editing, trending problems, issue types, reports, settings, logs, "Test the assistant") needs a staff token; the
help center and the chat widget use only public endpoints, and the public article list shows published articles only.
The first account comes from `ADMIN_USERNAME` / `ADMIN_PASSWORD`; add more with
`backend/.venv/bin/python scripts/create_staff_user.py <username> --display-name "Priya S"`.

## Services

```
browser ─► frontend (nginx) ─► gateway  ── public + admin API, sign-in, chats, cases, review queue, orchestration
                                  ├─► nlu         intent / category, product, severity, sentiment, key details
                                  ├─► retrieval   hybrid semantic + keyword + metadata search, cross-encoder re-ranking
                                  └─► generation  LLM draft (Gemini, or the demo template) + grounding guard
```

One code base and one image; `SERVICE_ROLE` picks the role. The internal services publish no ports and accept only calls
carrying `INTERNAL_API_TOKEN`; the LLM key is given only to the services that call the LLM (generation, and nlu in AI
mode). Each gateway adapter subclasses the in-process service, so `SERVICE_ROLE=all` (the default, used for local runs
and the tests) runs the identical pipeline in one process. If the generation service is down the gateway answers with the
cited evidence-only template; if retrieval is down it returns `RETRIEVAL_FAILED` rather than guessing. The search index
rebuilds whenever the stored chunks change, so separate processes always see newly approved articles.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2, Pydantic 2 |
| Database | PostgreSQL + pgvector (Docker); automatic SQLite + in-memory cosine fallback for local runs |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (local); deterministic hashed n-gram fallback |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` (optional); falls back to the hybrid score |
| LLM | Provider abstraction: `GeminiProvider` (AI MODE) and `MockProvider` (DEMO MODE, no key needed) |
| Frontend | React 18, TypeScript, Vite, React Router, TanStack Query, plain CSS design system |
| Auth | Staff accounts (PBKDF2-SHA256), HMAC-signed bearer tokens, login lockout; public customer endpoints |
| Tests | pytest (279 tests), Vitest + Testing Library (42 tests), `scripts/verify_api.py` (43 live checks), `scripts/verify_llm.py` |

## Project structure

```
backend/
  app/
    main.py config.py database.py dependencies.py ingestion.py
    api/        health auth resolve feedback knowledge conversations emerging_issues intents analytics system _stream
                internal (nlu / retrieval / generation service endpoints)
    models/     ticket knowledge case resolution_attempt candidate_case conversation feedback emerging_issue intent evaluation staff
    schemas/    resolve feedback knowledge conversation emerging_issue common
    services/   classifier entity_extractor sentiment embeddings retrieval reranker evidence rag grounded_templates
                adaptive_resolution knowledge_evolution emerging_issue intent_admin memory llm_provider taxonomy
                evaluation analytics auth scope remote (gateway -> service clients) wire (service JSON format)
    utils/      logging validation errors text
  tests/        unit + integration + end-to-end tests
frontend/
  src/ components/ pages/ hooks/ services/ types/ utils/ styles/ test/
data/           tickets.csv knowledge_base.csv intent_taxonomy.csv support_categories.csv products.csv
                candidate_cases.csv eval_unknown_complaints.csv telecom_support_adaptive_60000.csv (your dataset)
scripts/        ingest_data.py validate_dataset.py migrate.py generate_embeddings.py evaluate.py verify_api.py verify_llm.py
                create_staff_user.py build_seed_data.py
docker-compose.yml  .env.example  .gitignore  .dockerignore  PROJECT_REQUIREMENTS_AUDIT.md
```

## Commands

All commands run from the repository root unless a `cd` is shown.

### 1. Open the project

```bash
cd path/to/telecom-support-assistant
```

### 2. Install frontend dependencies

```bash
cd frontend && npm install
```

### 3. Install backend dependencies

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

(Windows: `.venv\Scripts\pip install -r requirements-dev.txt`.) The first start downloads the two small local
models (~90 MB each) from Hugging Face; they are cached afterwards.

### 4. Create the environment file

```bash
cp .env.example .env
```

For local development **without PostgreSQL**, set this in `.env`:

```
DATABASE_URL=sqlite:///./data/telecom_support.db
```

Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` (10+ characters) in `.env` so the first staff account is created on start-up,
and sign in at `/admin` with them. Without `AUTH_SECRET_KEY`, development tokens stop working when the backend restarts;
production (`APP_ENV=production`) refuses to start without one.

### 5. Start PostgreSQL (optional locally, used by Docker)

```bash
docker compose up -d postgres
```

Then keep `DATABASE_URL=postgresql://telecom:telecom@localhost:5432/telecom_support` in `.env`. If PostgreSQL is
unreachable and `DB_FALLBACK_TO_SQLITE=true`, the backend falls back to SQLite instead of crashing.

### 6. Run migrations (create tables, enable pgvector)

```bash
backend/.venv/bin/python scripts/migrate.py
```

### 7. Validate and seed the data

```bash
backend/.venv/bin/python scripts/validate_dataset.py data/telecom_support_adaptive_60000.csv
```

```bash
backend/.venv/bin/python scripts/ingest_data.py --reset
```

Ingestion validates every row (missing values, empty strings, duplicate ticket/record IDs, invalid intents,
categories, severity, sentiment, split and timestamps). It writes rejected rows with reasons to
`data/rejected_rows.csv`; use `--strict` to abort on any rejection. It then inserts tickets, the KB and candidates,
chunks the documents, generates and stores embeddings, builds the index and runs emerging-issue clustering. It uses
`data/telecom_support_adaptive_60000.csv` if present, otherwise the demo `data/tickets.csv`
(`--dataset <path>` to choose). The backend also auto-seeds an empty database on first start (`AUTO_SEED=true`).

### 8. Generate embeddings (only new or changed chunks are embedded)

```bash
backend/.venv/bin/python scripts/generate_embeddings.py
```

### 9. Start the backend (http://127.0.0.1:8000, API docs at /api/v1/docs)

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 10. Start the frontend (http://127.0.0.1:5173)

```bash
cd frontend && npm run dev
```

The Vite dev server proxies `/api` to `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`).

### 11. Run tests

```bash
cd backend && .venv/bin/python -m pytest
```

```bash
cd frontend && npm test
```

```bash
backend/.venv/bin/python scripts/verify_api.py
```

`verify_api.py` signs in with the staff account from `.env`, exercises all endpoints against the running backend (and
checks that agent endpoints refuse anonymous calls) and writes demo data; run
`scripts/ingest_data.py --reset` afterwards for a clean database. To prove the fallbacks, run the backend suite with no
ML models:

```bash
cd backend && EMBEDDING_BACKEND=hashing RERANKER_ENABLED=false .venv/bin/python -m pytest
```

### 12. Run lint and type checks

```bash
cd backend && .venv/bin/ruff check app tests ../scripts
```

```bash
cd frontend && npm run lint && npm run typecheck && npm run build
```

### 13. Run with Docker (PostgreSQL + pgvector, gateway, nlu, retrieval, generation, frontend on http://localhost:8080)

Docker Compose needs three secrets, from the shell or a `.env` next to `docker-compose.yml`: `AUTH_SECRET_KEY`
(32+ characters), `INTERNAL_API_TOKEN` (16+ characters) and `ADMIN_PASSWORD` (10+ characters). Generate random values with
`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.

```bash
docker compose up --build
```

To run the services without Docker, start each role in its own terminal with the same `INTERNAL_API_TOKEN`:
`SERVICE_ROLE=nlu`, `retrieval` and `generation` on ports 8011–8013, then the gateway with `SERVICE_ROLE=gateway` and
`NLU_SERVICE_URL`, `RETRIEVAL_SERVICE_URL`, `GENERATION_SERVICE_URL` pointing at them.

### 14. Enable Gemini / AI MODE

Put the key in the **backend** `.env` only (it is never sent to the browser), then restart the backend:

```
DEMO_MODE=false
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.5-flash
```

Every Gemini answer still passes the grounding guard. If Gemini fails or times out (one retry on HTTP 429/5xx), the
deterministic evidence-only template is used and the answer says so. Check the live path with:

```bash
backend/.venv/bin/python scripts/verify_llm.py
```

It reports, for five sample complaints (including the use-case example), which generator answered, whether every step
cites a retrieved source, and what the guard removed; it exits non-zero unless every answer came from the LLM.

### 15. Run demo mode (default; no API keys needed)

```bash
DEMO_MODE=true backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8000
```

### Offline evaluation

The Reports page and `python -m scripts.evaluate` measure the same pipeline customers use, on three kinds of questions:

| Set | File | Used for |
|---|---|---|
| Realistic test questions (63, every issue type, labelled by hand) | `data/eval_realistic_complaints.csv` | The headline measurement. Never tuned on |
| Practice questions (64 + 55, different wording) | `data/tune_realistic_complaints.csv`, `data/tune2_realistic_complaints.csv` | Finding weaknesses to fix |
| Synthetic split + 4 seeded rewordings each (short, typos, casual, noise) | the 60K dataset | Regression checks; the split repeats a few templates |

Latest results on the realistic test set: issue type 92.1% (58/63), answered from a correct article 92.1%, correct
article in the top 3 98.4%, answered with steps 98.4%, clean customer wording 63/63. The synthetic rewordings score 8/8
in every wording on both splits.

Every rate on the Reports page is headlined by its 95% lower confidence bound (Wilson score), with the counts and the
measured rate underneath, so a perfect result on a small sample reads "≥ 68%" (8/8) rather than "100%": a model can
still be wrong, and a small sample cannot prove otherwise. Groundedness is shown as "Not measured" in demo mode
(steps are copied from sources) and citation completeness as "Enforced" (the safety check removes uncited steps).

How the classifier handles real wording (`backend/app/services/classifier.py`): keywords match by word stem and with
up to two words in between; unknown words of five or more letters are spelling-corrected against the classifier's
own vocabulary; context beats symptom ("travelling in Italy, no signal" is roaming); a specific billing issue beats a
dispute matched only on a catch-all word; matches in the product area the customer names get a bonus. When a
reviewer approves a new question under an issue type, the customer's wording becomes an example of that issue type,
so the next customer who puts it that way is recognised straight away (new questions improve the classifier, always
through human review). A question that matches no issue type is answered from the general checklist for its topic;
guessing the nearest issue type's article was tried and rejected because it chose wrong articles for new problems.

Each chat answer opens with a line written for what the customer said, built only from their words and the issue
type: a problem report gets "Sorry your broadband keeps dropping every evening. Since you've already restarted the
router, you can skip that step. Let's get your connection stable again:", a question gets "Let's reset your
password:", a retry gets "Let's try another way to …". "How do I reset…" is a question, not something already
tried; "took it out and put it back" counts as reseating the SIM. A travel destination makes a connectivity
question a roaming one (India is treated as home). When an issue type has several articles, the one whose
described symptoms best match the question is used (evening drops, weak Wi-Fi upstairs). 191 extra example
complaints (`scripts/seed_intent_examples.py`) are checked by a test to be independent of the test and practice sets.

```bash
backend/.venv/bin/python scripts/evaluate.py --split held_out_test --limit 120
```

It is also available from the Reports page.

## Demonstration script

| Demo | Steps | Expected |
|---|---|---|
| 1 | Admin → Test the assistant (or the customer chat) → “My broadband keeps disconnecting every evening around 8 PM.” | Broadband Disconnect · Internet › Broadband · evidence ≈0.9 KNOWN · steps cited to KB-031 / tickets |
| 2 | “I was charged twice on my bill this month” | Billing Dispute · KB-032 “Duplicate charge review” + similar ticket · citations |
| 3 | “The satellite emergency texting feature is greyed out on my phone” → **NO** → automatic attempt 2 → **YES** → Review queue → Review → edit content → Approve and publish → ask again in other words | "No help article matches this problem yet" (≈0.3) → candidate → approved KB article → same issue now KNOWN citing the new article |
| 4 | Submit 3 similar unseen complaints (e.g. visual voicemail transcription missing) → Trending problems → Create issue type | Pattern appears with occurrences; the new issue type classifies new complaints and they resolve KNOWN |
| Memory | Customer chat → “My broadband is slow.” then “Mostly at night.” | Second turn keeps intent Broadband Slow via `memory_carryover` |
| Handoff | Customer chat → Talk to a person; Admin → Live inbox → Assign to me → reply; Customer sees the reply; Admin → Mark solved & close | Chat moves Waiting for agent → With an agent → Closed on both sides |

## How it works

* **Understanding**: `ClassificationService` reads the taxonomy from the database. It uses the LLM in AI mode
  (constrained to known intents), then keyword rules, then embedding similarity to each intent's example complaints;
  otherwise it returns `unknown` and never forces a class. Rule-based entity extraction (time, frequency, duration,
  device, troubleshooting, customer context, money; account numbers are masked), sentiment and severity.
* **Hybrid retrieval**: `hybrid = 0.60·semantic + 0.25·keyword + 0.15·metadata` (configurable), with pgvector or
  in-memory cosine, BM25 and metadata filters (active knowledge only, guided category, excluded sources on retry).
  The top-K results are reranked by a cross-encoder.
* **Evidence**: `0.40·semantic + 0.20·reranker + 0.20·intent match + 0.10·source quality + 0.10·metadata`.
  KNOWN ≥ 0.70, UNKNOWN < 0.45. Thresholds live only in `backend/app/config.py`.
* **Grounding guard** (`services/rag.py`): every step must cite a supplied source. Fake citations are stripped,
  steps not supported by their cited text are removed, and money, percentage or time-limit figures absent from the
  evidence are rejected. If nothing grounded remains, the answer is downgraded to "evidence is insufficient".
* **Knowledge evolution**: customer YES creates a `candidate_cases` row only. A human approval creates a versioned
  ACTIVE KB article, embeds it and updates the index. Rejection keeps it out.
* **Memory**: messages plus a compact state (product, issue, intent, entities, troubleshooting, customer context,
  previous resolutions, feedback), bounded by `MEMORY_MAX_MESSAGES` / `MEMORY_MAX_CHARS`. Only genuine follow-ups
  inherit the active issue.

## Dataset notes (important for interpreting metrics)

* `telecom_support_adaptive_60000.csv`: 60,000 synthetic rows, 30 intents, 0 rows rejected by validation.
* The split is **intent-disjoint**, not stratified. `broadband_disconnects`, `service_outage` and
  `unexpected_charge` appear only in `held_out_test`; `account_security`, `billing_dispute` and `broadband_slow` only
  in `calibration`. Because those splits are never indexed, these intents rely on KB articles and the hand-authored
  `DEMO-` tickets in `data/tickets.csv`.
* The 60K rows come from about 86 complaint templates (only 8 distinct held-out texts once the
  `[synthetic case N]` tag is removed). Ticket chunks are de-duplicated per template, which gives 92 ticket groups
  plus 33 KB chunks. Offline metrics on such templated data are optimistic and should not be read as real-world accuracy.
* `mobile_data_not_working`, `broadband_no_internet` and `payment_failed` have only candidate (unverified) rows in the
  dataset; their KB articles (KB-001, KB-011, KB-021) are published so these complaints resolve KNOWN with citations.
* Five **general checklists** (KB-037 to KB-041, one per area) give unseen issues best-suitable, cited guidance. They
  are labelled "BEST-SUITABLE GUIDANCE", never count toward the evidence score (an unseen issue stays UNKNOWN and
  still goes through feedback, candidate knowledge and emerging-issue detection) and are excluded on retry so the next
  attempt uses different guidance. KB-042 is a DRAFT used to demonstrate draft approval.
* The Conversation page shows every AI reply with its cited steps, clickable sources and the
  "Did this solve the problem?" buttons; NO / PARTIAL / YES drive the same adaptive workflow inside the chat.
