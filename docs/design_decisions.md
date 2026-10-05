# Design Decisions – Support IQ

This document records the main design decisions we made while building Support IQ, the
adaptive RAG-based telecom support assistant. For each decision we note the problem we were
solving, the options we considered, what we chose, and the trade-offs we accepted.

---

## 1. Treat support as an evidence problem, not a chatbot problem

**Context.** A language model on its own will answer any telecom question confidently,
including with steps that are wrong or do not exist for our network.

**Options considered**
- Let the LLM answer directly from its own knowledge.
- Fine-tune a model on the ticket dataset.
- Retrieve evidence first and only allow answers built from that evidence (RAG).

**Decision.** Retrieval-augmented generation, with strict grounding.

**Why.** Every step can be traced to a ticket or help article, which agents can check and
customers can trust. New knowledge can be added by updating the data instead of retraining.

**Trade-off.** The assistant can only be as good as its knowledge base, so we had to invest
in unknown-issue handling and a learning loop (see decisions 8 and 11).

---

## 2. Hybrid retrieval instead of semantic search alone

**Context.** Customers describe the same problem in very different words ("my net keeps
cutting out" vs "broadband disconnects every evening"), but some terms must match exactly
(eSIM, roaming, 5G, PUK).

**Options considered**
- Keyword search (BM25) only – fails on paraphrases.
- Embedding search only – sometimes misses exact technical terms.
- A weighted combination of both plus metadata.

**Decision.** Hybrid score = 0.60 × semantic + 0.25 × BM25 keyword + 0.15 × metadata
(category and product match), followed by an optional cross-encoder reranker.

**Why.** Semantic search handles wording differences, keywords protect precise terms, and
metadata keeps results in the right product area. The weights favour meaning because
paraphrase was the main weakness of the old keyword-based process.

**Trade-off.** More moving parts to tune. The weights live in `backend/app/config.py` so they
can be adjusted without code changes.

---

## 3. A small local embedding model, with a fallback

**Options considered**
- Hosted embedding APIs.
- A large local model.
- `all-MiniLM-L6-v2` (384 dimensions) running locally.

**Decision.** `all-MiniLM-L6-v2` via sentence-transformers, with an automatic
hashing-based fallback when the model is not installed.

**Why.** It is fast on a laptop, needs no API key, and is good enough for short support
complaints. The fallback means the project always starts, even on a machine without the
model.

**Trade-off.** The fallback is noticeably less accurate. The health endpoint and the logs
say clearly which backend is active.

---

## 4. One evidence score with two thresholds

**Context.** We needed a single, explainable way to decide whether the system "knows" an
issue.

**Decision.**

```
evidence = 0.40 × semantic + 0.20 × reranker + 0.20 × intent match
         + 0.10 × source quality + 0.10 × metadata
```

| Score | Status | Behaviour |
|---|---|---|
| ≥ 0.70 | Known | Verified resolution |
| 0.45 – 0.70 | Uncertain | Candidate resolution, customer asked to confirm |
| < 0.45 | Unknown | Closest guidance and related articles |

**Why.** One number is easy to show to agents, easy to test and easy to calibrate. The
calibration split (decision 10) was used to choose the thresholds.

**Detail.** General checklists are excluded from the score. Otherwise a generic article
would make an unfamiliar problem look "known".

---

## 5. Grounding guard on every answer

**Decision.** Each generated step must cite a retrieved source. A guard removes any step
that is not supported by the evidence, whether it came from Gemini or from the templates.

**Why.** Prompt instructions alone do not guarantee grounding. A deterministic check after
generation does.

**Trade-off.** Answers are sometimes shorter than a free-form model would write. We
accepted this in exchange for trust.

---

## 6. Demo mode that works without an API key

**Options considered**
- Require a Gemini key to run.
- Provide grounded templates as the default and Gemini as an option.

**Decision.** `DEMO_MODE=true` by default, using deterministic grounded templates. Gemini
(`gemini-2.5-flash`) is used when `DEMO_MODE=false` and a key is set.

**Why.** Anyone can clone and run the full workflow, results are repeatable for evaluation
and tests, and no secrets are needed to demonstrate the project.

---

## 7. Don't force unknown issues into existing intents

**Context.** A classifier always picks *some* intent, which hides genuinely new problems.

**Decision.** Intents are only assigned when keyword rules or example similarity are
confident enough; otherwise the complaint is marked `unknown`. Unknown issues get the
closest general guidance plus related articles, framed positively for the customer.

**Why.** Mislabelling a new issue gives the customer a wrong fix and hides a trend the
support team should know about.

---

## 8. Adaptive retry with a hard limit of three attempts

**Decision.**
- "Partly solved" → ask for more details, then retry using them.
- "Not solved" → retry, excluding sources already used and steps already suggested.
- After 3 attempts → escalate to a human agent automatically.

**Why.** Retrying with the same evidence is pointless, and endless retries frustrate
customers. Three attempts gives the system a fair chance before a person takes over.

---

## 9. Human verification before anything becomes trusted

**Context.** A customer saying "yes, that worked" is a useful signal but not proof. It could
be a coincidence or the wrong problem.

**Decision.** Solved new queries never go straight into trusted knowledge. They go to a
**review queue** with three item types:

| Item type | Created when | Approval does |
|---|---|---|
| Customer confirmed a fix | Customer says yes to an unverified answer | Publishes an article + adds a dataset row |
| New question, answered by an article | A verified answer solved a question worded in a new way | Adds a dataset row only (no duplicate article) |
| Solved by an agent | An agent fixed the problem in chat and closed it | Publishes the agent's fix + adds a dataset row |

**Why.** A human check keeps bad fixes out of the knowledge base while still letting the
system learn from real conversations.

**Trade-off.** Learning is not instant; it depends on reviewers. The dashboard highlights
"Fixes to review" so the queue is not forgotten.

---

## 10. Intent-disjoint dataset splits

**Options considered**
- Random split by rows.
- Split by intent, so each intent belongs to exactly one split.

**Decision.** Development (searchable), calibration (threshold tuning) and held-out test
(final evaluation, never indexed) are split by intent.

**Why.** With a random split, test questions have near-identical twins in the index, so the
evaluation measures memorisation. Splitting by intent tests real unknown-issue handling.

---

## 11. Approved knowledge is written back to the dataset file

**Context.** We wanted the 60K dataset to stay the single source of truth, not a
separate store of "learned" data.

**Decision.** On approval, a new row (record ID `TELCO-LIVE-…`) is appended to
`telecom_support_adaptive_60000.csv` with the same 32 columns. The row is placed in the
split its intent already belongs to, inserted into the tickets table and indexed
immediately.

**Why.** Rebuilding the database from the CSV keeps everything that was learned, and the
dataset keeps the same format and validation rules.

**Details**
- Ingestion skips record IDs it has already loaded, so appending is safe.
- A query is "new" unless its exact wording is already in the dataset. Reworded versions
  go to review again so each phrasing gets a human check.
- A reviewer must choose a valid issue type, because the dataset validator rejects unknown
  intents.
- Tests run against a temporary copy of the dataset so they never modify the real file.

---

## 12. Answer only telecom questions

**Context.** Without a guard, "My dog isn't taking food" was matched to a recharge
article and answered with nonsense steps.

**Options considered**
- Rely on the evidence score – fails, because hashing embeddings give weak but non-zero
  matches.
- An LLM classifier – needs an API key and adds latency.
- A vocabulary-based scope check.

**Decision.** A message is in scope if it contains telecom vocabulary, matches a product or
issue-type keyword, is a follow-up in a telecom conversation, or comes with a chosen
category. Short words like "sim", "plan" and "app" match whole words only, so "simple",
"plant" and "appetite" do not count. Off-topic messages get a polite reply and create
**no case**, so nothing reaches the review queue. Greetings and thanks get a friendly reply.

**Trade-off.** It leans towards answering: mixed questions such as "my bank app is not
opening" pass. We preferred that to blocking real telecom customers.

---

## 13. Two separate experiences: customer website and admin console

**Decision.** One React project with two route trees: the customer help center at `/` and
the admin console at `/admin`.

**Why.** Customers and agents need very different things. Customers see plain steps,
article links and positive wording, with no scores or IDs. Agents see the full working:
evidence, sources, confidence, attempts and review tools. Sharing one codebase keeps the
components (for example `AssistantResolution`) consistent, with an `audience` setting
deciding what is shown.

---

## 14. Live chat handoff through the database, with polling

**Options considered**
- WebSockets.
- Server-sent events.
- Short polling every 3 seconds.

**Decision.** Chats have explicit states (`bot → needs_agent → agent → bot | closed`) stored
in the database, and both sides poll every 3 seconds.

**Why.** It is simple, reliable, works with SQLite and needs no extra infrastructure. For
support chat, a delay of up to three seconds feels natural.

**Trade-off.** It is not instant and creates some extra requests. WebSockets are listed as
future work.

---

## 15. Conversation memory only for genuine follow-ups

**Context.** An early version carried the previous topic into every new message, so a new
problem could be "hijacked" by the old one.

**Decision.** Memory is applied only when the new message looks like a follow-up (short, no
clear intent of its own). A clear topic change starts fresh.

**Why.** "Mostly at night" after "My broadband is slow" should stay on broadband, but "I was
charged twice" should not.

---

## 16. Positive, plain language for customers

**Decision.** Customer-facing text avoids negative phrasing ("couldn't find", "not
verified", "insufficient evidence") and technical terms. Unknown issues are introduced as
"Here are the steps that help most with issues like this". Internal feedback notes are
hidden from the customer chat.

**Why.** Customers want help, not an explanation of the retrieval system. The admin view
keeps the precise technical labels for agents.

---

## 17. PostgreSQL + pgvector in production, SQLite locally

**Decision.** PostgreSQL 16 with pgvector via Docker for a real deployment; SQLite for local
development. If PostgreSQL is unreachable, the backend retries and then falls back to
SQLite. Embeddings use a custom column type that maps to `VECTOR(384)` or binary.

**Why.** Easy local setup without losing a scalable path.

---

## 18. Strict validation and friendly errors

**Decision.**
- Every dataset row is validated before loading, and rejected rows are reported with
  reasons, never silently dropped.
- API schemas are strict: unknown fields are rejected, and request size and complaint
  length are limited.
- Errors return a code, a readable message and a request ID, never a stack trace.
- Every external dependency (database, embeddings, reranker, LLM) has a fallback.

**Why.** The system should fail safely and explain itself to both users and developers.

---

## 19. Security boundaries

**Decision.**
- API keys stay in the backend `.env` and are never sent to the browser.
- `.env` is excluded from version control; `.env.example` contains no secrets.
- Customers never see internal scores, IDs or agent-only notes.

**Known gap.** The admin console has no login yet. Authentication and roles must be added
before real-world use.

---

## Summary

| # | Decision | Main reason |
|---|---|---|
| 1 | RAG with strict grounding | Trustworthy, traceable answers |
| 2 | Hybrid retrieval (0.60 / 0.25 / 0.15) + reranking | Handles paraphrases and exact terms |
| 3 | MiniLM embeddings with fallback | Fast, local, always runs |
| 4 | Evidence score, thresholds 0.70 / 0.45 | One explainable confidence measure |
| 5 | Grounding guard | Guaranteed citations |
| 6 | Demo mode by default | Runs anywhere, repeatable |
| 7 | Explicit unknown issues | No forced wrong intents |
| 8 | Max 3 adaptive attempts, then escalate | Fair retry, then a human |
| 9 | Human review queue | Safe learning |
| 10 | Intent-disjoint splits | Honest evaluation |
| 11 | Write approved cases back to the dataset | Dataset stays the source of truth |
| 12 | Telecom-only scope check | No answers to unrelated questions |
| 13 | Separate customer and admin experiences | Right detail for each audience |
| 14 | DB-backed handoff with polling | Simple and reliable live chat |
| 15 | Memory for follow-ups only | Context without hijacking |
| 16 | Positive plain language for customers | Better customer experience |
| 17 | PostgreSQL + pgvector or SQLite | Scalable yet easy to run |
| 18 | Validation, fallbacks and friendly errors | Fails safely |
| 19 | Secrets on the backend only | Basic security |
