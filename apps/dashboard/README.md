# apps/dashboard

KSI Dashboard: mission, events, site twin, fleet/edge, reports and expert mode.

S3 MVP scope (see `docs/architecture/03_DASHBOARD_UX_GOALS.md`): home, site
list/detail, event triage, mission list, site-registration wizard, new-survey
wizard.

## Local development

1. Start a local KSI Core backend (durable filesystem-backed, dev auth tokens):
   ```bash
   uv run python scripts/run_core_dev.py
   ```
   Copy one of the printed bearer tokens.
2. `cp apps/dashboard/.env.local.example apps/dashboard/.env.local` and set
   `CORE_API_TOKEN` to that token (`CORE_API_BASE_URL` defaults to
   `http://127.0.0.1:8000`).
3. ```bash
   cd apps/dashboard
   npm run dev
   ```
   Open [http://localhost:3000](http://localhost:3000).

Built with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app)
(Next.js App Router, TypeScript, Tailwind v4).
