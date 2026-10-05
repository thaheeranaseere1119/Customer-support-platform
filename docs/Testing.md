# Testing Requirements – Support IQ

This document describes how Support IQ must be tested: what has to be covered, at which
levels, in which environment, and what counts as a pass. It also maps the requirements in
`TECHNICAL_REQUIREMENTS.md` to the tests that cover them, and lists the manual end-to-end
scenarios that must be run before a demonstration or release.

---

## 1. Objectives

Testing must show that:

1. Answers are built only from retrieved evidence, and every step is cited.
2. Known, uncertain and unknown issues are told apart correctly.
3. The feedback, retry and escalation workflow behaves as specified.
4. Nothing becomes trusted knowledge or enters the dataset without human approval.
5. The customer website and admin console stay in sync during handoff.
6. Unrelated questions are declined and create no case.
7. The system fails safely when a dependency (database, model, LLM) is unavailable.
8. Customers never see internal scores, IDs, agent-only notes or stack traces.

---

## 2. Scope

**In scope**
- Backend services: understanding, retrieval, evidence, generation, adaptive workflow,
  handoff, knowledge evolution, emerging issues, memory, scope check, analytics.
- REST API, including validation, error format and streaming.
- Dataset validation, ingestion and dataset learning.
- Customer website and chat widget.
- Admin console pages.
- End-to-end workflows across both sides.

**Out of scope for this version**
- Load and stress testing beyond a single user.
- Penetration testing. The admin console has no login yet (see NFR-18).
- Live Gemini output quality. Automated tests run in demo mode with grounded templates so
  results are repeatable.

---

## 3. Test Levels

| Level | What it checks | Tool | Location |
|---|---|---|---|
| Unit | Single functions and services: scoring, BM25, validation, classifier, grounding check | pytest | `backend/tests/` |
| Integration | Services working together through the API and database | pytest + FastAPI `TestClient` | `backend/tests/` |
| Component | Individual React components and pages with a mocked API | Vitest + Testing Library | `frontend/src/test/` |
| End-to-end (automated) | Full pipeline from complaint to cited answer, including streaming | pytest (`test_e2e.py`) | `backend/tests/` |
| End-to-end (manual) | Real browser use of both sides against a running backend | Browser | Section 7 |
| Data | Dataset validation and split integrity | pytest, `validate_dataset.py` | `backend/tests/`, `scripts/` |
| Evaluation | Classification and ranking quality on unseen intents | `evaluate.py` | `scripts/` |
| Smoke | Every endpoint of a running backend | `verify_api.py` | `scripts/` |

---

## 4. Test Environment

### 4.1 Automated tests

| Item | Requirement |
|---|---|
| Python | 3.11 or later, with `requirements-dev.txt` installed |
| Node.js | 18 or later, with `npm install` run in `frontend/` |
| Database | A temporary SQLite database created per test session |
| Dataset | A temporary **copy** of `data/tickets.csv` (the small demo dataset) |
| LLM | Demo mode (`DEMO_MODE=true`, no API key) |
| Embeddings | Whatever is installed; tests must pass with the hashing fallback |

**Rule:** automated tests must never write to the real database or to
`telecom_support_adaptive_60000.csv`. `backend/tests/conftest.py` enforces this by pointing
`DATABASE_URL` and `DATASET_PATH` to a temporary folder.

### 4.2 Manual end-to-end tests

- Backend running on port 8000 and front end on port 5173.
- Chrome or Edge (needed for voice input).
- For tests that approve review items or write to the dataset, use a **copy** of the
  database and dataset (a second backend with `DATABASE_URL` and `DATASET_PATH` pointing to
  the copies), so real data is not changed.

---

## 5. Entry and Exit Criteria

**Entry**
- The code builds: `npx tsc -b` passes and the backend imports without errors.
- The dataset passes `scripts/validate_dataset.py`.

