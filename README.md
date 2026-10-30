# The Forum — live debate prep

A private Sites Worker application with four model roles. Affirmative and Negative each search for evidence and build a case, then rebut the opposing case. The Researcher searches the web to audit specific claims. The Judge evaluates the full transcript and audit against a 100-point rubric. All calls use the server-side Anthropic Messages API; the browser never receives the API key.

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

The browser Speech Synthesis API reads the existing debate text aloud. Each role has its own selectable voice, with role-specific pitch defaults; available voices depend on the visitor's device and browser. No additional voice-service credential is required. Voice selections, playback speed, and the optional automatic-reading preference are stored locally.

Individual contributions have Listen controls. Play debate reads the available transcript in canonical order. Automatic reading queues new rounds in that same order even when model calls finish out of order. Pause, resume, stop, changing saved sessions, and starting a new debate manage the speech queue. Long passages are split into short utterances and raw source URLs are omitted from narration. Text and linked sources remain visible. Browsers may require a playback click before allowing audio; blocked or unsupported playback shows an explanatory message.
