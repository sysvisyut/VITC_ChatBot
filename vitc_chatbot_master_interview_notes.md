# VITC ChatBot — Final Interview Master Notes
### Gen-AI RAG System | FastAPI · Weaviate · Google Gemini · Docker

**How to use this document:** Read it once fully, then re-read only the "Final Cheat Sheet" (Section 15) the morning of an interview. Everywhere you see a bracket like `[X]` or `[measured value]`, that's a real number only you can fill in — run your RAGAS eval and check your logs before your next interview and replace every bracket. An interview answer with a real number in it is worth ten with a placeholder.

---

# 1. Project Overview (Interview Introduction)

### "Tell me about your project."

"I built a Retrieval-Augmented Generation chatbot for VIT Chennai — the problem was that a lot of essential campus information, academic regulations, hostel codes of conduct, attendance policies, is locked away in dense, unsearchable PDFs. Students either don't read them or spend ten minutes hunting for one clause. I wanted something where a student could just ask a plain-English question and get a direct, cited answer.

The existing alternative is literally just Ctrl+F in a PDF, or asking a warden or faculty member and waiting. Neither scales, and neither gives you a precise, sourced answer.

I built the system around a FastAPI backend, Weaviate as the vector store, and Google Gemini for generation, with a React and Tailwind frontend. The core pipeline chunks the source PDFs, indexes them with metadata like page number and document type, and at query time runs hybrid search — combining keyword and vector similarity — followed by cross-encoder re-ranking, before passing only the highest-confidence chunks into Gemini with an explicit instruction to cite sources. Answers stream back token by token over Server-Sent Events instead of the user staring at a spinner for five seconds.

I was responsible for the full stack: the ingestion pipeline, the retrieval and generation logic, the API layer, the frontend integration, and — the part I'm most proud of — building an actual evaluation harness using RAGAS with a 25-question golden set, so I could measure whether a change like adding re-ranking actually improved answer quality instead of just assuming it did. [Faithfulness went from X to Y after adding hybrid search and re-ranking — fill in your real number.]

The real-world impact is scoped — it's a campus tool, not a startup — but it's a genuinely working, end-to-end production-shaped system: containerized, has CI, has structured logging and latency tracking, and I know its actual limitations because I tested for them rather than assumed they didn't exist."

**Delivery notes:** Say this like you're describing a system you debugged at 1am, not reciting a spec. Slow down on the RAGAS number — that's your differentiator. If asked "why does this matter," don't oversell scale; own that it's a focused, well-engineered tool for a real, specific audience.

---

# 2. Complete System Architecture

### High-level architecture

```
┌─────────────────┐        HTTPS / SSE        ┌──────────────────────┐
│  React + Tailwind │ ─────────────────────────▶│     FastAPI Backend  │
│  Frontend         │◀───── streamed tokens ────│                      │
└─────────────────┘                             │  ┌────────────────┐  │
                                                 │  │  rag_service.py │  │
                                                 │  │  (singleton DI) │  │
                                                 │  └───────┬────────┘  │
                                                 │          │           │
                                    ┌────────────┼──────────┴───────┐   │
                                    │            │                  │   │
                              ┌─────▼─────┐ ┌────▼─────┐    ┌───────▼───▼──┐
                              │  Weaviate │ │  Gemini  │    │  LRU / semantic│
                              │  (hybrid  │ │  (query  │    │  cache layer   │
                              │  search + │ │  rewrite,│    └───────────────┘
                              │  re-rank) │ │  gen)    │
                              └───────────┘ └──────────┘
                                    ▲
                                    │ ingestion (chunk + embed)
                              ┌─────┴─────┐
                              │  PDF docs │
                              │  (academic│
                              │  regs,    │
                              │  hostel   │
                              │  code, …) │
                              └───────────┘
```

### Every major component, and why it exists

- **React/Tailwind frontend** — owns chat UI state, renders streamed tokens as they arrive, shows sources/confidence, persists chat history locally. Exists as a separate SPA rather than server-rendered pages because the interaction is highly stateful (streaming, live typing) and a SPA gives the smoothest UX for that.
- **FastAPI backend** — the orchestration layer. Exists to keep the frontend dumb and stateless about business logic (no API keys, no retrieval logic, no prompt construction lives client-side).
- **`rag_service.py` (service layer, dependency-injected)** — wraps the Weaviate client and Gemini client as app-lifetime singletons. Exists because creating a new client per request added measurable connection overhead, and because a service layer decouples the route handlers from the orchestration logic, which made testing and later refactors (adding streaming, adding caching) much safer.
- **Weaviate** — vector store + hybrid search engine. Exists because I needed approximate nearest-neighbor search over embeddings *plus* exact keyword matching (BM25) in one system, without standing up two separate search backends.
- **Cross-encoder re-ranker (`ms-marco-MiniLM-L-6-v2`)** — a second-pass scorer over the top-10 hybrid results, trims to the top 3. Exists because hybrid search alone still let semantically-similar-but-not-actually-relevant chunks through; a cross-encoder scores the (query, chunk) pair jointly, which is more accurate than either signal alone, at the cost of extra latency I decided was worth it.
- **Google Gemini** — generation, and also the lightweight query-rewriting step before retrieval. Exists as the reasoning layer that turns retrieved chunks into a coherent, cited natural-language answer.
- **Cache layer (LRU, optionally semantic)** — sits in front of the full retrieval+generation call. Exists because campus chatbot queries are highly repetitive ("hostel timings", "attendance rule") and caching cuts real Gemini API cost and latency for duplicate/near-duplicate queries.
- **Ingestion pipeline (`pdf_processor.py` → chunker → Weaviate)** — runs incrementally, not as a full wipe-and-reload, so adding one new PDF doesn't require re-embedding the entire corpus.