**Exit (required before a release or demonstration)**
- 100% of automated backend and front-end tests pass.
- ESLint reports no warnings (`npx eslint . --max-warnings 0`).
- All manual scenarios in section 7 pass.
- No open critical or high-severity defects.
- The real dataset file is unchanged after testing, unless an approval was intended.

---

## 6. Requirement Coverage

Current automated suite: **94 backend test cases** (81 test functions, some parametrised)
and **30 front-end tests**. All of them pass.

### 6.1 Backend test files

| File | Tests | Covers |
|---|---|---|
| `test_dataset_validation.py` | 4 | Dataset rules: valid rows, every issue type detected, missing columns and values |
| `test_understanding.py` | 8 | Intent, unknown not forced, category and product, guided input, entities, masking sensitive numbers, sentiment, severity |
| `test_embeddings_retrieval.py` | 11 | Embeddings, hashing fallback, BM25, hybrid weights, metadata filter, exclusions, reranker and its fallback, held-out tickets never indexed |
| `test_evidence_rag.py` | 11 | Thresholds, evidence formula, intent mismatch, grounding rules, removal of unsupported steps, LLM fallback, retry exclusions, general checklists |
| `test_workflows.py` | 19 | Known and unknown flows, feedback rules, review and approval, dataset learning, rejection, articles and versions, memory, emerging issues, analytics |
| `test_handoff.py` | 10 | Customer chat, full handoff, invalid transitions, escalation after 3 attempts, agent fixes to review, critical routing, approval notices, queue and cancel, off-topic questions |
| `test_health_and_api.py` | 10 | Health, request IDs and security headers, structured errors, input validation, size limits, HTML handling, settings |
| `test_e2e.py` | 4 | Known and unknown end to end, streaming stages, guided and free text sharing the pipeline |
| `test_evaluation.py` | 4 | Classification and ranking metrics, evaluation on held-out split, invalid split |

### 6.2 Front-end test files

| File | Tests | Covers |
|---|---|---|
| `portals.test.tsx` | 8 | Help-center search, topics, no internal IDs, article pages hide agent notes, 404 page, chat and talk to a person, agent replies, plain language, admin inbox |
| `components.test.tsx` | 7 | Cited steps and source details, unknown-issue view, information-gathering steps, feedback buttons, voice input supported and unsupported, friendly errors |
| `assistantResolution.test.tsx` | 4 | Customers never see scores, feedback question, related articles in positive wording, admin evidence details |
| `supportFlow.test.tsx` | 4 | Test-the-assistant flow, guided and free text, unknown issue and retry, backend failure |
| `candidatesStepper.test.tsx` | 1 | Review-queue workflow steps are clickable and filter correctly |
| `api.test.ts` | 3 | Structured errors, unreachable backend, network failures |
| `utils.test.ts` | 3 | Citation parsing without HTML, percentage formatting, list parsing |

### 6.3 Traceability (requirement → test)

