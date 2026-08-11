# VITC ChatBot — Interview Prep Guide
### Gen-AI RAG System | FastAPI, Weaviate, Google Gemini, Docker

This guide assumes the **upgraded version** of the project: recursive chunking, hybrid (BM25+vector) retrieval with cross-encoder re-ranking, query rewriting, structured citations with confidence scoring, SSE streaming, a RAGAS evaluation harness, a service-layer backend with DI, caching, rate limiting, API-key auth, Docker + CI, and observability. Anchor your answers in what you actually implemented and tested — if you didn't finish a given item, say so plainly rather than improvising; interviewers probe exactly at the seams between "built" and "described."

---

## 1. Project Understanding & Ownership

1. Walk me through what this project does, in plain English, for someone who's never seen it.
2. Why did you build this specific project — what problem at VIT Chennai were you trying to solve?
3. Who is the actual end user? What do they do today without this tool, and how does your tool change that?
4. What was the trigger — was there a real, painful gap (students can't find hostel rules, academic regulations buried in PDFs), or was this primarily a learning project you retrofitted a use case onto? Be honest either way.
5. Did you build this alone or with a team? If a team, what exactly was your slice — backend, RAG pipeline, frontend, infra, all of it?
6. Walk me through the full workflow: a student opens the app, types a question — trace every step until they see an answer, including what happens behind the scenes.
7. If I asked your teammate (or a rubber duck) to describe your contribution in one sentence, what would they say?
8. What data/documents does this system actually work over? How did you obtain and prepare them?
9. Is this deployed anywhere real students use, or is it a portfolio/local project? If deployed, how many real queries has it handled?
10. What would you change about the *problem framing* itself if you started over?

**Expected interviewer intent:** These aren't throwaway warm-up questions — they're calibration. An interviewer forms a first impression here of whether you're describing your own work or reciting a review someone else did for you. Vague, hand-wavy answers to "walk me through the workflow" are the #1 tell of a resume-inflated project.

**Strong answer should:** be specific about the *actual* documents (name them — academic regulations, hostel code of conduct, etc.), be honest about scale (this is a small campus project, not a startup — don't oversell), and describe the workflow in terms of actual function/file names, not generic RAG buzzwords.

**Weak answer to avoid:** "It uses RAG to retrieve relevant chunks and generate an answer" — this is a definition, not a description of *your* system.

---

## 2. Technical Architecture

1. Draw (verbally or on a whiteboard) the complete system architecture — every component, every arrow.
2. Trace one query end to end: user types a question in the React UI → ... → answer streams back. Name every function/file it touches.
3. Why is this split into a separate FastAPI backend and React frontend instead of, say, a Streamlit app or a Next.js full-stack app?
4. Where does ingestion happen — at server boot, on a schedule, on demand? What triggers a document being (re-)indexed?
5. Explain your Weaviate schema. What properties does each object have, and why those specifically (`text_chunk`, `source_file`, `page_number`, `section_name`, `doc_type`)?
6. Why Weaviate over Pinecone, Qdrant, Chroma, pgvector, or FAISS? What did you actually evaluate versus what did you just pick because it had a free tier?
7. Explain your API design: what does `POST /retrieve/` accept and return? What about `/stream/`? Why two separate endpoints instead of one with a `stream: bool` flag?
8. How does the SSE streaming endpoint actually work mechanically — what is `StreamingResponse` doing under the hood, and how does the browser (`EventSource`/`fetch` + `ReadableStream`) consume it?
9. What's the difference between your streaming and non-streaming code paths? Why keep both?
10. Where does retrieval end and generation begin in your pipeline, and what data crosses that boundary?
11. How is the app containerized? Walk me through your Dockerfile's multi-stage build — why two stages instead of one?
12. If this had a database beyond the vector store (e.g., chat history persistence, user accounts), where would that fit architecturally?
13. What does your `services/rag_service.py` singleton actually hold, and why singleton instead of creating a new Weaviate/Gemini client per request?
14. How does dependency injection (`Depends()`) work in FastAPI, and why did you introduce it here instead of just calling functions directly?

**Expected interviewer intent:** Testing whether you understand your system as a system, not a sequence of tutorial steps stitched together. The Weaviate schema and API design questions specifically test whether design decisions were deliberate or accidental defaults.

**Strong answer should:** justify each boundary (why this is two services, why this schema, why singleton) with a *tradeoff*, not just a description. "I used a singleton because creating a new Weaviate client per request added ~200ms connection overhead I measured" is a strong answer. "Because that's how you're supposed to do it" is not.

---

## 3. Technology Choices

For each technology, be ready for: **why this, what else did you consider, pros/cons, when would you NOT use it.**

### FastAPI
- Why FastAPI over Flask or Django REST Framework?
- What specifically does FastAPI give you that Flask doesn't (async support, automatic OpenAPI docs, Pydantic validation)?
- When would FastAPI be the *wrong* choice?

### Weaviate
- Why a managed/cloud vector DB over a self-hosted FAISS index or pgvector inside an existing Postgres instance?
- What's HNSW, and why is it the default indexing algorithm for approximate nearest neighbor search? What do you trade off versus exact search?
- What are Weaviate's limitations you ran into (free tier limits, cold start latency, schema migration pain)?
- When would you *not* use Weaviate — e.g., if you needed strict transactional consistency, or if your dataset was small enough that a brute-force in-memory search would suffice?

### Google Gemini
- Why Gemini over OpenAI GPT-4/GPT-4o-mini, Claude, or an open-source model like Llama/Mistral served locally?
- What's the cost/latency profile of the model you used (e.g., `gemini-2.5-flash`)? Why not the largest/most capable model?
- What are Gemini's context window and rate limit constraints, and how did they shape your design (e.g., prompt structuring, caching)?
- When would you switch to a self-hosted open-source model instead — cost at scale, data privacy requirements, latency control?

### Hybrid Search (BM25 + Vector) + Cross-Encoder Re-ranking
- Why not pure vector search? What specific failure mode does BM25 fix that vector-only search doesn't?
- What is `alpha` in Weaviate's hybrid query, and what does 0.75 actually mean? How did you pick that number — did you tune it or guess?
- Why re-rank at all if hybrid search already combines two signals? What does a cross-encoder do differently from a bi-encoder (the embedding model)?
- Why `ms-marco-MiniLM-L-6-v2` specifically? What's the latency cost of re-ranking, and was it worth it?

### langchain_text_splitters (RecursiveCharacterTextSplitter)
- Why recursive character splitting over fixed-size chunking or a full semantic/LLM-based chunker?
- Why chunk_size=512 / overlap=64 — how did you land on those numbers?
- What breaks if chunks are too small? Too large?

### SSE (Server-Sent Events) vs WebSockets
- Why SSE over WebSockets for streaming responses?
- What can WebSockets do that SSE can't, and why doesn't your use case need that?
- What are SSE's limitations (one-directional, reconnection behavior, proxy/buffering issues)?

### RAGAS
- Why RAGAS specifically over building your own eval scripts or using a different framework (e.g., DeepEval, TruLens)?
- What do faithfulness, answer_relevancy, and context_recall each actually measure, mathematically or conceptually?
- What are RAGAS's own limitations — it uses an LLM to judge outputs, so what bias or noise does that introduce?

### Docker / GitHub Actions
- Why containerize at all for a project this size?
- What does your CI pipeline actually catch that manual testing wouldn't?
- Why didn't you include the RAGAS eval in CI, and is that the right call?

### React / Tailwind
- Why React over a simpler vanilla JS frontend or a framework like Vue/Svelte?
- Why Tailwind over CSS modules or styled-components?
- Why `EventSource` vs `fetch` + `ReadableStream` for consuming the SSE stream — which did you end up using, and why (hint: custom auth headers aren't supported by native `EventSource`)?

**Common trap across all of these:** "It's popular / it's what the tutorial used" is a real answer some people give under pressure — never say this. Even if a choice genuinely was "I saw it in a tutorial," reframe honestly: "I started with what I'd seen used elsewhere, then validated it made sense for constraints X and Y."

---

## 4. Implementation Deep Dive

1. Walk me through `weaviate_handler.py`'s `retrieve_chunks()` function line by line.
2. Walk me through `gemini_handler.py`'s prompt construction. What's actually in the final prompt sent to Gemini — show me an example.
3. How does `RAG_CORE.py`'s `query()` function orchestrate retrieval, rewriting, and generation? What's the call order and why?
4. Explain your incremental ingestion logic (`delete_chunks_from_source()`). How do you detect that a source file changed versus is new?
5. What does your Pydantic `RetrieveRequest`/response schema look like, and why those specific fields and constraints (`min_length=3, max_length=500`)?
6. How do you handle a query that returns zero relevant chunks (below your similarity threshold)? Walk me through that code path exactly.
7. How is `confidence` computed? Is it a real calibrated probability or a heuristic — be precise about which, and why that's an acceptable tradeoff (or isn't).
8. What edge cases did you explicitly handle — empty query, extremely long query, non-English input, a question totally unrelated to any ingested document, a client disconnecting mid-stream?
9. What edge cases do you know are *not* handled, and what would break if they occurred?
10. Explain your rate limiting implementation (`slowapi`) — what's the actual limiting key (IP? API key?), and what happens to a request that exceeds it?
11. Explain your prompt-injection mitigation. What specific attack does it defend against, and what does it *not* defend against (be honest — a denylist is not a complete defense)?
12. How does your API key auth work end to end, from the frontend storing/sending the key to the backend validating it? What's its actual security level (is this "real" auth or a basic deterrent)?
13. Walk me through what happens, step by step, if Weaviate is down when a request comes in. What about if Gemini's API times out?
14. Why did you choose an in-memory LRU cache (or Weaviate-based semantic cache) instead of Redis? What do you lose by not using Redis?

**Expected interviewer intent:** This category is where "did they actually write this code" gets tested hardest. Be ready to describe actual variable names, actual control flow, and actual failure behavior — not idealized behavior.

---

## 5. Problem Solving & Challenges

1. What was the single hardest bug you hit, and how did you find and fix it?
2. Describe the async/blocking bug you found (`async def` route calling synchronous Weaviate/Gemini calls). How did you discover it — did you observe it in production/testing, or find it during code review? What would have happened under real concurrent load if you hadn't fixed it?
3. You had a bug where the frontend's `Source` interface didn't match the actual API response shape, so sources silently rendered as empty. How did you find this — TypeScript should have caught a type mismatch, so what actually happened?
4. What approach did you try for chunking/retrieval that *didn't* work, and why did you abandon it?
5. Did you ever have a moment where adding a "smarter" component (re-ranking, query rewriting) made results *worse*? What did you learn from that?
6. What was the hardest architectural decision — e.g., sync vs. async route, LRU vs. semantic caching, SSE vs. WebSockets — and what tipped the decision?
7. Describe a time retrieval returned technically-relevant-but-practically-useless chunks. How did you diagnose whether it was a chunking problem, an embedding problem, or a query problem?
8. What's something you built that you'd now consider over-engineered, in hindsight?
9. What's something you *didn't* build that you now think you should have (be ready with a real answer — this is basically free credit if you're honest and specific)?
10. If a teammate or reviewer pushed back hard on one of your design decisions, what was it and how did you respond?

**Expected interviewer intent:** Genuine problem-solving stories are the highest-signal part of any interview — this is where "did they think, or did they copy" becomes obvious. Prepare 2–3 *real* stories in STAR format (Situation, Task, Action, Result) rather than trying to answer every bullet fresh in the room.

---

## 6. Performance & Scalability

1. What's the current end-to-end latency for a query, broken into retrieval time vs. generation time? (You should have real numbers from your observability/logging work — cite them.)
2. What's the very first thing that breaks under 10x concurrent load? (Correct answer, if unfixed: blocking event loop; if fixed: probably Gemini's rate limit next.)
3. What breaks at 100x load, and what's your plan to fix it?
4. What's Gemini's rate limit on your tier, and what happens to a request when you exceed it? Do you have retry/backoff logic?
5. How does your semantic/LRU cache change your effective throughput? What's your cache hit rate in practice?
6. If you needed to horizontally scale the FastAPI service, what would you need to change (stateless services, shared cache backend, load balancer)?
7. Is Weaviate itself a scaling bottleneck? What would you do at a much larger document corpus (millions of chunks) — sharding, different indexing parameters?
8. What's your actual per-query cost (Gemini tokens + any infra), and how would you reduce it at scale — model tier selection, prompt compression, caching?
9. Would you consider a job queue (e.g., for ingestion) instead of synchronous processing at server boot? Why or why not, given the current scale?
10. What would a load test of this system actually show — have you run one, and if not, what would you expect to find first?

**Expected interviewer intent:** Interviewers want to see you reason about scale honestly, not claim you've solved a problem you haven't tested. "I haven't load-tested this yet, but based on the architecture, I'd expect X to break first because Y" is a legitimate, strong answer.

---

## 7. Security

1. Walk me through every unauthenticated endpoint in your system before and after your security pass. What could an attacker with just your public URL do?
2. What is prompt injection, specifically in the context of your app? Show me a concrete example query that would attempt to bypass your system prompt, and explain exactly how your denylist defends (or fails to defend) against it.
3. Your prompt-injection mitigation is a denylist of strings — what's a trivial way to bypass it (e.g., paraphrasing, different casing, a different language, encoding tricks)? What would a more robust defense look like?
4. How is your API key stored and transmitted? Is this genuinely secure, or a basic deterrent — be precise about the difference.
5. What data does your system expose in error responses, and what did you specifically lock down there?
6. If someone got your Gemini API key, what's the blast radius — cost, data exposure, both?
7. What's your CORS policy, and what would happen if you'd left it wildcarded?
8. Since you ingest PDFs, is there any risk from a malicious PDF (e.g., ingesting content designed to manipulate future retrieval/generation — a form of "training-time" or "corpus" injection)? Did you consider this?
9. Do you log user queries? If so, what's your data retention/privacy stance, especially since these are real students' questions?
10. If you were told "this needs to survive a penetration test before deployment," what are the top 3 things you'd fix first that you haven't yet?

**Expected interviewer intent:** Most student projects have close to zero real security. Interviewers aren't expecting enterprise-grade security — they're testing whether you can *reason* about attack surface, even for things you haven't fixed. Naming the gap honestly ("this is a deterrent, not real auth, and here's what real auth would need") is much stronger than pretending you've solved it.

---

## 8. Testing & Reliability

1. What's your actual test coverage — walk me through what your smoke test does and doesn't verify.
2. Why did you write an end-to-end integration test against your real running system rather than mocking Weaviate/Gemini? What's the tradeoff (test speed, cost, flakiness) versus a fully mocked unit test?
3. How do you specifically test *retrieval quality*, as opposed to just "does the endpoint return 200"? Walk me through your golden-set/keyword-assertion tests.
4. What does your RAGAS eval actually protect you from? If you change the chunking strategy tomorrow, how would you know if it made things better or worse?
5. What's missing from your test suite that a production system would need (load tests, security tests, frontend E2E tests)?
6. What happens if Weaviate or Gemini is unreachable — does your system fail gracefully or throw a raw 500? Did you write a test for that failure path?
7. How does your CI pipeline catch regressions? What does it *not* catch (e.g., it doesn't run the RAGAS eval, so a chunking regression wouldn't be caught until manual testing)?
8. What monitoring/observability do you have in production right now, if deployed? What would you add first if given another week?
9. If this were on-call for a real team, what alert would you configure first, and on what threshold?
10. What's your actual deployment process — manual, or automated via CI/CD? What would you need to add to make it a real one-click or automatic deploy?

**Expected interviewer intent:** Reliability questions probe production-mindedness, which is rare in student projects and is genuinely differentiating. Own the gaps directly — "I have retrieval-quality regression tests via RAGAS but no load testing or alerting yet, and here's what I'd add first" is a complete, credible answer.

---

## 9. AI/ML-Specific Questions

1. This isn't a traditional ML training project — you're not training a model, you're building a retrieval + generation pipeline. Can you clearly explain that distinction, and why "RAG" doesn't mean "we fine-tuned a model"?
2. What embedding model are you using, and why? What's its dimensionality, and what did you trade off by not using a larger/more expensive embedding model?
3. If you were going to fine-tune anything in this system, what would you fine-tune first — the embedding model, a re-ranker, or the generation model — and why?
4. Walk me through your "evaluation metrics" — faithfulness, answer relevancy, context recall. Give me a concrete example of an answer that would score low on each one individually.
5. What's your baseline you're comparing against? (If none: "pure vector search, no re-ranking, no query rewriting" is a legitimate baseline you should be able to cite actual eval numbers against.)
6. How do you handle "model drift" here — is there any, given you're not training anything? (Good answer: the risk here is closer to *retrieval drift* as documents change, or *API drift* if Google updates the underlying Gemini model version silently.)
7. What are the known limitations/failure modes of your system — questions it systematically gets wrong or can't answer, and why?
8. How would you detect and handle hallucination in production, beyond your current similarity-threshold + citation-requirement approach?
9. If you had 10x more documents to ingest, what would break first in your current pipeline?
10. Is there a feedback loop — do you have any mechanism (even manual) to capture cases where the system gave a bad answer, for future improvement?

**Expected interviewer intent:** A number of interviewers will probe whether you understand that RAG ≠ ML model training, since resumes often blur this. Being crisp about "I didn't train a model, I engineered a retrieval and generation pipeline, and here's the ML-adjacent evaluation rigor I applied" is exactly the right frame — don't overclaim ML depth you don't have, and don't underclaim the very real engineering rigor (hybrid retrieval tuning, RAGAS evaluation) that you do have.

---

## 10. Resume Validation Questions

1. Your resume says "millisecond-latency semantic search" — what's the actual measured latency, and did you measure it, or is that aspirational phrasing?
2. Explain, in detail, exactly how the SSE streaming works — not what it does, but how, at the protocol level.
3. What was *your* individual contribution versus anything scaffolded, templated, or AI-assisted? Be exact.
4. Show me one piece of code you're proud of and one piece you'd rewrite today — explain both.
5. If I asked you to add a completely new document type (say, exam timetables) to this system right now, what would you need to change, and how long would it take you?
6. What's a bug that existed in an earlier version of this project that a user or reviewer would never have known about just from using it? (Good chance to reference the `Source` interface mismatch — a real, specific, silently-broken bug is excellent proof of ownership.)
7. What would you do differently if you rebuilt this from scratch today, knowing everything you know now?
8. What's the most technically sophisticated part of this project, and why — defend that choice against someone who says it's "just a wrapper around an LLM API."
9. If you had one more week, what's the single highest-leverage improvement you'd make, and why that one over the alternatives?
10. Can you extend this system live, right now, on a shared screen, to handle one new small feature? (Be ready for this — some interviewers will actually ask you to code live against your own repo.)

**Expected interviewer intent:** This entire category exists to catch resume inflation. The strongest defense is total precision: exact numbers where you have them, honest "I don't have that number" where you don't, and at least one story about a real bug you personally found and fixed with specifics (function name, symptom, root cause, fix).

---

## 11. Advanced Follow-Ups — Pattern to Prepare For

For nearly every question above, expect a follow-up chain like:

> "Why hybrid search?" → "What's alpha?" → "Why 0.75 and not 0.5?" → "How would you tune that properly instead of guessing?" → "What would you measure to know it's working?"

**What separates a strong candidate across these chains:**
- Each answer names a concrete tradeoff, not just a benefit ("X is faster but loses Y").
- When asked "how would you tune/measure this," you point to a real mechanism you built (RAGAS, latency logging) rather than "I'd just test it."
- You clearly separate "what I actually did" from "what I would do with more time/resources" — never blur those together.

**Common weak-answer patterns to eliminate from your prep:**
- Restating the tool's marketing description instead of your reasoning ("Weaviate is a fast, scalable vector database" — so what, why did *you* pick it).
- Answering "why X" with "because it's popular / best practice" with no tradeoff analysis.
- Claiming a metric or behavior you can't actually produce a number or code path for.
- Over-explaining generic RAG theory when asked about *your* implementation specifically.

---

## Top 20 Most Likely Questions (Ranked)

1. Walk me through what happens from the moment a user types a question to when they see an answer.
2. Why did you choose Weaviate over other vector databases?
3. Explain hybrid search and why you added it — what problem did pure vector search have?
4. What is a cross-encoder re-ranker, and why add one after hybrid search already runs?
5. Walk me through your chunking strategy and why you chose those chunk size/overlap values.
6. Why Gemini over other LLMs (OpenAI, Claude, open-source)?
7. How does your streaming (SSE) implementation actually work?
8. Why SSE instead of WebSockets?
9. What's your evaluation strategy — how do you actually know your RAG system is good, and how would you know if a change made it better or worse?
10. Walk me through the async/blocking bug you found and fixed — what was actually happening and why did it matter?
11. How do you prevent hallucination? What are your actual guardrails, and what are their limits?
12. What's your rate limiting/security setup, and what's the actual attack surface that remains?
13. What was the hardest bug or design decision in this project?
14. What breaks first if this got 10x or 100x the traffic?
15. What was your individual contribution to this project?
16. What's an edge case your system doesn't handle well?
17. Why did you structure the backend the way you did (service layer, dependency injection)?
18. How do you handle incremental updates to your document corpus without re-indexing everything?
19. What would you improve if you had one more week?
20. Can you explain [some specific piece of code] in detail, right now?

---

## "Tell Me About Your Project" — 2-Minute Structure

Use this shape; adjust the bracketed specifics to your real numbers. Aim for ~90 seconds spoken, leaving room for a follow-up.

**1. Problem (15s)**
"VIT Chennai students need to dig through dense, unsearchable PDFs — academic regulations, hostel codes of conduct — to answer simple questions. I built a chatbot that answers those questions directly, with citations back to the source document and page."

**2. What it is, one sentence (15s)**
"It's a Retrieval-Augmented Generation system: FastAPI backend, Weaviate as the vector store, Google Gemini for generation, with a React frontend that streams answers token by token."

**3. How it works, briefly (30s)**
"Documents get chunked with a recursive splitter and indexed in Weaviate with metadata like page number and section. When a user asks a question, I rewrite it for clarity, run hybrid search — combining keyword and vector similarity — retrieve the top candidates, re-rank them with a cross-encoder, and only pass chunks above a similarity threshold into the prompt, along with explicit citation requirements. The answer streams back over SSE instead of waiting for the full generation."

**4. What made it non-trivial / your specific contribution (30s)**
"The interesting engineering problems were: getting retrieval quality right — pure vector search missed exact-match terms like 'CGPA', which is why I added hybrid search and re-ranking; fixing a blocking event-loop bug that would've serialized every request under load; and building a RAGAS evaluation harness with a 25-question golden set so I could actually measure whether changes helped instead of guessing — faithfulness went from [X] to [Y] after adding re-ranking."

**5. Close — impact + what's next (15s)**
"It's containerized with CI, has structured logging and latency tracking, and I've got a clear list of next steps — proper auth beyond a static API key, load testing, and semantic caching to cut redundant Gemini calls further."

**Delivery notes:**
- Practice this out loud, timed — 2 minutes disappears fast once you start explaining architecture.
- Have the real RAGAS before/after numbers memorized — this is your single strongest, most differentiating detail. If you don't have them yet, run the eval before your next interview.
- If the interviewer's eyes light up on any one part (streaming, RAGAS, hybrid search), that's your signal — stop the scripted flow and go deep on that thread. That's usually a stronger outcome than finishing your pitch.