### Complete data flow

```
User types question (React)
  → POST/stream request to FastAPI, with X-API-Key header
  → FastAPI route (sync, threadpool-executed) hands off to rag_service
  → [cache check] — if hit, skip straight to response
  → query rewriting (short Gemini call, faithful fallback to raw query on failure/timeout)
  → Weaviate hybrid search (alpha=0.75, top 10)
  → cross-encoder re-rank → top 3
  → similarity threshold filter (drop weak matches; return fallback message if nothing clears it)
  → structured, attributed context assembled (source + page number per chunk)
  → prompt built with citation + "answer only from context" instructions
  → Gemini streaming generation
  → tokens streamed back over SSE
  → frontend renders tokens live, then renders sources + confidence badge from the final SSE event
```

### Alternative architectures considered

- **Single full-stack framework (e.g., Next.js API routes) instead of separate FastAPI + React.** Rejected because I wanted Python for the RAG/ML tooling ecosystem (LangChain splitters, sentence-transformers, RAGAS) without a Node↔Python bridge, and the separation makes each half independently deployable/scalable.
- **Self-hosted FAISS instead of Weaviate.** Considered, rejected because I wanted managed hybrid search (BM25 + vector fusion) out of the box rather than hand-rolling a fusion scoring layer myself, given the project's scope and timeline.
- **WebSockets instead of SSE for streaming.** Rejected because the data flow is one-directional (server → client token stream); WebSockets would add bidirectional complexity I don't need, plus SSE gets automatic reconnection semantics for free.

---

# 3. Technology Stack Deep Dive

**Technology:** FastAPI
**Why used:** Native async support, automatic OpenAPI docs, Pydantic-based request/response validation out of the box — all of which matter for an API-first backend serving a SPA.
**Alternative:** Flask (simpler but no native async, no built-in validation), Django REST Framework (heavier, more opinionated than I needed for a single-purpose API).
**Trade-offs:** FastAPI's async model is a footgun if you're not careful — I actually hit this directly (see Section 7) when I declared a route `async def` but called blocking synchronous code inside it, which serialized every request instead of running concurrently. Async gives you power but demands discipline.

