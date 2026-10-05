# Technical Requirements – Support IQ

This document lists the technical requirements for Support IQ, the adaptive RAG-based
telecom support assistant. It covers what the system must do (functional requirements),
how well it must do it (non-functional requirements), and what it needs in order to run.
Each requirement has an ID so it can be referenced from tests and reviews. The
**Where** column points to the main place it is implemented.

Related documents: `DESIGN_DECISIONS.md`, `TECH_STACK_DECISIONS.md`,
`PROJECT_REQUIREMENTS_AUDIT.md`.

---

## 1. Scope

The system receives telecom support complaints from customers through a help-center website
or chat. It must:

1. understand each complaint,
2. retrieve relevant evidence from historical tickets and help articles,
3. generate a grounded, cited resolution,
4. detect issues it does not know,
5. adapt to customer feedback,
6. hand over to human agents when needed,
7. learn new knowledge only after human verification.

Support agents use a separate admin console to manage chats, cases, knowledge and reports.

---

## 2. Functional Requirements

### 2.1 Input and scope

| ID | Requirement | Where |
|---|---|---|
| FR-01 | The system shall accept complaints as free text, as a guided category plus text, and as voice input. | `ComplaintInput.tsx`, `ChatWidget.tsx`, `VoiceButton.tsx` |
| FR-02 | All three input modes shall go through the same resolution pipeline. | `adaptive_resolution.py` |
| FR-03 | Voice input shall be converted to text in the browser and submitted like a typed complaint. | `useSpeechRecognition.ts` |
| FR-04 | Complaints shall be limited to 2,000 characters and validated before processing. | `config.py`, `schemas/` |
| FR-05 | The system shall answer only telecom questions. Unrelated questions shall receive a polite reply and shall not create a case. | `scope.py` |
| FR-06 | Greetings and thank-you messages shall receive a short friendly reply. | `scope.py` |

### 2.2 Complaint understanding

| ID | Requirement | Where |
|---|---|---|
| FR-07 | The system shall identify the intent of each complaint from the intent taxonomy, or mark it as `unknown`. | `classifier.py` |
| FR-08 | The system shall identify the category, product, severity (low / medium / high / critical) and sentiment (positive / neutral / negative / frustrated / urgent). | `classifier.py`, `sentiment.py` |
| FR-09 | The system shall extract entities such as device, time reference, amount and location. | `entity_extractor.py` |
| FR-10 | Critical issues shall be routed to a human agent immediately. | `adaptive_resolution.py`, `handoff.py` |
| FR-11 | The system shall keep conversation memory and apply it to genuine follow-up messages only. | `memory.py` |

### 2.3 Retrieval and evidence

| ID | Requirement | Where |
|---|---|---|
| FR-12 | The system shall create embeddings for complaints, ticket templates and help-article chunks. | `embeddings.py` |
| FR-13 | Retrieval shall combine semantic similarity (0.60), BM25 keyword score (0.25) and metadata match (0.15). | `retrieval.py` |
| FR-14 | The top candidates shall be reranked with a cross-encoder when it is available. | `reranker.py` |
| FR-15 | Only development-split tickets and active help articles shall be searchable. | `ingestion.py`, `retrieval.py` |
| FR-16 | The system shall compute an evidence score: 0.40 semantic + 0.20 reranker + 0.20 intent match + 0.10 source quality + 0.10 metadata. | `evidence.py` |
| FR-17 | Each complaint shall be classified as Known (≥ 0.70), Uncertain (0.45–0.70) or Unknown (< 0.45). | `evidence.py`, `config.py` |
| FR-18 | General checklists shall not raise the evidence score. | `evidence.py` |

### 2.4 Resolution generation

| ID | Requirement | Where |
|---|---|---|
| FR-19 | Resolutions shall be generated only from retrieved evidence. | `rag.py`, `grounded_templates.py` |
| FR-20 | Every resolution step shall cite at least one source (help article or ticket). | `rag.py` |
| FR-21 | A grounding check shall remove any step that is not supported by the evidence. | `rag.py` |
| FR-22 | The system shall use Gemini when configured, and grounded templates otherwise (demo mode). | `llm_provider.py` |
| FR-23 | Unknown issues shall receive the closest relevant guidance and related help articles, without being forced into an existing intent. | `rag.py`, `AssistantResolution.tsx` |
| FR-24 | Steps the customer has already tried shall be marked as such. | `grounded_templates.py` |

