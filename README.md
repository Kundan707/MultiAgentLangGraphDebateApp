# The Forum — live debate prep

A private Sites Worker application with four model roles. Affirmative and Negative each search for evidence and build a case, then rebut the opposing case. The Researcher searches the web to audit specific claims. The Judge evaluates the full transcript and audit against a 100-point rubric. All calls use the server-side OpenAI Responses API; the browser never receives the API key.

## Local development

Use Node 22 or newer. The ignored `.env.local` holds `OPENAI_API_KEY`; optional `OPENAI_MODEL` defaults to `gpt-5.4-mini`. See `.env.example` for names only.

- `npm run dev` starts http://localhost:4173.
- `npm test` runs orchestration, source filtering, scoring, request validation, and provider error checks with mocks.
- `npm run build` embeds public assets into the Worker deployment.
- `node scripts/validate-artifact.mjs` validates the built Worker.
- `node --env-file=.env.local scripts/smoke.mjs` runs one complete paid live debate when the API project has credits and model access.

## Hosting

Preserve the Site identity in `.openai/hosting.json`. Set `OPENAI_API_KEY` as a secret using Sites environment settings, then deploy the matching pushed source archive. Keep the Site owner-private. The API depends on the Sites authentication boundary and rejects cross-origin browser calls. Concurrent sessions are limited per visitor within each Worker isolate; this is not a global billing limit. Configure project spend limits in OpenAI Platform before broadening access.

Sessions and evidence notes are stored in this browser's local storage, with a maximum of 20 sessions. Existing prepared practice sessions remain clearly labeled in history. Live runs do not fall back to prepared answers. Interrupted runs preserve completed rounds. Research source links are restricted to URLs returned by the search tool; those links and AI assessments still need human review.

The provisioned key has a 30-day expiration. Rotate the server secret when it expires.