| Requirement | Covered by |
|---|---|
| FR-01–FR-03 Input modes, one pipeline | `test_e2e::test_guided_and_free_text_share_the_pipeline`, `supportFlow` (guided and free text), `components` (voice) |
| FR-04 Input validation | `test_health_and_api` (empty, overlong, extra fields, size limit) |
| FR-05–FR-06 Telecom-only scope, greetings | `test_handoff::test_non_telecom_questions_are_politely_declined` |
| FR-07–FR-09 Understanding | `test_understanding` (all) |
| FR-10 Critical routing | `test_handoff::test_critical_issue_is_routed_to_an_agent_immediately` |
| FR-11 Memory | `test_workflows` (follow-up, not hijacked, bounded) |
| FR-12–FR-15 Retrieval | `test_embeddings_retrieval` (all) |
| FR-16–FR-18 Evidence score | `test_evidence_rag` (thresholds, formula, mismatch, general checklists) |
| FR-19–FR-24 Grounded generation | `test_evidence_rag` (grounding, guard, LLM fallback), `test_workflows::test_known_complaint_retrieval_rag_citations` |
| FR-25–FR-30 Feedback, retry, escalation | `test_workflows::test_unknown_candidate_feedback_retry_escalation`, `test_duplicate_feedback_rejected`, `test_handoff::test_max_attempts_escalates_chat_to_admin_inbox` |
| FR-31–FR-36 Handoff | `test_handoff` (full workflow, invalid transitions, queue and cancel), `portals` (chat, agent replies, inbox) |
| FR-37–FR-45 Knowledge evolution and dataset learning | `test_workflows` (approval, rejection, new query to dataset, dataset query closes), `test_handoff` (agent fix, no reply, approval notice) |
| FR-46 Articles and versions | `test_workflows::test_draft_article_approval_and_versioning`, `test_create_knowledge_article_validation` |
| FR-47–FR-49 Emerging issues | `test_workflows::test_emerging_issue_detection_and_new_intent`, `test_create_intent_validation` |
| FR-50–FR-53 Customer website | `portals`, `assistantResolution` |
| FR-54–FR-57 Admin console | `supportFlow`, `candidatesStepper`, `portals` (inbox) |
| FR-58–FR-60 Dataset validation and splits | `test_dataset_validation`, `test_embeddings_retrieval::test_held_out_and_calibration_tickets_never_indexed` |
| FR-61 Analytics and evaluation | `test_workflows::test_analytics_and_logs`, `test_evaluation` |
| NFR-05–NFR-07 Fallbacks | `test_embeddings_retrieval` (keyword-only, reranker fallback), `test_evidence_rag` (LLM fallback) |
| NFR-12–NFR-15 Security | `test_health_and_api` (headers, errors, limits, HTML), `api.test.ts`, `components` (no stack trace) |
| NFR-26 Tests do not touch real data | `conftest.py` temporary database and dataset copy |

**Coverage gaps to close**
- NFR-01 response time has no automated check yet.
- NFR-08 (concurrent approvals writing to the dataset) is protected by a lock but has no
  dedicated concurrency test.
- NFR-19 and NFR-20 (responsive layout, keyboard use) are checked manually only.

---

## 7. Manual End-to-End Scenarios

These must be run in a browser against the running application before each demonstration.

| ID | Scenario | Steps | Expected result |
|---|---|---|---|
| TC-01 | Known issue | Customer chat: "My SIM isn't detected" | SIM Not Detected steps with a link to the article; "Did this solve it?" shown |
| TC-02 | Reworded complaint | "My net keeps cutting out every evening" | Same broadband evidence as "broadband disconnects every evening" |
| TC-03 | Unknown issue | "My smartwatch stopped getting notifications from my phone" | Closest guidance in positive wording; not forced into an unrelated issue type |
| TC-04 | Partly solved | Answer → "Partly" → add details | Details box appears; the next attempt uses the details |
| TC-05 | Retry and escalation | Answer "I still need help" three times | Attempts 2 and 3 use different sources; after the third the chat shows as Waiting in the admin inbox |
| TC-06 | Talk to a person | Customer clicks "Talk to a person" | Queue position shown; Cancel works |
| TC-07 | Live agent chat | Admin: Assign to me, reply. Customer replies back | Customer sees "<agent> is helping you now" and the reply; admin sees the customer's message |
| TC-08 | New query to review | New wording solved, customer clicks "Yes, all sorted" | Item in Review queue as "New question, answered by an article" or "Customer confirmed a fix" |
| TC-09 | Approval and dataset learning *(use data copies)* | Approve the item with an issue type | Toast shows the dataset record `TELCO-LIVE-…`; the CSV copy has one extra valid row |
| TC-10 | System has learned *(use data copies)* | Ask the approved question again | Higher evidence; answer cites the new row or article; "Yes" closes without review |
| TC-11 | Agent fix to review | Agent replies and clicks "Mark solved & close" | Item in Review queue as "Solved by an agent" with the agent's reply as the fix |
| TC-12 | Rejection | Reject a review item | Nothing added to articles or dataset; customer gets a neutral notice |
| TC-13 | Off-topic question | "My dog isn't taking food" | Polite telecom-only reply; no case, no feedback buttons |
| TC-14 | Greeting | "Hi" and "Thank you" | Friendly reply; no case |
| TC-15 | Memory | "My broadband is slow" then "Mostly at night" | Second message stays on Broadband Slow |
| TC-16 | Voice | Microphone in Chrome: speak a complaint | Transcript appears and follows the same pipeline |
| TC-17 | Emerging issue | Submit 3 similar unknown complaints, then "Check for new trends" | A trending problem appears and can become a new issue type |
| TC-18 | Customer privacy | Inspect customer answers and article pages | No scores, KB IDs, agent notes or technical labels |
| TC-19 | Admin search | Press `/` and search a customer name and case ID | Results link to the right chat, case and article |
| TC-20 | Backend down | Stop the backend and use the chat | A friendly error is shown, never a stack trace |
| TC-21 | Real data unchanged | After testing, check the dataset line count and checksum | 60,000 rows and the same checksum, unless an approval was intended |