### 2.5 Feedback, retry and escalation

| ID | Requirement | Where |
|---|---|---|
| FR-25 | After each resolution the customer shall be asked whether it solved the problem: solved, partially solved or not solved. | `feedback.py`, `AssistantResolution.tsx` |
| FR-26 | "Partially solved" shall ask for more information and retry using it. | `adaptive_resolution.py` |
| FR-27 | "Not solved" shall trigger a retry that excludes sources already used and avoids repeating earlier steps. | `adaptive_resolution.py` |
| FR-28 | A case shall allow at most 3 resolution attempts. | `config.py` |
| FR-29 | After the third unsuccessful attempt the case shall be escalated and the chat moved to the admin inbox. | `adaptive_resolution.py`, `handoff.py` |
| FR-30 | Feedback can be given only once per attempt and only for the latest attempt. | `adaptive_resolution.py` |

### 2.6 Human handoff

| ID | Requirement | Where |
|---|---|---|
| FR-31 | Chats shall have the states: assistant (`bot`), waiting (`needs_agent`), with an agent (`agent`) and closed. | `handoff.py` |
| FR-32 | Customers shall be able to request a person, see their queue position and cancel the request. | `handoff.py`, `ChatWidget.tsx` |
| FR-33 | Agents shall be able to assign a chat, reply, hand it back to the assistant, and mark it solved and close it. | `conversations.py`, `InboxPage.tsx` |
| FR-34 | While an agent handles a chat, the assistant shall not reply, and customer messages shall be counted as unread for the agent. | `conversations.py` |
| FR-35 | A new customer message shall reopen a closed chat with the assistant. | `handoff.py` |
| FR-36 | Both sides shall see updates within about 3 seconds. | `ChatWidget.tsx`, `InboxPage.tsx` |

### 2.7 Knowledge evolution and dataset learning

| ID | Requirement | Where |
|---|---|---|
| FR-37 | No new solution shall become trusted knowledge without human approval. | `knowledge_evolution.py` |
| FR-38 | A solved query that is not already in the dataset shall create a review queue item. | `adaptive_resolution.py` |
| FR-39 | A chat solved by an agent shall create a review queue item using the agent's replies, if the agent replied. | `handoff.py`, `knowledge_evolution.py` |
| FR-40 | Review items shall record their origin: customer-confirmed fix, new question answered by an article, or solved by an agent. | `candidate_case.py` |
| FR-41 | Reviewers shall be able to edit the title, content and issue type, and approve or reject. | `CandidatesPage.tsx`, `knowledge.py` |
| FR-42 | On approval, a help article shall be published (except for article matches), and the case shall be added to the tickets table and the search index. | `knowledge_evolution.py` |
| FR-43 | On approval, a row with the same 32 columns shall be appended to the dataset CSV, with a record ID starting `TELCO-LIVE-`, in the split its intent belongs to. | `knowledge_evolution.py` |
| FR-44 | Appended rows shall pass the same validation as the original dataset and shall not be duplicated on re-ingestion. | `validation.py`, `ingestion.py` |
| FR-45 | The customer shall be notified in their chat when a fix they confirmed is approved or reviewed. | `knowledge_evolution.py` |
| FR-46 | Help articles shall support create, edit and version history. | `knowledge.py`, `KnowledgePage.tsx` |

### 2.8 Emerging issues

| ID | Requirement | Where |
|---|---|---|
| FR-47 | Repeated unknown complaints shall be clustered by similarity, with a minimum of 3 per cluster. | `emerging_issue.py` |
| FR-48 | Each cluster shall show occurrences, average evidence score, examples and a status (New, Under review, Approved, Rejected). | `emerging_issue.py`, `EmergingPage.tsx` |
| FR-49 | An admin shall be able to create a new intent from a cluster, after which new complaints are classified with it. | `intent_admin.py` |

