# Support IQ: Project Guide

A plain-language guide to what this project is, how to run it, what every web page does, and how the client
(browser) and server (backend) parts work together. For the full command reference see `README.md`; for the
requirement-by-requirement status see `PROJECT_REQUIREMENTS_AUDIT.md`.

> All tickets and help articles in `data/` are **synthetic demo data**, not real telecom operator data.

---

## 1. What the project is

Support IQ is a telecom customer-support assistant with two websites in one app:

| Website | Who uses it | What it is for |
|---|---|---|
| **Customer help center** (`/`) | Customers | Search help articles, browse topics, and chat with the assistant or a person |
| **Agent workspace** (`/admin`) | Support agents and reviewers (sign-in required) | Answer customers live, review new knowledge, manage articles and issue types, and track quality |

When someone describes a problem (for example *"My broadband drops every evening around 8 and I've already restarted
the router twice"*), the assistant:

1. **Understands it**: issue type (e.g. Broadband Disconnect), product, severity, sentiment and key details (time,
   device, what was already tried).
2. **Searches** 60,000 past tickets and the help articles by meaning, by keywords and by category.
3. **Checks the evidence**: a confidence score labelled *Known*, *Uncertain* or *Unknown*.
4. **Answers with cited steps** taken from those sources, in plain wording for customers and precise instructions
   for agents. A safety check removes any step that no source supports.
5. **Learns, with human approval**: confirmed fixes go to a review queue, and only approved fixes become help
   articles, dataset rows and classifier examples.

---

## 2. How to run it

### Requirements
- Python 3.11 or newer, and Node.js 20 or newer
- About 300 MB of free disk space for the two local AI models (downloaded once on first start)
- Optional: Docker, if you want PostgreSQL and the split services

### First-time setup (from the project folder)

```bash
cd frontend && npm install
```

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cp .env.example .env
```

Then edit `.env`:
- `DATABASE_URL=sqlite:///./data/telecom_support.db` runs without PostgreSQL.
- `ADMIN_USERNAME` and `ADMIN_PASSWORD` (10+ characters) create the first agent account on start-up.
- `AUTH_SECRET_KEY` keeps agents signed in across restarts.

### Start the app (two terminals)

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend && npm run dev
```

| Open | What you get |
|---|---|
| http://127.0.0.1:5173 | Customer help center and chat |
| http://127.0.0.1:5173/admin | Agent workspace (sign in with `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env`) |
| http://127.0.0.1:8000/api/v1/docs | Interactive API documentation |

On the first start the backend builds the database from the 60,000-ticket dataset (about 10 seconds) and downloads the
AI models. If another copy of the app is already using ports 8000 and 5173, stop it first.

### Optional: AI mode (Gemini)
By default the app runs in **demo mode**: answers are built from article and ticket text, with no API key needed. For
answers written by an LLM, set `DEMO_MODE=false` and `GEMINI_API_KEY=…` in `.env`, restart the backend, then check it:

```bash
backend/.venv/bin/python scripts/verify_llm.py
```

### Optional: Docker (PostgreSQL + all services)

```bash
AUTH_SECRET_KEY=... INTERNAL_API_TOKEN=... ADMIN_PASSWORD=... docker compose up --build
```

Then open http://localhost:8080 (see section 6 for what runs where).

### Useful commands

| Task | Command |
|---|---|
| Backend tests | `cd backend && .venv/bin/python -m pytest` |
| Frontend tests | `cd frontend && npm test` |
| Check every API endpoint on a running backend | `backend/.venv/bin/python scripts/verify_api.py` |
| Add an agent account | `backend/.venv/bin/python scripts/create_staff_user.py <username>` |
| Change an agent's password | `backend/.venv/bin/python scripts/create_staff_user.py <username> --reset-password` |
| Rebuild the database from the data files | `backend/.venv/bin/python -m scripts.ingest_data --reset` |
| Run the offline quality evaluation | `backend/.venv/bin/python -m scripts.evaluate --split held_out_test` |

---

## 3. Customer pages (public, no sign-in)

| Page | Address | What it shows and how it works |
|---|---|---|
| **Help center home** | `/` | Search box with popular searches, **Browse by topic** tiles (Internet, Mobile, Calls, SMS, SIM, Billing, Recharge, Account, Roaming), popular articles and contact options. Topics and articles are loaded live from the server, so new approved articles appear automatically. |
| **Topic page** | `/help/topic/<topic>` | Every published article in one topic, e.g. all Internet articles. |
| **Help article** | `/help/article/<KB-id>` | One article: *What you might notice* (symptoms) and *How to fix it*, written for customers. Agent-only notes (escalation rules, cautions) are never shown. Links to related articles and the chat. |
| **Page has moved** | any unknown address | A friendly "this page has moved" page with links back to the help center, instead of an error. |

### The chat widget ("Chat with us", on every customer page)

| Feature | How it works |
|---|---|
| Start a chat | The customer enters a first name; the server creates a chat session, remembered in the browser. |
| Ask a question | Type, tap a suggested topic, or speak (voice input uses the browser's speech recognition). |
| The answer | Step-by-step instructions in plain wording, with links to the help articles they come from. Steps the customer already tried are marked "you've already tried this". |
| "Did this solve it?" | **Yes** sends the fix to the review queue. **Partly** asks for more details and tries again. **I still need help** retries with different sources, up to 3 attempts, then passes the chat to a person. |
| Off-topic questions | Questions that aren't about telecom services get a polite "Sorry, I can't help with that" reply. Greetings and thanks get a friendly reply. Vague messages ("it's not working") get a question about which service is affected. |
| Follow-ups | Short follow-ups like "Mostly at night" are understood as part of the same problem (conversation memory). |
| Talk to a person | The button, or typing "talk to a human", puts the chat in the agent queue and shows the queue position, with a Cancel option. When an agent joins, their replies appear live in the same chat. |
| Your requests | A list of the customer's cases from this chat and their status. |
| Notices | When a reviewer approves a fix the customer confirmed, a thank-you notice appears in their chat. |

---

## 4. Agent workspace pages (`/admin`, sign-in required)

Agents sign in with a username and password. The session lasts 12 hours, and 5 wrong passwords lock the account for
10 minutes. The top bar has a **search** (press `/`) across cases, customers and articles, a **system health**
indicator, the agent's display name (shown to customers on replies) and **Sign out**.

| Page | Address | What it shows and how it works |
|---|---|---|
| **Dashboard** | `/admin` | **Needs attention**: customers waiting for an agent, fixes to review, escalated cases and trending problems. Also headline numbers and a 14-day chart of cases. |
| **Live inbox** | `/admin/inbox` | All customer chats, filtered by *Waiting*, *With an agent*, *Assistant* or *Closed*, with unread counts. Open a chat to read the whole conversation, including the assistant's cited answers. **Assign to me** takes the chat (the assistant stops answering); typing a reply also assigns it. **Canned replies**, `j`/`k` to move between chats and `Cmd`/`Ctrl`+`Enter` to send. **Hand back to assistant** or **Mark solved & close** ends the agent's part. |
| **Cases** | `/admin/cases` | Every customer request with each attempt the assistant made, the sources it used, the confidence and the customer's feedback. Filter by status. |
| **Test the assistant** | `/admin/support` | Paste any complaint and watch the pipeline run step by step: understanding, search, re-ranking, evidence, answer and citations. Shows the issue type, product, severity, sentiment, sources, confidence and the cited answer. This is the agent tool for Use Case 2. |
| **Help articles** | `/admin/knowledge` | Create, edit and publish articles. Every edit is saved as a new version with history. Each article has agent steps ("Resolution steps") and the same steps in plain words for customers ("Customer steps"). |
| **Review queue** | `/admin/candidates` | New knowledge waiting for human approval: fixes customers confirmed, new questions answered by an existing article, and fixes from agents. A reviewer edits, chooses the issue type, and approves or rejects. Approving publishes the article, adds the case to the dataset CSV, makes it searchable immediately, and teaches the classifier the customer's wording. |
| **Trending problems** | `/admin/emerging` | Groups of similar questions the assistant couldn't match to any issue type (3 or more reports). A reviewer can turn a group into a new issue type with its own help article. |
| **Issue types** | `/admin/intents` | The 30 issue types the assistant recognises (plus any added), with their keywords and examples. New types can be added here. |
| **Reports** | `/admin/analytics` | Resolution performance and the offline quality evaluation (see below). |
| **Settings** | `/admin/settings` | Assistant behaviour (evidence thresholds, search weights and other tunable values) and the agent's display name. |

### How the Reports page measures quality
- **Realistic customer questions (shown first):** 63 hand-labelled questions worded the way customers write. It reports
  whether the issue type was right, whether the answer came from a correct article, and wording quality, plus a table of
  every miss. This set is never used for tuning; two separate practice sets are.
- **Synthetic split:** the template tickets, each also tested in four seeded rewordings (short, typos, casual, extra
  noise), with accuracy per wording.
- **No bare "100%":** every rate is headlined by its 95% lower confidence bound, with the counts underneath. For example
  8/8 correct reads "≥ 68%", because a perfect score on a small sample doesn't prove the model is never wrong.
  Groundedness shows *Not measured* in demo mode, and citation completeness shows *Enforced* by the safety check.

---

## 5. Client side (frontend, `frontend/`)

The client is a single-page web app: **React 18 + TypeScript**, built with **Vite**, using React Router for pages and
TanStack Query for loading and refreshing data. It contains no secrets and no AI logic; it only calls the server's API.

| Folder | Contents |
|---|---|
| `src/App.tsx` | Page routes: the customer site and the `/admin` workspace (shown only after sign-in) |
| `src/site/` | Customer website: home, topic, article and "page moved" pages, the chat widget, and article parsing (customer steps only) |
| `src/pages/` | Agent workspace pages (dashboard, inbox, cases, test the assistant, articles, review queue, trending, issue types, reports, settings, sign-in) |
| `src/components/` | Shared pieces: the answer display (`AssistantResolution`, with customer and agent versions), citations, charts, navigation, voice button, modals, toasts |
| `src/services/api.ts` | The single place that talks to the server; it adds the agent's sign-in token to requests and signs out on an expired session |
| `src/hooks/` | Chat session, agent display name, sign-in token, speech recognition, toasts |
| `src/types/api.ts` | The shapes of the data exchanged with the server |
| `src/test/` | Frontend tests (Vitest and Testing Library) |

**How live updates work:** the chat widget and the admin inbox refresh every 3 seconds, so an agent's reply appears in
the customer's chat, and a customer's message appears in the inbox, without reloading. "Test the assistant" streams the
pipeline stages as they finish.

**How sign-in works on the client:** `/admin` shows the sign-in page until a token is stored. Every admin request sends
`Authorization: Bearer <token>`. If the server rejects the token (expired or invalid), the client signs the agent out.
Customer pages never send or need a token.

---

## 6. Server side (backend, `backend/`)

The server is a **FastAPI** (Python) application with **SQLAlchemy** for the database: SQLite locally, or PostgreSQL
with pgvector in Docker. All API addresses start with `/api/v1`.

### Main parts (`backend/app/`)

| Folder / file | Contents |
|---|---|
| `main.py` | Starts the app, creates tables, seeds the database on first start, syncs data-file updates into existing databases, creates the first agent account, loads models |
| `config.py` | Every setting, read from `.env` |
| `api/` | The web endpoints (listed below) |
| `services/classifier.py` | Understanding: issue type (keywords with word-stem and spelling-tolerant matching, plus example similarity), product, category |
| `services/sentiment.py`, `entity_extractor.py` | Sentiment, severity and key details (times, devices, steps already tried; account numbers masked) |
| `services/retrieval.py`, `reranker.py`, `embeddings.py` | Hybrid search (meaning + keywords + category) and re-ranking with local AI models |
| `services/evidence.py` | The confidence score (Known / Uncertain / Unknown) |
| `services/rag.py`, `grounded_templates.py`, `wording.py` | Writing the cited answer, the safety check, and customer wording |
| `services/adaptive_resolution.py` | The full pipeline, retries and escalation |
| `services/knowledge_evolution.py` | Review queue, approvals, help articles, dataset updates and learning customer wording |
| `services/emerging_issue.py`, `intent_admin.py` | Trending problems and new issue types |
| `services/handoff.py`, `memory.py`, `scope.py` | Agent handoff, conversation memory, off-topic and greeting handling |
| `services/auth.py` | Agent accounts, password hashing, sign-in tokens and lockout |
| `services/evaluation.py` | The offline quality evaluation behind the Reports page |
| `models/`, `schemas/` | Database tables and request/response formats |

### Endpoints

**Public** (used by the customer site; no sign-in):

| Method and path | Purpose |
|---|---|
| `GET /health` | System status |
| `POST /conversations`, `GET /conversations/{id}`, `POST /conversations/{id}/message` | Start a chat, read it, send a message |
| `POST /conversations/{id}/handoff` (`request` / `cancel`) | Ask for, or cancel, a person |
| `POST /feedback`, `POST /resolve/retry` (+ `/stream`) | Yes / Partly / No, and the next attempt |
| `GET /cases/{id}` | One case (for the answer display) |
| `GET /knowledge`, `GET /knowledge/{id}`, `GET /intents` | Published articles and topics only |
| `POST /auth/login` | Agent sign-in |

**Agents only** (need the sign-in token):

| Method and path | Purpose |
|---|---|
| `GET /auth/me` | Who is signed in |
| `POST /resolve` (+ `/stream`) | Test the assistant |
| `GET /cases` | All cases |
| `GET /conversations`, `POST /conversations/{id}/agent-message`, `/read`, `/handoff` (`take` / `release` / `close`) | Live inbox |
| `POST /knowledge`, `PUT /knowledge/{id}` | Create and edit articles |
| `GET /candidates`, `POST /knowledge/{id}/approve`, `POST /knowledge/{id}/reject` | Review queue |
| `GET /emerging-issues` (+ `/{id}`, `/detect`, `/{id}/status`, `/{id}/create-intent`) | Trending problems |
| `POST /intents` | New issue type |
| `GET /analytics`, `POST /analytics/evaluate`, `GET /analytics/evaluations` | Reports |
| `GET` / `PUT /settings`, `GET /logs` | Settings and system logs |

### One process or separate services
Locally everything runs in **one process** (`SERVICE_ROLE=all`). In Docker the same code runs as separate services,
chosen by `SERVICE_ROLE`:

```
browser ─► frontend (nginx) ─► gateway   public + agent API, sign-in, chats, cases, review queue
                                  ├─► nlu         understanding (issue type, product, severity, sentiment)
                                  ├─► retrieval   hybrid search + re-ranking
                                  └─► generation  answer writing + safety check (the only service with the LLM key)
```

The internal services expose no ports to the outside, and accept only calls carrying the shared `INTERNAL_API_TOKEN`
(`/internal/v1/classify`, `/search`, `/rerank`, `/generate`, `/health`). If the answer-writing service is down, the
gateway falls back to the cited template answer; if search is down, it reports the error rather than guessing.

---

## 7. How a question flows through the system

```
Customer types "no internet since morning" in the chat widget
   │  (client) POST /api/v1/conversations/{id}/message
   ▼
Server: telecom question?  ── no ──► "Sorry, I can't help with that…"
   │ yes
   ▼
Understanding ─ issue type: Broadband No Internet · product: broadband · severity · sentiment · details
   ▼
Search ─ 60K tickets + help articles (meaning + keywords + category) ─► re-rank ─► keep the question's topic
   ▼
Evidence score ─ Known / Uncertain / Unknown
   ▼
Answer ─ steps from the issue type's own article (KB-011), each cited; customer wording attached
   ▼  safety check removes unsupported steps
(client) shows the steps, article links and "Did this solve it?"
   │
   ├─ Yes ──► Review queue ──► reviewer approves ──► article + dataset row + classifier learns the wording
   ├─ Partly ─► asks for details ─► tries again
   └─ No ────► tries different sources (up to 3) ─► then the Live inbox for a person
```

---

## 8. Data files (`data/`)

| File | Contents |
|---|---|
| `telecom_support_adaptive_60000.csv` | The 60,000 synthetic tickets (validated on load; split into development, calibration and held-out test) |
| `knowledge_base.csv` | The 42 help articles, with agent steps and customer steps |
| `intent_taxonomy.csv`, `support_categories.csv`, `products.csv` | Issue types, topics and product keywords |
| `eval_realistic_complaints.csv` | 63 realistic test questions (never tuned on) |
| `tune_realistic_complaints.csv`, `tune2_realistic_complaints.csv` | Practice questions used for tuning |
| `eval_unknown_complaints.csv` | Out-of-scope questions, to check that unknown issues are recognised as new |

The local database (`data/*.db`) is created automatically and is not part of the repository.