---

## 8. Non-Functional Testing

| Area | Requirement | Method |
|---|---|---|
| Performance | Resolution returned in about 2 s on a laptop in demo mode | Check `total_latency_ms` in the backend logs during TC-01 to TC-03 |
| Reliability | Starts and answers without sentence-transformers, the reranker or PostgreSQL | Run with `EMBEDDING_BACKEND=hashing` and an unreachable `DATABASE_URL` |
| Security | No secrets in the browser or logs; structured errors only | Inspect network responses and logs; automated header and error tests |
| Usability | Customer site usable at laptop and narrow widths; keyboard reachable | Manual check at 1366 px and 375 px wide; Tab through the chat |
| Accessibility | Interactive elements have labels | Tests use roles and labels, so a missing label fails them |

---

## 9. Data and Evaluation Testing

- `python scripts/validate_dataset.py` must report 0 rejected rows for the main dataset.
- Held-out and calibration tickets must never appear in the search index (automated test).
- `python scripts/evaluate.py --split held_out_test` must run and store results. Results are
  reviewed on the Reports page and compared with the previous run to catch regressions.
- Rows added through approval must pass the same validation as the original dataset
  (automated in `test_known_solved_new_query_goes_to_review_then_into_dataset`).

---

## 10. Regression Testing

The full automated suite must be run after every change:

```bash
cd backend  && python -m pytest
cd frontend && npx tsc -b --noEmit && npx eslint . --max-warnings 0 && npx vitest run
```

Any change to customer-facing wording must update the related front-end tests. Any bug fix
must come with a test that would have caught it.

---

## 11. Defect Management

| Severity | Definition | Example | Release rule |
|---|---|---|---|
| Critical | Wrong or unsafe behaviour, data loss or corruption | Unapproved knowledge written to the dataset | Must be fixed |
| High | A core workflow is broken | Handoff reply not reaching the customer | Must be fixed |
| Medium | Feature works but is wrong in some cases | Loosely related article suggested | Fix or document |
| Low | Cosmetic or wording issue | Label spacing | Can be deferred |

Each defect is recorded with steps to reproduce, the expected and actual result, the request
ID from the error (if any), and the test added to cover it.

---

## 12. How to Run

```bash
# Backend tests
cd backend
python -m pytest

# Front-end tests and checks
cd frontend
npx tsc -b --noEmit
npx eslint . --max-warnings 0
npx vitest run

# Dataset, smoke test and evaluation (backend must be running for verify_api)
python scripts/validate_dataset.py
python scripts/verify_api.py
python scripts/evaluate.py --split held_out_test
```