### 2.9 Customer website

| ID | Requirement | Where |
|---|---|---|
| FR-50 | The customer site shall provide a help-center home page, article search, topic pages and article pages. | `site/` |
| FR-51 | Agent-only article notes, internal IDs and scores shall not be shown to customers. | `ArticlePage.tsx`, `AssistantResolution.tsx` |
| FR-52 | The chat widget shall be available on every customer page. | `SiteLayout.tsx`, `ChatWidget.tsx` |
| FR-53 | Customer-facing wording shall be plain and positive (no "couldn't find" or "not verified" messages). | `ChatWidget.tsx`, `AssistantResolution.tsx` |

### 2.10 Admin console

| ID | Requirement | Where |
|---|---|---|
| FR-54 | The admin console shall provide: dashboard, live inbox, cases, test tool, help articles, review queue, trending problems, issue types, reports and settings. | `pages/` |
| FR-55 | The test tool shall show the issue summary, retrieved sources, evidence score, cited resolution and processing steps. | `SupportPage.tsx` |
| FR-56 | The dashboard shall highlight customers waiting, fixes to review, escalated cases and trending problems. | `DashboardPage.tsx` |
| FR-57 | The admin console shall provide search across cases, customers and articles. | `TopNavigation.tsx` |

### 2.11 Data ingestion and evaluation

| ID | Requirement | Where |
|---|---|---|
| FR-58 | The dataset shall be validated before loading: required columns, missing and empty values, duplicates, valid values, timestamps, score ranges and entity JSON. | `validation.py` |
| FR-59 | Rejected rows shall be reported with row numbers and reasons, never silently dropped. A strict mode shall stop loading on any rejection. | `validation.py`, `ingestion.py` |
| FR-60 | The dataset shall be split by intent into development, calibration and held-out test sets. | dataset, `ingestion.py` |
| FR-61 | The system shall provide analytics (cases, resolution rates, evidence status, escalations, trends) and an offline evaluation on the calibration and held-out splits. | `analytics.py`, `evaluation.py` |

---

## 3. Non-Functional Requirements

### 3.1 Performance

| ID | Requirement |
|---|---|
| NFR-01 | A resolution should be returned within about 2 seconds on a typical laptop in demo mode (retrieval itself takes milliseconds). |
| NFR-02 | LLM calls shall time out after 25 seconds and fall back to grounded templates. |
| NFR-03 | Embeddings shall be computed once at ingestion and reused. Only changed chunks are re-embedded. |
| NFR-04 | Live chat and inbox updates shall poll no more often than every 3 seconds. |

### 3.2 Reliability

| ID | Requirement |
|---|---|
| NFR-05 | If PostgreSQL is unreachable, the backend shall retry (5 attempts, 2 s apart) and then fall back to SQLite. |
| NFR-06 | If sentence-transformers or the reranker is unavailable, the system shall fall back to hashing embeddings and hybrid ranking. |
| NFR-07 | Failure of any single dependency shall not stop the application from starting. |
| NFR-08 | Writes to the dataset file shall be serialised so that concurrent approvals cannot corrupt it. |

### 3.3 Accuracy and trust

| ID | Requirement |
|---|---|
| NFR-09 | No unsupported troubleshooting step shall reach the user. |
| NFR-10 | Every answer shall be traceable to its sources from the admin console. |
| NFR-11 | Evaluation shall use intent-disjoint splits so that results reflect unseen issues. |

### 3.4 Security and privacy

| ID | Requirement |
|---|---|
| NFR-12 | API keys shall be stored only in the backend `.env` file and never sent to the browser or written to logs. |
| NFR-13 | `.env` shall be excluded from version control; `.env.example` shall contain no secrets. |
| NFR-14 | Request bodies shall be limited to 64 KB, and API schemas shall reject unknown fields. |
| NFR-15 | Errors shall return a code, a readable message and a request ID, never a stack trace. |
| NFR-16 | Customers shall be reminded not to share passwords, PINs or card numbers in chat. |
| NFR-17 | All data shall be clearly labelled as synthetic. |
| NFR-18 | *(Open)* The admin console shall require authentication before real-world deployment. |

