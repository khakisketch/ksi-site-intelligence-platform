# apps/dashboard

KSI Operations Console: Home, Sites and the existing five-tab Site workspace
(overview, observations, assets, analysis, work). P4 removed Mission/flight/Edge/managed
acquisition screens and actions; S3's older mission/event/fleet scope is historical only.
Auth, scoped external registration, work operations, result/evidence and unavailable states remain.

P4 local technical evidence is in [`p4-cleanup-evidence/verification/receipt.md`](p4-cleanup-evidence/verification/receipt.md)
and the design-owned [`p4-cleanup-final-render-review.md`](p4-cleanup-final-render-review.md).
P5 reuses their unchanged source/capture hashes, not a new aesthetic judgment. The former evidence
stack at `http://localhost:3241/` (Core8041/Identity9041, host-loopback only) is no longer reachable
as of the P5 read-only check; it is not a live customer/demo link. No duplicate server was started.
Current approval/limitations: [task ledger](../../docs/superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md)
and [first-flow gap map](../../docs/audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md).

## Local development

An intentionally isolated synthetic rehearsal can set
`KSI_DASHBOARD_SYNTHETIC_DEMO=1` with the `LOCAL` deployment profile. The Console then
labels its measurements as synthetic, for screen/workflow checks only. Do not enable
this marker for customer/real data: it neither sanitizes records nor grants authority,
activates policies, bypasses inspection, or changes any API/analysis/review behavior.
External deployments ignore this display marker. The current approved task ledger
owns the actual rehearsal, data location and verification evidence.

1. Start the standard local stack:

   Commands below describe the existing workflow, not permission to install, alter Tailscale,
   register a persistent service or restart a live target. Use the already prepared toolchain;
   dependency installation is separately approved.

   ```bash
   cd apps/dashboard
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

Run the component and production-build gates before handing off an authorized UI change:

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
npm run test:e2e
```

To repeat the same non-mutating checks against an already running tailnet-only
development stack, set its origin explicitly:

```bash
KSI_DASHBOARD_E2E_BASE_URL=http://<magic-dns-name>:3210 npm run test:e2e
```

Playwright state is isolated in a run-scoped `test-results/runtime-*`
directory; it does not reuse or overwrite the normal local OIDC journals. The
current fixture seed writes five owned synthetic Sites/WorkAreas through real stores;
four managed-mode WorkOrders are explicitly historical/non-executable and one external
WorkOrder is APPROVED/OPEN. E2E-only OIDC mapping grants these exact fixture resources;
the normal and empty-organization accounts do not inherit those grants. It creates no Mission,
device receipt, ProcessingJob/result or Event. Scoped-OIDC Site creation is the F-01
capability bootstrap (server-issued `siteId`, `SITE_BOOTSTRAP` via the protected registry;
[ADR-KSI-040](../../docs/architecture/ADR-KSI-040-site-bootstrap-and-grant-ownership.md)):
the fixture accounts do not carry that capability, so this suite does not exercise it —
actual-auth acceptance evidence is recorded in the
[task ledger](../../docs/superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md).
The `/sites/new` flow resolves its registration mode from Core's `whoami` registry
metadata (`getSiteRegistrationMode`): legacy opaque accounts keep the client `siteId`
form, mapped accounts use the bootstrap form. Missing optional Analysis/workflow
configuration and real storage bytes remain honest unavailable states, not successful first-flow evidence.
Visual snapshots and fixture data are not HIL evidence and never change a DJI
capability from `NOT_VERIFIED`.

Built with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app)
(Next.js App Router, TypeScript, Tailwind v4).
