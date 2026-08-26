# apps/dashboard

KSI Dashboard: mission, events, site twin, fleet/edge, reports and expert mode.

S3 MVP scope (see `docs/architecture/03_DASHBOARD_UX_GOALS.md`): home, site
list/detail, event triage, mission list, site-registration wizard, new-survey
wizard.

## Local development

1. Start the standard local stack:

   ```bash
   cd apps/dashboard
   npm install
   npm run dev
   ```

   This starts three loopback-only processes: KSI Local Identity, Core in OIDC
   mode, and the Operations Console. It also configures persistent, tailnet-only
   Tailscale Serve HTTP proxies for the Dashboard (`:3210`) and local Identity
   (`:9010`). Open the printed MagicDNS URL from any authorized tailnet device
   and continue with the default development operator. Role-specific accounts
   are available only under the advanced test control. The browser never asks a
   human to paste a Bearer token. The services are not bound to LAN or public network
   interfaces.

   The `KSI 로컬 인증 테스트` page is the development-only OIDC issuer, not an
   Operations Console product screen. Choose `기본 개발 계정으로 계속` for the
   normal path; the optional role controls exist only for RBAC checks and do not
   represent the production login experience.

   Core journals persist below `.dev-data/local-oidc-core`; local issuer keys
   and secrets persist below `.dev-data/local-identity`. Both are ignored by Git.

   If Tailscale is intentionally unavailable, use the explicit localhost rollback:

   ```bash
   npm run dev:local
   ```

   Tailscale Serve configuration survives the dev process. To remove only these
   two development endpoints without touching other Serve routes:

   ```bash
   tailscale serve --http=3210 off
   tailscale serve --http=9010 off
   ```

   On the KSI development host, the stack can be kept available across SSH
   disconnects and machine restarts with the repository-owned user service:

   ```bash
   systemctl --user enable --now \
     "$PWD/../../deploy/systemd/ksi-operations-console-dev.service"
   systemctl --user status ksi-operations-console-dev.service
   journalctl --user -u ksi-operations-console-dev.service -f
   ```

   When the service is enabled, edit the source normally; Next.js hot reload is
   already running. Do not launch a second `npm run dev` on the same ports. If
   the stack launcher or its environment changes, restart the service:

   ```bash
   systemctl --user restart ksi-operations-console-dev.service
   ```

   Roll back only the persistent dev stack with:

   ```bash
   systemctl --user disable --now ksi-operations-console-dev.service
   ```

2. To run only the Dashboard for a focused UI investigation, use:

   ```bash
   npm run dev:dashboard
   ```

   In that exceptional mode provide the Core and OIDC environment variables
   explicitly. It is not the supported integration test path.

## Operations Console validation

Run the component and production-build gates before handing off a UI change:

```bash
npm test
npm run lint
npx tsc --noEmit
npm run build
```

The browser suite starts an isolated local Identity/Core/Dashboard stack and
checks the `390`, `768`, `1024`, and `1440` px layouts, OIDC sign-in, primary
navigation, horizontal overflow, touch targets, reduced motion, and serious or
critical axe-core findings:

```bash
npx playwright install chromium
npm run test:e2e
```

To repeat the same non-mutating checks against an already running tailnet-only
development stack, set its origin explicitly:

```bash
KSI_DASHBOARD_E2E_BASE_URL=http://<magic-dns-name>:3210 npm run test:e2e
```

Playwright state is isolated in a run-scoped `test-results/runtime-*`
directory; it does not reuse or overwrite the normal local OIDC journals. The
browser suite registers three synthetic Sites, their work areas, and **draft
WorkOrders only** through the same authenticated Core route used by the
Console. It creates no Mission, device receipt, processing result, or Event.
Visual snapshots and fixture data are not HIL evidence and never change a DJI
capability from `NOT_VERIFIED`.

Built with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app)
(Next.js App Router, TypeScript, Tailwind v4).