### 3.5 Usability

| ID | Requirement |
|---|---|
| NFR-19 | The customer site shall work on laptop screens and adapt to narrow screens without horizontal scrolling. |
| NFR-20 | Interactive elements shall have accessible labels; the UI shall be usable with a keyboard. |
| NFR-21 | Customer messages shall avoid technical and negative wording. |

### 3.6 Maintainability and portability

| ID | Requirement |
|---|---|
| NFR-22 | Thresholds, weights, model names and paths shall be configurable without code changes. |
| NFR-23 | The same code shall run on PostgreSQL + pgvector and on SQLite. |
| NFR-24 | The project shall run without any paid service or API key (demo mode). |
| NFR-25 | The system shall be deployable with a single `docker compose up --build`. |
| NFR-26 | The backend and frontend shall have automated tests, and the tests shall not modify real data. |

---

## 4. System Requirements

### 4.1 Software

| Component | Requirement |
|---|---|
| Python | 3.11 or later (3.12 in Docker) |
| Node.js | 18 or later (20 in Docker) |
| Database | SQLite (bundled), or PostgreSQL 16 with the pgvector extension |
| Browser | A current Chrome, Edge, Firefox or Safari; Chrome or Edge for voice input |
| Optional | Docker and docker-compose; a Gemini API key |

### 4.2 Hardware (local development)

| Resource | Minimum |
|---|---|
| CPU | Any modern 64-bit CPU (no GPU required) |
| Memory | 4 GB free (8 GB recommended with sentence-transformers) |
| Disk | About 1 GB for the dataset, database and models |

### 4.3 Ports

| Service | Port |
|---|---|
| Backend API | 8000 |
| Front end (dev server) | 5173 |
| Front end (Docker / Nginx) | 8080 |
| PostgreSQL (Docker) | 5432 |

---

## 5. Interface Requirements

- **API style:** REST over HTTP with JSON, under the `/api/v1` prefix.
- **Streaming:** `/resolve/stream` and `/resolve/retry/stream` return newline-delimited JSON
  (NDJSON) progress events, then the final result.
- **Error format:** `{"error": {"code": "...", "message": "...", "request_id": "..."}}`.
- **Main endpoint groups:** health and settings; resolve and retry; feedback; cases;
  conversations and handoff; knowledge and candidates; emerging issues; intents; analytics.
  See the project documentation for the full list.
- **CORS:** only the configured front-end origins are allowed.

---

## 6. Data Requirements

| ID | Requirement |
|---|---|
| DR-01 | The main dataset shall be a CSV with 32 columns, from `record_id` through `source_type`. |
| DR-02 | Required columns shall not be empty, except `customer_id`, `conversation_context` and `previous_troubleshooting`. |
| DR-03 | Record IDs and ticket IDs shall be unique. |
| DR-04 | Intent and category values shall exist in the intent taxonomy. |
| DR-05 | Severity, sentiment, split, resolution status, evidence status and knowledge state shall use the allowed values. |
| DR-06 | Evidence scores shall be between 0 and 1, and resolution attempts shall be 1 or more. |
| DR-07 | Supporting files shall include the knowledge base, intent taxonomy, support categories and products. |
| DR-08 | Data appended through approval shall meet DR-01 to DR-06. |

---

## 7. Constraints and Assumptions

- The dataset and knowledge base are synthetic; real customer data is not used.
- The system answers in English only.
- There is no admin authentication in this version (see NFR-18).
- Live updates use polling, not WebSockets.
- A query counts as "new" when its exact wording is not already in the dataset.

---

## 8. Verification

| Area | How it is verified |
|---|---|
| Functional requirements | 94 backend tests (pytest) and 30 front-end tests (Vitest) |
| End-to-end workflows | Manual runs on the live application: known issue, reworded complaint, unknown issue, retry and escalation, learning loop, emerging issues, memory, voice, handoff, off-topic questions |
| Dataset | `python scripts/validate_dataset.py` (all 60,000 rows pass) |
| API | `python scripts/verify_api.py` against a running backend |
| Quality | `python scripts/evaluate.py --split held_out_test` |
