APPROACH

Our approach to building Support IQ was to treat telecom support as an evidence problem
rather than a chatbot problem. Instead of letting a language model answer freely, every
answer is built from retrieved evidence, scored for reliability, checked against its
sources, and improved through customer feedback and human review. We built the system in
the following stages.

1. Understanding the requirements
   We started by breaking the problem statement into concrete requirements: complaint
   understanding, hybrid retrieval, grounded generation with citations, unknown-issue
   detection, feedback and retry, escalation, human verification, knowledge evolution,
   emerging-issue discovery, conversation memory and voice input. We also looked at how
   keyword-based ticket search fails in practice, mainly with different wording, new
   issues and no feedback loop. These gaps shaped the design.

2. Preparing the data
   We used a 60,000-row synthetic telecom ticket dataset with 32 columns, together with a
   knowledge base of help articles, an intent taxonomy, support categories and products.
   Every row is validated before loading: missing values, duplicates, invalid categories,
   timestamps and score ranges. The data is split by intent into development, calibration
   and held-out test sets. Splitting by intent instead of random rows means the test set
   contains issues the system has truly never seen, which is the only fair way to evaluate
   unknown-issue handling.

3. Understanding the complaint
   Each message first goes through a scope check, so only telecom questions are answered.
   The complaint is then analysed for intent, category, product, severity, sentiment and
   entities, using taxonomy keywords and embedding similarity, with the LLM as an option.
   Conversation memory carries context across genuine follow-up messages, and critical
   issues are routed to a human straight away.

4. Retrieving the evidence
   We combined three kinds of search: semantic embeddings for meaning (weight 0.60), BM25
   for exact keywords (0.25) and metadata matching for category and product (0.15). The
   best results are reranked with a cross-encoder. This hybrid approach handles both
   "same problem, different words" and precise technical terms such as eSIM or roaming.

5. Measuring confidence
   Instead of trusting the top result blindly, we calculate an evidence score from
   semantic similarity, reranker score, intent match, source quality and metadata match.
   Two thresholds divide every complaint into Known (0.70 and above), Uncertain or
   Unknown (below 0.45). This decides how the answer is framed and what happens next.

6. Generating grounded answers
   The resolution is generated only from the retrieved tickets and articles, and every
   step carries a citation to its source. A grounding check removes any step that the
   evidence does not support. Gemini can be used when an API key is available; otherwise
   a demo mode with grounded templates produces the same kind of answer, so the project
   runs anywhere without keys. For unknown issues the system gives the closest relevant
   guidance and related articles rather than forcing the complaint into a wrong category.

7. Adapting through feedback
   After each answer the customer is asked whether it solved the problem. "Partly" leads
   to a retry with the extra details the customer gives. "No" leads to a retry with
   alternative evidence, excluding sources and steps already tried. After three attempts
   the case is escalated to a human agent through a live handoff to the admin inbox.

8. Learning with human verification
   We never let a solution become trusted knowledge automatically. Every new query that
   gets solved goes to a review queue: fixes confirmed by customers, new wordings answered
   by existing articles, and fixes written by agents in live chat. A reviewer checks and
   edits the item, assigns an issue type and approves it. The approved solution becomes a
   help article where needed, is added as a new row in the dataset file, and is indexed
   immediately, so the next customer with the same problem gets a verified answer.
   Repeated unknown complaints are also clustered into trending problems that the team
   can promote to new issue types.

9. Building the two connected sides
   The customer side is a help-center website with a chat assistant, voice input,
   feedback buttons and a "Talk to a person" option. The admin side is a console with a
   live inbox, cases, a test tool for the assistant, help articles, the review queue,
   trending problems, issue types and reports. Both sides communicate through the backend
   and database, with live updates every few seconds.

10. Testing and refinement
    We wrote automated tests for every stage (94 backend and 30 frontend tests) and tested
    real scenarios by hand: known issues, reworded complaints, brand-new issues, failed
    answers with retries and escalation, the full learning loop, emerging issues,
    multi-turn memory, voice input, live handoff and unrelated questions. Based on these
    tests we refined the wording for customers, the relevance of suggestions and the
    connection between the two sides.

In short, the approach is: understand, retrieve, score, answer from evidence, listen to
feedback, involve humans when needed, and learn only from what has been verified.