**Technology:** Weaviate
**Why used:** Managed hybrid search (BM25 + vector fusion in one query call) plus schema/metadata support without me having to build a fusion layer myself.
**Alternative:** Pinecone (vector-only, no native BM25 fusion at the time I evaluated), pgvector (would've meant standing up and tuning Postgres for vector search, more infra ownership than the project needed), FAISS (self-hosted, no managed hybrid search, no metadata filtering without extra plumbing).
**Trade-offs:** Free-tier resource limits, some cold-start latency, and I don't control the underlying HNSW parameters as finely as a self-hosted setup would allow. I accepted this for faster iteration speed.

**Technology:** Google Gemini (generation + query rewriting)
**Why used:** Strong performance-per-cost at the Flash tier, large context window headroom, and a single provider for both the cheap rewriting call and the main generation call simplified API key/auth management.
**Alternative:** OpenAI GPT-4o-mini (comparable cost/quality tier, would've worked equally well — this was largely a first-hand-familiarity decision, and I'd say that honestly if asked), a self-hosted open-source model like Llama/Mistral (rejected due to hosting cost/complexity for a project this size, though it's the right call if data privacy or long-term cost at scale mattered more).
**Trade-offs:** Vendor lock-in, rate limits on the free/low tier (I had to design around 15 RPM), and no control over model versioning — if Google silently updates the underlying model, my prompt behavior could shift without me changing anything.

**Technology:** `sentence-transformers` cross-encoder (`ms-marco-MiniLM-L-6-v2`)
**Why used:** Re-scoring the (query, chunk) pair jointly is meaningfully more accurate than bi-encoder similarity alone for filtering the final top-3 context.
**Alternative:** Skip re-ranking entirely and just trust hybrid search's top-3 directly (simpler, faster, measurably worse — I could show this with my RAGAS eval before/after).
**Trade-offs:** Added latency per query (extra model inference pass) in exchange for retrieval precision — I judged this worth it because generation quality is entirely bottlenecked on context quality.

**Technology:** `langchain_text_splitters.RecursiveCharacterTextSplitter`
**Why used:** Splits on a priority list of separators (paragraph, sentence, word) rather than a blind fixed-character cut, which better respects natural document structure.
**Alternative:** Naive fixed-size chunking (what the original version of my project actually did — full PDF pages as single chunks — I identified this as the single biggest retrieval-quality bottleneck and replaced it), or a fully semantic/LLM-based chunker (more accurate, meaningfully more expensive and slower for a project this size).
**Trade-offs:** chunk_size=512 / overlap=64 (in tokens) is a balance I chose to keep chunks small enough for retrieval precision but large enough to preserve context — smaller chunks lose surrounding context, larger chunks dilute similarity scores and increase the chance of pulling in irrelevant text alongside relevant text.

**Technology:** Server-Sent Events (SSE) via FastAPI `StreamingResponse`
**Why used:** One-directional server→client token streaming is exactly what SSE is designed for, with automatic reconnection behavior built into the protocol.
**Alternative:** WebSockets (bidirectional, more complex than the use case needs), long-polling (worse UX, wasteful).
**Trade-offs:** Native browser `EventSource` doesn't support custom headers, which mattered because I needed to send an API key — I had to use `fetch` + `ReadableStream` on the frontend instead of plain `EventSource` to work around that.

**Technology:** RAGAS
**Why used:** Purpose-built RAG evaluation metrics (faithfulness, answer relevancy, context recall) instead of me hand-rolling scoring logic.
**Alternative:** No formal eval at all (what the original version of the project had — a real gap I identified and fixed), or a custom keyword-assertion test suite only (I actually kept a lightweight version of this too, as a fast regression check, alongside RAGAS for deeper scoring).
**Trade-offs:** RAGAS itself uses an LLM as a judge internally, which introduces its own noise/bias — I treat its scores as directional signal for before/after comparisons, not as ground truth.

**Technology:** Docker (multi-stage) + GitHub Actions
**Why used:** Reproducible builds across machines, and automated lint/test on every push so I don't rely on remembering to test manually.
**Alternative:** No containerization (what the original version had — meant "works on my machine" risk). 
**Trade-offs:** Multi-stage builds add Dockerfile complexity in exchange for a smaller, more secure final image (no build tooling shipped in the runtime image, runs as non-root).

**Technology:** `slowapi` (rate limiting)
**Why used:** Minimal-dependency IP-based rate limiting for FastAPI without standing up a separate gateway.
**Alternative:** API gateway-level rate limiting (more robust, more infra than this project needs), no rate limiting at all (what I had originally — a real cost/abuse risk against the Gemini API).
**Trade-offs:** IP-based limiting is coarse (shared IPs, e.g. campus NAT, could be unfairly throttled) — a real production system would key on the API key or user account instead.

---

# 4. Core Implementation Explanation

### Feature: Hybrid retrieval + re-ranking (`weaviate_handler.py::retrieve_chunks`)
**Problem it solves:** Pure vector similarity search misses exact-term matches — a query containing "CGPA" might not surface the chunk containing "CGPA" in its top results if the surrounding semantic content differs, because dense embeddings prioritize meaning over literal tokens.
**How it works internally:** I call `collection.query.hybrid(query=query_text, alpha=0.75, limit=10)`, which fuses BM25 keyword scoring and vector similarity scoring at 75% vector weight / 25% keyword weight. The top 10 results then go through the cross-encoder, which independently scores each (query, chunk) pair, and I keep only the top 3 post-re-rank.
**Data flow:** raw query string in → 10 hybrid-scored chunk dicts → 3 re-ranked chunk dicts (with text, source_file, page_number, doc_type, score) out.
**Edge cases handled:** empty result set (falls through to the "no relevant information" response), all 10 candidates scoring below my similarity threshold (same fallback path).
**Engineering decisions:** I chose alpha=0.75 empirically — I tested both keyword-heavy and semantic queries against a few alpha values and this consistently balanced both without sacrificing too much of either. I'd want a systematic tuning pass (grid search against my RAGAS golden set) if I had more time, and I say that honestly rather than pretending 0.75 was rigorously derived.

### Feature: Query rewriting (`RAG_CORE.py::query`)
**Problem it solves:** Short, ambiguous user queries like "hostel rules" retrieve poorly because there's not enough semantic signal in the query itself.
**How it works internally:** Before retrieval, I make a short, cheap Gemini call that expands the raw query into a fuller, unambiguous question. I use the rewritten query for retrieval only — the original query is preserved for display in chat history and isn't fed into the final answer prompt, so the user's own words aren't silently altered.
**Edge cases handled:** rewrite call failure or timeout falls back to using the original query directly, so this step can never hard-fail the whole pipeline.
**Engineering decision:** I deliberately kept this "lite" (a single prompt call) rather than a full multi-query retrieval-and-fusion approach, because the cost/complexity of running N retrieval passes per query wasn't justified by the marginal quality gain I measured for this corpus size.

### Feature: Structured citations + confidence scoring (`gemini_handler.py`)
**Problem it solves:** Raw, unattributed context concatenation gives Gemini nothing to cite from, and gives the user no way to verify an answer.
**How it works internally:** Retrieved chunks are formatted as `[Source: filename, Page N]` blocks before being joined into the prompt, and the system prompt explicitly requires inline citations in that same bracket format. A similarity threshold filters weak matches before they ever reach the prompt. Confidence is a heuristic derived from how many chunks cleared the threshold and how strong the top score was — I'm explicit that this is a heuristic, not a calibrated probability, if asked.
**Edge cases handled:** zero chunks above threshold → explicit "could not find relevant information" response rather than letting Gemini attempt an answer from nothing.

### Feature: SSE streaming (`/stream/` route + frontend `fetch`/`ReadableStream`)
**Problem it solves:** Users staring at a spinner for 3–10 seconds while the full answer generates feels slow even when total latency is unchanged.
**How it works internally:** Retrieval and re-ranking run synchronously first (fast, and needs to complete before generation can start anyway); then Gemini's streaming generation API yields tokens as they're produced, and I wrap each as an SSE `data: ...\n\n` event. A final SSE event carries the structured sources/citations/confidence metadata once generation completes.
**Edge cases handled:** client disconnect mid-stream is handled so a dropped connection doesn't leave a dangling Gemini call running indefinitely. I kept the original non-streaming `/retrieve/` endpoint intact as a fallback rather than replacing it outright.

### Feature: Incremental ingestion (`weaviate_handler.py::delete_chunks_from_source`)
**Problem it solves:** The original version wiped and re-ingested the entire Weaviate collection on every server boot — adding one new PDF meant re-embedding everything.
**How it works internally:** Ingestion now checks per-source-file whether content is new or changed before touching Weaviate; if a file is unchanged, its existing chunks are left alone. If changed, only that file's chunks are deleted and replaced.
**Engineering decision:** I extended the schema with `doc_type`, `page_number`, and `section_name` specifically to support this and to enable metadata filtering later (e.g., restricting retrieval to hostel-specific documents when a query clearly implies that scope).

---

# 5. Database Design

**Database choice reasoning:** Weaviate, used purely as a vector store with metadata properties — there's no separate relational database in this project, since there's no user account system or transactional data; document chunks and their metadata are the only persisted state.

**Schema (Weaviate collection):**
| Property | Type | Purpose |
|---|---|---|
| `text_chunk` | TEXT | the actual chunk content, embedded for vector search |
| `source_file` | TEXT | which PDF this chunk came from, for citation and filtered incremental updates |
| `page_number` | INT | for precise citation and future page-level filtering |
| `section_name` | TEXT (nullable) | best-effort heading extraction, for richer citation context |
| `doc_type` | TEXT | derived from filename (e.g. "hostel", "academic"), enables scoped filtering |

**Relationships:** None in the relational sense — this is a single flat collection, not a normalized multi-table schema, because the data model genuinely is flat (chunks with metadata, no foreign-key relationships to other entities).

**Indexing decisions:** Weaviate's default HNSW (Hierarchical Navigable Small World) index for approximate nearest-neighbor search over the vector, plus its BM25 inverted index over `text_chunk` for the keyword half of hybrid search. I didn't hand-tune HNSW parameters (`ef`, `efConstruction`, `maxConnections`) beyond defaults — that's a legitimate next step for larger-scale tuning I haven't done yet.

**Query optimization:** The `alpha` parameter tuning in hybrid search *is* my primary query-level optimization lever here, rather than traditional index/query-plan optimization you'd do in a relational DB.

**Data consistency:** Since ingestion is now incremental and keyed per source file, consistency risk is scoped to "did the last ingestion run fully complete for a given file" — I don't currently have a transactional guarantee across a multi-chunk file update (a crash mid-update could leave a file partially re-indexed). That's a known gap I'd address with either a staging-collection-then-swap pattern or idempotent re-run logic.

**"Why did you design it this way?"** Because the actual data shape is flat and read-heavy (index once, query many times), a full relational schema would've added complexity with no benefit — the metadata fields I do have exist specifically to support citation accuracy and future filtered retrieval, not because "a database needs tables."

---

# 6. API Design

### `POST /retrieve/`
- **Purpose:** non-streaming, full-response query endpoint (kept as a fallback alongside `/stream/`)
- **Request:** `{"query": string}` — validated via Pydantic `Field(min_length=3, max_length=500)`
- **Response:** `{"answer": string, "sources": [{"source_file": string, "page_number": int}], "confidence": "high"|"medium"|"low"}`
- **Auth:** `X-API-Key` header, validated via FastAPI dependency injection
- **Validation:** length constraints on query; whitespace-only rejected
- **Error handling:** generic 500 with a safe message on internal failure (raw exceptions logged server-side only, never returned to client); 422 on validation failure; 429 on rate-limit breach (`slowapi`, ~10 req/min/IP)

### `POST /stream/`
- **Purpose:** streaming version of the same query flow
- **Request:** same shape as `/retrieve/`
- **Response:** `text/event-stream` — a sequence of `data: {token}\n\n` events, followed by a final `data: {sources, confidence}\n\n` event marking completion
- **Auth/validation/error handling:** identical to `/retrieve/`, plus explicit handling for client disconnect mid-stream

**"How does your backend communicate with the frontend?"** Two REST-shaped endpoints over HTTPS, one of which upgrades to a streamed response using SSE rather than a single JSON payload. I deliberately kept both as thin, symmetric interfaces so the frontend's choice of streaming vs. non-streaming doesn't require different auth or validation handling.

---

# 7. Difficult Technical Challenges (STAR format)

### Challenge 1 — Blocking event loop under an `async def` route
**Situation:** My `/retrieve/` route was declared `async def`, which I assumed meant it was non-blocking by default.
**Task:** I needed to understand why concurrent requests were effectively serializing instead of running in parallel.
**Action:** I traced the call chain and found the route called into `query_rag()`, which called synchronous, blocking Weaviate and Gemini SDK calls. An `async def` function that calls blocking code doesn't yield control back to the event loop — it blocks the *entire* server, worse than if the route had just been declared synchronous in the first place (which FastAPI would've run in a threadpool automatically). I fixed it by changing the route to a plain `def` so FastAPI handles the threadpool dispatch correctly, as the pragmatic near-term fix, with a fully async client/call chain flagged as the more scalable long-term fix.
**Result:** Verified with a small concurrency test firing 5 simultaneous requests — request handling now visibly overlaps in timing logs instead of fully serializing.

### Challenge 2 — Silent frontend bug from an API/type mismatch
**Situation:** The Sources panel in the chat UI was silently rendering nothing, with no errors thrown.
**Task:** Find out why, given TypeScript should theoretically catch a shape mismatch.
**Action:** I traced the actual backend response shape (from `gemini_handler.py`'s response construction) against the frontend's `Source` interface and found they didn't match — the interface expected `{source_file, text_chunk}` while the real payload was shaped differently. TypeScript didn't catch it because the data was coming from an untyped `fetch`/`axios` response, not a statically-checked source, so the mismatch only manifested at runtime as `undefined` fields silently failing a `.filter()`/dedup step.
**Result:** Fixed the interface to match the real response shape, added the fix as part of the response-shape restructuring I was doing anyway for the citation feature, and it's now one of my go-to answers for "describe a real bug you found and fixed" because it's specific and verifiable.

### Challenge 3 — Naive chunking as the retrieval quality ceiling
**Situation:** Early retrieval results were mediocre even after I'd validated the embedding and query logic looked correct.
**Task:** Diagnose whether the problem was embeddings, query formulation, or the underlying data.
**Action:** I discovered the ingestion pipeline was pushing entire PDF pages as single chunks — a `chunk_text()` function existed in the codebase but was never actually called. This meant retrieval was working correctly against garbage input: a page of mixed, unrelated content scored as "one chunk," so similarity search couldn't isolate the actually-relevant sentence within it.
**Result:** Replaced page-level chunking with `RecursiveCharacterTextSplitter` (512/64), which measurably improved retrieval precision on manual spot-checks and, later, on RAGAS context recall once I built the eval harness.

### Challenge 4 — Deciding LRU cache vs. Redis vs. semantic cache
**Situation:** I wanted to reduce redundant Gemini calls for repeated queries without over-building infrastructure for a project this size.
**Task:** Choose a caching approach appropriate to actual usage patterns (campus queries repeat a lot — "hostel timings" gets asked constantly) without adding a new infra dependency like Redis.
**Action:** I started with a simple in-memory LRU cache keyed on the normalized query string for exact-duplicate hits, which is cheap and requires no new infra. I evaluated extending to true semantic caching (a small Weaviate collection of recent queries, checked for near-duplicates before running full retrieval) as a stretch goal.
**Result:** [Fill in your actual measured cache hit rate from testing] — even the simple LRU version meaningfully cuts duplicate-query cost without the operational overhead of standing up Redis for a project at this scale.

---

# 8. Engineering Decisions & Trade-offs

**Decision:** Hybrid search over pure vector search.
**Why:** Pure vector search missed exact-term queries like "CGPA."
**Alternative:** Pure vector search (simpler, one fewer knob to tune).
**Trade-off:** Slightly more complex query construction and one more parameter (`alpha`) to reason about, in exchange for meaningfully better recall on keyword-specific queries.

**Decision:** Cross-encoder re-ranking after hybrid search.
**Why:** Hybrid search's top-10 still contained noise; joint (query, chunk) scoring is more accurate than either fused signal alone.
**Alternative:** Trust hybrid search's ranking directly.
**Trade-off:** Added per-query latency (a second model inference pass) for higher-precision final context — I judged this correct because generation quality is entirely gated on context quality, and the latency cost was small relative to the Gemini generation call itself.

**Decision:** LRU cache over Redis.
**Why:** No new infra dependency, sufficient for expected traffic and repetition patterns.
**Alternative:** Redis-backed cache (durable across restarts, shareable across multiple backend instances if I horizontally scaled).
**Trade-off:** In-memory cache is lost on restart and doesn't share across instances — acceptable for current single-instance deployment, a real limitation the moment I'd horizontally scale.

**Decision:** Sync route (threadpool) over full async rewrite for the blocking-call fix.
**Why:** Pragmatic, low-risk fix that immediately resolved the event-loop-blocking bug without a large, riskier rewrite of the entire Weaviate/Gemini call chain to true async.
**Alternative:** Fully async client chain (async Weaviate client, async Gemini calls) — the "correct," more scalable long-term answer.
**Trade-off:** The sync fix caps concurrency at FastAPI's threadpool size rather than true async concurrency — a real remaining limitation I'd flag proactively if asked "is this actually solved."

**Decision:** Static API key auth over full user authentication.
**Why:** The threat model is "deter casual abuse / API cost overrun," not "support individual user accounts" — there's no per-user data in this system.
**Alternative:** Full auth (JWT, OAuth, user accounts).
**Trade-off:** This is explicitly a deterrent, not real access control — anyone with the key has full access, and I'd say that plainly rather than overselling it as "secure."

**Decision:** RAGAS for evaluation over no formal eval.
**Why:** I had no way to know if a pipeline change actually improved quality versus just "felt" better.
**Alternative:** Manual spot-checking only (what I did before building the harness — fast but not rigorous or repeatable).
**Trade-off:** RAGAS costs real API calls to run (LLM-as-judge), which is why I deliberately did NOT wire it into CI on every push — it runs on-demand when I'm evaluating a specific change.

---

# 9. Performance & Scalability Discussion

**What happens with 10x users?** The first thing to break, before my fix, was the blocking event loop — now that it's fixed (sync route in threadpool), the next likely bottleneck is Gemini's rate limit (15 RPM on the free tier, higher on paid) and Weaviate's free-tier resource limits.

**Current bottleneck:** [Fill in your actual measured retrieval_ms / generation_ms breakdown from your logging]. Generation is almost certainly the larger share of total latency, since it involves a full LLM call versus a vector/BM25 lookup.

**How would you optimize it?** Three concrete levers I've already partially built: (1) the cache layer, which eliminates repeat Gemini calls entirely for duplicate/near-duplicate queries; (2) model tier selection — using a cheaper/faster Gemini tier for simple factual queries and reserving the larger model only when retrieval confidence is low; (3) prompt compression — stripping whitespace and redundant formatting from retrieved chunks before injecting them into the prompt.

**Where would caching help?** Exactly where I put it — in front of the full retrieval+generation call, keyed on normalized query text, since campus chatbot queries repeat heavily ("hostel timings," "attendance requirement").

**How would you scale the system?** Horizontally scale the FastAPI service behind a load balancer, but that requires the cache to move from in-memory to a shared backend (Redis) so cache state isn't siloed per instance, and requires the Weaviate/Gemini clients to remain stateless per-request (which the singleton service pattern already supports, since the singletons hold clients, not per-request state).

**How would you reduce latency further?** Move from the pragmatic sync-route fix to a fully async call chain (async Weaviate client, async Gemini API) so the threadpool ceiling isn't the limiting factor under high concurrency — this is the honest "if I had more time" answer.

---

# 10. Security Considerations

**Authentication:** Static `X-API-Key` header, validated via FastAPI dependency injection on `/retrieve/` and `/stream/`. This is a deterrent against casual abuse, not real per-user access control — I'd say this explicitly if asked how "secure" it is.

**Authorization:** None beyond the single shared API key — there are no user roles or permission tiers, because there's no per-user data model in this system.

**Data protection:** No PII is intentionally stored; query logs (used for latency observability) contain raw user question text, which I'd want a documented retention/anonymization policy for if this were handling real student data at scale — a gap I'd flag proactively.

**API security:** Rate limiting via `slowapi` (~10 req/min/IP) to prevent cost-blowout abuse of the Gemini API; input length validation (`min_length=3, max_length=500`); CORS pinned to explicit known frontend origins rather than a wildcard.

**Common vulnerabilities considered:** Prompt injection — I added a denylist-based mitigation stripping/escaping strings like "CONTEXT:", "---", "IGNORE PREVIOUS INSTRUCTIONS" from user input before it's inserted into the prompt. I'm explicit that this is a shallow defense — paraphrasing, casing tricks, or a different language would likely bypass it, and a more robust defense would need a dedicated prompt-injection classifier or stricter structural separation between user input and system instructions (e.g., using the model provider's native system/user role separation more strictly than a single f-string).

**How could this be attacked?** (1) Cost-abuse via rapid repeated queries — mitigated by rate limiting and caching, not eliminated. (2) Prompt injection to override the "answer only from context" instruction — partially mitigated, not eliminated. (3) API key leakage (e.g., if exposed client-side) — since it's a single static key, leakage means full access until rotated; I don't have automatic key rotation or per-client keys currently.

**How would I improve it?** Move the API key check to per-client keys with individual rate limits and revocation, add a real prompt-injection classifier or stricter prompt templating, and add request logging/alerting on anomalous query volume per key.

---

# 11. Testing Strategy

**What testing was done:** A pytest smoke test suite (`test_smoke.py`) covering app import health and a real end-to-end integration test hitting the live `/retrieve/` endpoint with `httpx.TestClient`, asserting a 200 and a non-empty answer field. Deliberately *not* mocked against Weaviate/Gemini, so it validates the real running pipeline, not a mocked approximation of it — a tradeoff of slower/costlier tests for higher confidence that the actual system works.

**Retrieval-quality-specific testing:** A keyword-assertion golden set (e.g., asserting "75%" and "attendance" appear in retrieval results for an attendance-related query) as a fast regression check, plus the deeper RAGAS harness (25-question golden set, scoring faithfulness/answer_relevancy/context_recall) for measuring actual quality shifts across pipeline changes.

**Edge cases / failure scenarios tested:** empty/whitespace queries (rejected via validation), zero-relevant-context queries (fallback response path), client disconnect mid-stream (handled without leaving a dangling Gemini call).

**Monitoring and logging:** Structured logging (Python's `logging` module, not `print()`) with per-request latency breakdown (`retrieval_ms`, `generation_ms`, `chunks_retrieved`), plus a Prometheus-instrumented `/metrics` endpoint and a lightweight custom `/admin/metrics` rolling-window endpoint for retrieval/generation latency — both behind the same API key auth.

**"How do you know your project works correctly?"** Three layers: smoke/integration tests catch outright breakage, the keyword golden set catches obvious retrieval regressions fast, and RAGAS gives me an actual quantitative signal on answer quality that I can compare before/after a pipeline change — which is exactly how I validated that hybrid search + re-ranking was a real improvement rather than an assumed one.

**What's missing:** Load testing, frontend E2E tests (e.g., Playwright), and CI-integrated RAG evaluation (deliberately excluded from CI due to real API cost on every push, run on-demand instead) — I'd add load testing first if given more time, since that's the biggest unknown about production readiness right now.

---

# 12. ML-Adjacent Section (Read Carefully Before Using)

This project does **not** involve training or fine-tuning a model — it's important to say this clearly and not blur the line, because interviewers will specifically probe whether you understand the distinction. Frame it exactly like this if asked:

"I didn't train a model — I engineered a retrieval-and-generation pipeline on top of pretrained models (an embedding model for retrieval, Gemini for generation), and I applied ML-evaluation rigor to that pipeline via RAGAS rather than to model training."

- **"Dataset":** the 4 source PDFs (academic regulations, hostel code of conduct, and others), not a labeled training dataset — my "data pipeline" is document ingestion and chunking, not data cleaning for training.
- **"Feature engineering" equivalent:** chunk size/overlap tuning, metadata extraction (page number, section, doc type), and the hybrid search `alpha` weighting — these are the closest analogues to feature engineering in this system.
- **"Model selection":** choosing Gemini's Flash tier over a larger tier, and choosing the specific cross-encoder re-ranker model — both cost/quality tradeoff decisions, not architecture design decisions.
- **"Baseline":** pure vector search with no re-ranking and no query rewriting is my legitimate baseline, and I have (or should generate) RAGAS scores comparing that baseline against the final hybrid+re-ranked+rewritten pipeline.
- **"Evaluation metrics":** faithfulness (does the answer stay true to retrieved context, i.e., is it hallucinating), answer relevancy (does the answer actually address the question asked), context recall (did retrieval actually surface the information needed to answer correctly). I can explain what a low score on each one specifically looks like in a real bad answer if asked.
- **"Model drift" equivalent:** there's no training drift since nothing is trained, but there is a real analogous risk — if Google silently updates the underlying Gemini model version, or if new source documents are added that shift what "correct" retrieval looks like, my eval baseline could go stale. I'd want to re-run RAGAS periodically as a drift check, not just once at launch.
- **"Deployment":** the "model" here is really the whole pipeline; deployment is the Docker container + CI, not a model-serving endpoint in the traditional ML sense.

---

# 13. Resume Verification Questions — With Strong Answers

**"You mentioned millisecond-latency semantic search — what's the actual number?"**
"[Cite your real measured retrieval_ms from logging]. That's the vector+BM25 hybrid query time in Weaviate specifically, not counting re-ranking or generation, which are separate stages I track independently in my latency logging."

**"You mentioned implementing streaming — explain exactly how."**
"Retrieval and re-ranking run synchronously first since generation can't start without context. Then I call Gemini's streaming generation API, and wrap each token as an SSE `data: ...\n\n` event via FastAPI's `StreamingResponse`. On the frontend, since native `EventSource` doesn't support custom headers and I needed to send an API key, I used `fetch` with a `ReadableStream` reader instead, appending tokens to the message state as they arrive."

**"Show me the hardest part you coded."**
"The re-ranking integration — changing `retrieve_chunks()`'s return type from a list of raw strings to a list of structured dicts (text, source, page, score) was a breaking change that touched every caller in the pipeline: RAG_CORE, gemini_handler, and the response schema, plus the frontend's Source interface. Migrating that cleanly without leaving half the pipeline on the old shape, while my smoke test still passed, was the most structurally demanding change I made."

**"What exactly did you contribute?"**
"[Be precise and honest here based on your actual role — full-stack if solo, name your specific slice if part of a team.]"

---

# 14. Rapid Fire — 50 Questions with Concise Answers

1. **What does the system do?** Answers campus-policy questions from PDFs using RAG, with citations.
2. **Backend framework?** FastAPI, for native async + Pydantic validation + auto docs.
3. **Vector DB?** Weaviate — hybrid search support out of the box.
4. **LLM used?** Google Gemini (Flash tier) for generation and query rewriting.
5. **Frontend?** React + Tailwind, SPA.
6. **Streaming protocol?** SSE, one-directional server→client token streaming.
7. **Chunking method?** RecursiveCharacterTextSplitter, 512 tokens / 64 overlap.
8. **Why not fixed-size chunking?** Ignores natural document structure, was the original bottleneck.
9. **Retrieval method?** Hybrid search (BM25 + vector), alpha=0.75.
10. **Why hybrid over pure vector?** Vector-only missed exact keyword matches like "CGPA."
11. **Re-ranking model?** `cross-encoder/ms-marco-MiniLM-L-6-v2`.
12. **Why re-rank?** Joint (query, chunk) scoring is more precise than fused hybrid score alone.
13. **How many chunks go into the prompt?** Top 3, post-re-rank, above a similarity threshold.
14. **How is hallucination mitigated?** Similarity threshold + explicit citation requirement + "answer only from context" instruction.
15. **What happens if no relevant context is found?** Explicit fallback message, not a forced answer.
16. **How is confidence computed?** Heuristic based on chunk count and top score above threshold — not calibrated probability.
17. **What is query rewriting?** A short pre-retrieval Gemini call that expands ambiguous queries.
18. **What happens if rewriting fails?** Falls back to the original raw query, never hard-fails.
19. **Why keep the original query for chat history?** So the user's own words aren't silently altered.
20. **Auth mechanism?** Static `X-API-Key` header via FastAPI dependency.
21. **Is that real security?** No — it's a deterrent, not per-user access control.
22. **Rate limiting?** `slowapi`, ~10 req/min per IP.
23. **Prompt injection defense?** Denylist stripping known injection patterns — shallow, not comprehensive.
24. **CORS policy?** Pinned to explicit known frontend origins, not wildcarded.
25. **Error handling?** Generic 500 to client, full exception logged server-side only.
26. **What was the async bug?** `async def` route calling blocking sync code, serializing all requests.
27. **How was it fixed?** Changed route to sync `def`, letting FastAPI use its threadpool correctly.
28. **What's the long-term fix?** Full async client chain (async Weaviate + async Gemini calls).
29. **What was the frontend bug?** `Source` interface didn't match actual API response shape, silently rendering nothing.
30. **How was ingestion originally broken?** Full wipe-and-reingest of the entire Weaviate collection on every boot.
31. **How is ingestion fixed now?** Incremental, per-source-file updates via `delete_chunks_from_source()`.
32. **What metadata does each chunk have?** text, source_file, page_number, section_name, doc_type.
33. **Why those metadata fields?** Precise citation and future scoped/filtered retrieval.
34. **Caching strategy?** In-memory LRU keyed on normalized query text.
35. **Why not Redis?** No shared-instance requirement yet; avoided unnecessary infra for current scale.
36. **What would Redis add?** Persistence across restarts and shared state across horizontally scaled instances.
37. **Evaluation framework?** RAGAS — faithfulness, answer relevancy, context recall.
38. **Why isn't RAGAS in CI?** Costs real API calls on every push; run on-demand instead.
39. **What is faithfulness measuring?** Whether the answer stays true to retrieved context (hallucination check).
40. **What is context recall measuring?** Whether retrieval actually surfaced the needed information.
41. **Is this a trained ML model project?** No — retrieval + generation pipeline on pretrained models, not model training.
42. **Deployment method?** Docker multi-stage build, non-root user, docker-compose for local/prod parity.
43. **CI pipeline covers what?** pytest smoke tests + ruff linting on push/PR.
44. **Why not include eval in CI?** API cost, and it's a slower signal than fast regression tests.
45. **Observability?** Structured logging with per-request latency breakdown, Prometheus `/metrics`, custom `/admin/metrics`.
46. **Biggest current scalability limit?** Threadpool-bound concurrency (from the sync-route fix) and Gemini API rate limits.
47. **What breaks first at 10x load?** Gemini rate limits, likely, now that the event-loop bug is fixed.
48. **What's the single highest-leverage next improvement?** Full async call chain + load testing to validate real capacity.
49. **Biggest known security gap?** Static shared API key, no per-client revocation or granular rate limiting.
50. **What would you rebuild differently from scratch?** [Be ready with a real, honest answer specific to your experience.]

---

# 15. Final Interview Cheat Sheet

## 30-second explanation
"I built a RAG chatbot that answers VIT Chennai campus policy questions — hostel rules, academic regulations — with cited, streamed answers, using FastAPI, Weaviate hybrid search with re-ranking, and Gemini. The part I'm proudest of is building an actual RAGAS evaluation harness so I could measure real quality improvements instead of guessing."

## 2-minute explanation
Use the full answer in **Section 1**.

## 5-minute deep explanation
Section 1 (2 min) → walk through the architecture diagram in Section 2 (1 min) → pick your single strongest STAR story from Section 7 (1.5 min) → close with your RAGAS before/after numbers and your honest "what I'd do next" (30s).

## Top 20 Questions Interviewer Will Most Likely Ask
1. Walk me through the full query flow, start to finish.
2. Why Weaviate?
3. Explain hybrid search and why you added it.
4. Why add re-ranking on top of hybrid search?
5. Walk me through your chunking strategy and the numbers you chose.
6. Why Gemini over other LLMs?
7. How does SSE streaming work here, mechanically?
8. Why SSE instead of WebSockets?
9. How do you know your RAG system actually works well — what's your evaluation strategy?
10. Walk me through the async/blocking bug you found.
11. How do you prevent hallucination, and what are the limits of that approach?
12. What's your security setup, and what's the honest remaining attack surface?
13. What was the hardest bug or decision in this project?
14. What breaks first at 10x or 100x traffic?
15. What was your individual contribution?
16. What edge case does your system still not handle well?
17. Why the service-layer/DI refactor — what problem did it solve?
18. How does incremental ingestion work?
19. What would you improve first with one more week?
20. Explain a specific piece of your code in detail, live.

## Things I Must Remember During the Interview
- Lead with the RAGAS before/after number — it's my strongest, most differentiating detail.
- Never blur "I trained a model" language into this project — I engineered a pipeline on pretrained models.
- Be precise about what's a real security control (rate limiting, validation) versus a deterrent (static API key) — don't oversell.
- Have real numbers ready: retrieval_ms, generation_ms, cache hit rate, RAGAS scores. If I don't have one memorized, say "I have that logged, let me pull the exact figure" rather than guessing.
- My two strongest, most specific bug stories are the async/blocking bug and the frontend Source interface mismatch — lead with these when asked "describe a bug you fixed."

## Mistakes Weak Candidates Make While Explaining Projects
- Reciting what a technology *is* instead of explaining *why they specifically chose it* for *this* system.
- Answering "why X" with "best practice" or "it's popular" instead of naming a real tradeoff.
- Claiming a metric with no actual number behind it.
- Blurring "what I built" with "what I would build with more time" as if both already exist.
- Over-explaining generic RAG/ML theory when asked specifically about their own implementation.
- Getting defensive when a gap is pointed out, instead of owning it plainly and stating what the fix would be — owning a known limitation confidently is a stronger signal than pretending there isn't one.
