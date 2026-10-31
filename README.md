# The Forum — live debate prep

A private Sites Worker application with six model roles. Affirmative and Negative each search for evidence and build a case. The Questioner and Rebuttal agent challenge both sides; each side answers before rebutting the opposing case. The Researcher searches the web to audit specific claims. The Judge evaluates the full transcript and audit against a 100-point rubric. All calls use the server-side Anthropic Messages API; the browser never receives the API key.

## Local development

Use Node 22 or newer. The ignored `.env.local` holds `ANTHROPIC_API_KEY`; optional `ANTHROPIC_MODEL` defaults to `claude-sonnet-5`. See `.env.example` for names only.

- `npm run dev` starts http://localhost:4173.
- `npm test` runs orchestration, source filtering, scoring, request validation, and provider error checks with mocks.
- `npm run build` embeds public assets into the Worker deployment.
- `node scripts/validate-artifact.mjs` validates the built Worker.
- `node --env-file=.env.local scripts/smoke.mjs` runs one complete paid live debate when the API project has credits and model access.

## Hosting

Preserve the Site identity in `.openai/hosting.json`. Set `ANTHROPIC_API_KEY` as a secret using Sites environment settings, then deploy the matching pushed source archive. Keep the Site owner-private. The API depends on the Sites authentication boundary and rejects cross-origin browser calls. Concurrent sessions are limited per visitor within each Worker isolate; this is not a global billing limit. Configure spend limits in the Anthropic console before broadening access.

Sessions and evidence notes are stored in this browser's local storage, with a maximum of 20 sessions. Existing prepared practice sessions remain clearly labeled in history. Live runs do not fall back to prepared answers. Interrupted runs preserve completed rounds. Research source links are restricted to URLs returned by the search tool; those links and AI assessments still need human review.

Research uses Claude web search first, followed by a separate JSON synthesis call because web citations and structured output cannot be requested together. Authentication, billing, model access, and web search errors are surfaced without exposing provider credentials.

## Agent voice playback

Kokoro-82M is the default speech engine, running quantized ONNX inference in a browser Web Worker with kokoro-js 1.2.1. Each role has its own selectable neural preset voice. The pinned Kokoro browser library is packaged with the Site; model/tokenizer data, voice weights, and the ONNX WASM runtime download from Hugging Face and jsDelivr as needed. Model artifacts use the runtime's browser cache. Debate text is processed on-device for speech, and no additional voice-service key is needed. System Speech Synthesis voices remain an explicit fallback in Voices settings. Voice selections, playback speed, and the optional automatic-reading preference are stored locally.

Individual contributions have Listen controls. Play debate reads the available transcript in canonical order. Automatic reading queues new rounds in that same order even when model calls finish out of order. Pause, resume, stop, changing saved sessions, and starting a new debate manage the speech queue. Long passages are split into short utterances and raw source URLs are omitted from narration. Text and linked sources remain visible. Browsers may require a playback click before allowing audio; blocked or unsupported playback shows an explanatory message.

## Questions, challenges, and judging

New debates use six roles. After opening cases, the Questioner asks two questions per side (Q1/Q2); the Rebuttal agent identifies two weaknesses per side and poses follow-ups (R1/R2). Each side must answer its four assigned questions before its rebuttal. The source audit includes empirical claims made in those answers. The Judge receives the full question-and-answer transcript.

The new 100-point rubric assigns 25 points each to reasoning and feasibility, evidence quality, rebuttal effectiveness, and question handling. Question handling rewards direct, relevant, supported answers and honest acknowledgment of uncertainty; evasive replies are penalized. The verdict includes side-specific feedback referencing the Q/R IDs. Older sessions retain their original three-criterion scorecards. Questions, answers, challenges and judging feedback are included in voice playback and exported notes.


## Kokoro download and playback

Open Voices and click Download Kokoro, or click a role preview/Listen to initialize on first use. Download progress and readiness are visible in the settings. CPU/WASM with the q8 model is used for broad browser compatibility; initial downloads and inference speed depend on network and device. Six default voices are Heart, Michael, Emma, Fenrir, Bella, and George. Subsequent passages are prepared in the worker while current audio plays. The audio cache is bounded, canceled generations cannot start stale playback, and blob URLs are released after playback. Model downloads can be retried; system voices can be selected manually if neural loading fails.

`npm install` installs the pinned library. `npm run build` embeds its browser bundle and Apache license, not its Node inference stack. Node-only image-processing dependencies reported by npm are not included in the deployed browser/Worker artifact. The model weights are Apache-2.0 licensed; see the Kokoro model card and `/kokoro-LICENSE.txt` for library licensing.
