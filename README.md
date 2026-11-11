# The Forum — Python debate agents

A local debate-preparation app with six Claude-powered debate roles, a tool-calling coordinator, durable checkpoints, local vector memory, streamed text, a scored verdict, and on-device Kokoro neural voices. All agent logic and the local API server are written in Python. The browser interface and browser-side speech engine remain HTML, CSS, and JavaScript.

## Run locally

Requires Python 3.11+ and Node/npm for the Kokoro browser library. From this project directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
npm ci
.venv/bin/python -m forum
```

Open **http://localhost:8000**. The server binds to `127.0.0.1` by default. To change the port, use `--port 8001`.

The existing ignored `.env.local` is reused. On a new computer, configure `ANTHROPIC_API_KEY` there; optional `ANTHROPIC_MODEL` defaults to `claude-sonnet-5`. `.env.example` contains names only. No API credentials are served to the browser. `requirements.lock.txt` pins the tested Python environment, including development tools; `requirements.txt` lists runtime dependencies only.

## Where the agents live

- `forum/coordinator.py`: Claude chooses registered tools, checks prerequisites, tracks checkpoints, retries recoverable failures, and hands off to a human. This is the default execution path.
- `forum/memory.py`: embedded Qdrant semantic search, FastEmbed embeddings, saved debate records, and SQLite session journals.
- `forum/agents.py`: readable Python classes for Affirmative, Negative, Questioner, Rebuttal, Researcher, and Judge.
- `forum/debate.py`: agent construction and the standalone fixed-pipeline runner retained for tests and comparison. Failed or cancelled parallel work cancels its siblings.
- `forum/claude.py`: asynchronous Anthropic API calls, web-search continuation, source extraction, structured output, and safe provider errors.
- `forum/models.py`: Pydantic response contracts and validation, including unique question IDs, score bounds, and agreement between totals and winner.
- `forum/app.py`: FastAPI routes, newline-delimited JSON streaming, heartbeats, timeout/cancellation, bounded concurrency, and explicit static-file allowlisting.
- `forum/config.py`: local configuration and secret handling.
- `forum/__main__.py`: local server entry point.

## Debate sequence and judging

Affirmative and Negative independently search for evidence and build opening cases. The Questioner asks two questions per side (Q1/Q2). In parallel, the Rebuttal agent identifies two weaknesses per side and asks follow-ups (R1/R2). Each side answers all four assigned questions and rebuts the opposing case. The Researcher independently searches to audit up to six consequential empirical claims, including those in the answers. Source links are restricted to URLs actually returned by web search.

The Judge sees the full transcript and research audit. The 100-point rubric gives 25 points each to reasoning and feasibility, evidence quality, rebuttal effectiveness, and question handling. Direct, supported answers and honest admissions of uncertainty matter; evasive answers lose credit. Feedback references specific Q/R IDs. Older saved sessions retain their original scorecards.

## Voice and frontend

`public/` contains the existing interface, session history, exported notes, and playback controls. Kokoro-82M runs locally in a browser Web Worker using pinned `kokoro-js` 1.2.1, q8 ONNX, and CPU/WASM inference. The Python server serves its browser library from `node_modules`; no Node server or JavaScript agent backend is needed for the Python version.

Open Voices and choose Download Kokoro, or click Listen to initialize on first use. Model/tokenizer artifacts, voice weights, and the WASM runtime download from Hugging Face and jsDelivr as needed and use the runtime's browser cache. Speech text is processed on-device, with no additional speech API key. Available neural presets include distinct voices for all six roles. System voices remain a manual fallback. Model and library licensing are Apache-2.0; library license is available at `/kokoro-LICENSE.txt`.

Sessions and evidence notes are stored in browser local storage (up to 20 sessions). Text remains visible during playback. The audio queue supports automatic reading, role selection, speed, pause/resume, stop, and cancellation. A bounded audio cache and prefetching reduce repeat generation and gaps.

## Verification

```sh
.venv/bin/python -m pytest -q
npm test
```

One live, paid Claude debate can be tested with:

```sh
.venv/bin/python -m forum.smoke
```

`/healthz` checks the local server, `/api/config` reports readiness without exposing a key, and `/docs` provides FastAPI's endpoint reference. A successful config check means a key is configured; it does not verify provider credits or access.

## Local and hosted versions

`npm run dev` starts the local Python server. The previously published Site is a separate deployment of the earlier JavaScript version. Deploying this version requires a Python-capable host.

Before exposing the Python server publicly, configure authentication and an explicit trusted host/origin policy, along with hosting-level rate/spend controls. The local default intentionally accepts only localhost hosts and same-origin browser requests; it does not treat arbitrary request headers as authenticated identities.


## Coordinator and durable state

The default API now runs a real Claude tool-use loop. Each decision selects a registered tool: build either opening, ask questions, challenge cases, answer as either side, review sources, judge, save, or hand off to a human. Tools cannot execute arbitrary shell commands or URLs. Dependency checks prevent judging before the evidence review or saving before a valid verdict. Claude receives the completed steps, latest tool results, research summary, available actions, and recovery budget. Tool calls and tool-result messages are retained across decisions.

Each successful step is checkpointed in `data/sessions.sqlite3`. Resuming reconstructs the transcript from those checkpoints and does not rerun completed agent steps. Interrupted sessions appear under Past sessions → Resume unfinished debates. A handoff shows the issue and a question, with an optional clarification field and Resume button. Fixing an API key in `.env.local` requires restarting the local server before resuming. Credit top-ups can be retried using the same configured key.

Transient network, rate-limit, and invalid-output errors have a maximum of three attempts per tool. Configuration, billing, refusal, and repeated failures pause for a human. Each invocation has a 30-decision and 15-minute budget. Stopping the browser request cancels pending work while retaining completed steps. Resume gives the user a fresh bounded attempt budget. A save failure retains the judged debate so only storage needs to be retried.

## Vector memory and previous-debate choice

Completed debates are stored in local **Qdrant**, under `data/vectors`, with full transcripts, source audits, verdicts, model names, and original dates. **FastEmbed BAAI/bge-small-en-v1.5** creates 384-dimensional embeddings locally; its roughly 64 MB model is downloaded once into `data/models`. No embedding API key is needed. The whole `data/` directory is ignored by Git; back it up to retain debate memory and checkpoints.

Before any debate agents run, the server searches semantic memory. Up to three results above a cosine-similarity threshold of 0.82 are offered. The student explicitly chooses an earlier debate or a new run. Similar resolutions, including opposing policy wordings, are never automatically treated as equivalent. Opening a saved debate makes no Claude calls. Choosing new runs fresh research and stores a separate version. Saved evidence keeps its original date. Incomplete debates stay in checkpoints and are not indexed as completed debates.

The browser uses `/api/debates/check` for the choice dialog; `/api/debate` independently enforces the check. `/api/debates/{id}` retrieves a completed debate, and `/api/sessions` lists resumable checkpoints. A failed lookup is surfaced to the user, who may repair it or explicitly choose a fresh run. Embedded Qdrant is a single-process local database: use one app server process for this setup.

The end-to-end coordinator and vector retrieval check is:

```sh
.venv/bin/python -m forum.coordinator_smoke
```

This performs a new paid debate and saves the real result to local memory. Unit tests use isolated databases and mock model calls, including recovery, rejected tools, handoff/resume, cancellation, persistence across reopen, duplicate prevention, and the no-model-call memory-choice path.

### LangChain agents and tools

The Python backend uses `ChatAnthropic` through LangChain in `forum/claude.py`.
Agent prompts in `forum/agents.py` run through `ChatPromptTemplate` and
`with_structured_output`, followed by local Pydantic validation. Research calls
use Claude's built-in web search through `bind_tools`.

`forum/tools.py` defines typed async `@tool` functions for case building,
questions, challenges, answers, source review, judging, saving, human handoff,
and semantic memory search. The coordinator binds these tools to Claude and
executes the chosen tool with `ainvoke`. Session state stays in application
closures; tool arguments cannot overwrite it. Dependency checks still prevent
judging an incomplete debate.

`forum/coordinator.py` retains the durable checkpoint and recovery loop.
Existing saved tool histories are converted to LangChain `AIMessage` and
`ToolMessage` objects, preserving resumable sessions and Qdrant memory.
LangSmith tracing is disabled; no LangSmith account or key is required.
