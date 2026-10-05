This list follows your actual requests in this project, reworded into the same style as your sample. Prompts 1–20 cover the detailed specification you gave at the start (you sent it as one long prompt, here split by topic). Prompts 21–54 are your later requests, in order.

AI PROMPTS

The following are the major original prompts used during the development of the Support IQ – Adaptive RAG-Based Telecom Support Resolution Assistant.

1. This is the complete problem statement for an Adaptive RAG-Based Telecom Support Resolution Assistant. The attached file shows the structure of my dataset (telecom_support_adaptive_60000.csv). Analyze all the requirements and generate the complete project.
2. Let's support three input modes – guided categories, free-text complaints and voice input – and make all of them use the same resolution pipeline.
3. Let's build the complaint understanding module to identify intent, category, product, severity, sentiment and entities from the customer's complaint.
4. Let's implement semantic embeddings so that complaints worded differently but meaning the same thing retrieve the same historical tickets.
5. Let's implement hybrid retrieval combining semantic search, BM25 keyword search and metadata matching, followed by reranking.
6. Let's calculate an evidence score from semantic similarity, reranker score, intent match, source quality and metadata match.
7. Let's use evidence thresholds to classify every complaint as KNOWN, UNCERTAIN or UNKNOWN.
8. Let's implement the RAG pipeline so that resolutions are generated only from the retrieved tickets and knowledge-base articles, with citations for every step.
9. Let's add a grounding check that removes any troubleshooting step that is not supported by the retrieved evidence.
10. Let's support Gemini as the LLM provider and also provide a demo mode that works without any API key.
11. For unknown issues, let's generate a controlled candidate resolution instead of forcing the complaint into an existing intent.
12. Let's collect customer feedback (solved, partially solved, not solved) after every resolution.
13. If the issue is not solved, let's retry with alternative evidence and additional information, with a maximum of 3 attempts, and then escalate to a human agent.
14. If a candidate resolution solves the issue, let's store it as candidate knowledge and send it for human verification before it becomes trusted knowledge.
15. Let's detect repeated unknown complaints, cluster them into emerging issues and allow an admin to promote them to new intents.
16. Let's implement conversation memory so that follow-up messages keep the context of the earlier conversation.
17. Let's design the database schema for tickets, knowledge articles, document chunks, cases, resolution attempts, feedback, candidate cases, emerging issues and conversations, using PostgreSQL with pgvector and SQLite for local runs.
18. Let's build the dataset ingestion and validation pipeline that checks for missing values, duplicates and invalid records, and splits the data into intent-disjoint development, calibration and held-out test sets.
19. Let's add analytics, an offline evaluation, Docker setup, automated tests, a README and a requirements audit document.
20. Let's make sure API keys and sensitive configuration are kept in environment files and never exposed in the project.
21. The AI is not showing responses based on the knowledge-base articles and previous tickets, and the resolution section is empty. Let's show KB-based resolutions with citations in the chat and ask whether the solution solved the problem; if no source matches, let's generate the best suitable response.
22. In the knowledge evolution workflow I can only open step 3; steps 1 and 2 cannot be clicked. Let's make all the workflow steps clickable and make sure the logical constraints are met.
23. Let's split the application into two sides – a user side and an admin side. The user side should have a WhatsApp-like chatbot showing the resolutions, and the admin side should have all the other features. Let's make sure there is proper connectivity and a proper workflow between the two.
24. Let's make the customer application look like a website that runs on a laptop instead of a phone-style app.
25. The dev server is failing to start. Let's fix the issue and run the preview.
26. Why is "Talk to a human agent" not working? Let's implement the complete human handoff from the customer chat to the admin inbox.
27. Why can't the customer type anything after being connected to a human agent from the admin side? Let's fix the live chat between the customer and the agent.
28. Let's run the complete project.
29. Let's push the project code to GitHub as a public repository including the dataset.
30. Let's remove the session ID and DEMO MODE labels from the user interface.
31. Let's change the application name to "Support IQ".
32. Let's redesign the customer website so it looks like a proper human-made website.
33. What changes can make the website look human-made? Let's apply all of them on the customer side.
34. Where is the admin side? Let's show how to open the admin console.
35. Let's apply the same human-made design to the admin side without changing any logic, and make sure the user and admin sides communicate properly.
36. Let's verify the complete customer-to-admin communication: talk to a person, assign the chat to an agent, reply, and show the reply on the customer side.
37. Why are recently solved chats not going for human verification when a new problem gets solved? Let's make sure every new query that was not in the dataset goes for human approval after it is solved.
38. Once a new solved query is approved by a human, let's add it to our dataset file so that the system learns effectively.
39. Let's also send chats solved by a human agent to the review queue so their fixes can become trusted knowledge.
40. Let's test whether this learning feature works end to end: new query, customer confirmation, review, approval, dataset update and improved answer the next time.
41. Will this feature work correctly in the real application now?
42. For unknown questions, the assistant must still give some closely relevant answers, and no negative words should be shown to the customer.
43. Questions related only to telecom should be answered. For any other irrelevant question (for example, "My dog isn't taking food"), let's show a message that it cannot be answered because it is not a telecom question.
44. Let's run the project again after all the changes.
45. What are the features implemented in this project? Let's list them.
46. Let's list the features directory-wise for the whole project.

NOTE:
The remaining development interactions were primarily image-based. These images contained screenshots of the user interface, error messages, dataset structure, chat responses and UI elements to be changed. They are not listed as separate textual prompts because they were submitted mainly as screenshots/images rather than typed prompts.
