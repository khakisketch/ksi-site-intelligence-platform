# Documentation map

The intended shared repository entry is [`../AGENTS.md`](../AGENTS.md); OpenCode V2 loads
`AGENTS.md` only (nested files on discovery), while [`../CLAUDE.md`](../CLAUDE.md) is a
Claude Code-specific wrapper that imports it. For a session, read global policy → project `AGENTS.md`
→ `.opencode/working-state.md` when it exists → [`superpowers/product-state.md`](superpowers/product-state.md)
→ the applicable ledger → revalidate Git. The checkpoint identifies an active checkout task and its
task ledger; a current Human-assigned bounded task persists without closing or reprioritizing a
product slice. Product-state identifies the product slice and its slice ledger. Only if no active
bounded checkout task exists may work selection begin from product-state. Neither an old handoff nor
a generic dated plan supplies current authorization.

Product authority is a **precedence** order for the applicable task, not a second universal startup
sequence: [`00_READ_FIRST.md`](00_READ_FIRST.md) → Product Constitution → Final Decision Ledger →
relevant PRD section → contract/schema → relevant accepted ADR → acceptance. A supporting design is
read only when selected by an ADR or higher authority and retains its declared subordination. Then use owner
and test/acceptance material required by the task. [`DOCUMENT_STATUS.md`](DOCUMENT_STATUS.md)
distinguishes active sources from historical material.

The current platform direction is [ADR-KSI-038](architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md):
spatial-data delivery and analysis for external applications. [SDP-20260930](superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md)
is the selected long-term planning and documentation ledger, with staged deliverables and open
decisions. [ADR-KSI-037](architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md)
retains the first earthwork analysis case's semantics and acceptance.
[ADR-KSI-039](architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md)
bounds long-term product responsibility: acquisition/flight/autonomous execution are out-of-product
and their sources are retained transitional implementation, now archived by P3. The initial
2026-09-30 planning-only request is historical; subsequent development approvals are in the
[current bounded rebaseline ledger](superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md).
[P5's integrated audit](audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md) records actual
source/verification limits. No cleanup record closes `EXT-VAL` or customer acceptance.

| Client | Intended repository entry | Evidence limit |
|---|---|---|
| Codex | `AGENTS.md` instruction chain | Per-run behavior is documented, not accepted for this checkout/session ([official docs](https://learn.chatgpt.com/docs/agent-configuration/agents-md)). |
| OpenCode (V2) | root/global `AGENTS.md`; nested `AGENTS.md` loaded as the agent explores | V2 loads `AGENTS.md` automatically and does not resolve the `instructions` config array; referenced documents here remain an explicit read path ([official docs](https://opencode.ai/v2/docs/instructions)). |
| Claude Code | `CLAUDE.md` → `@AGENTS.md` | Wrapper applies to Claude Code clients only (OpenCode V2 does not use `CLAUDE.md`); existing sessions/worktrees still must reread/adopt reviewed docs ([official docs](https://code.claude.com/docs/en/memory)). |

| Path | Routing role |
|---|---|
| `product/` | Constitution, durable decision ledger, PRD, and domain invariants |
| `architecture/` | Accepted ADRs and detailed control/source boundaries |
| `design/` | Active target contracts only when explicitly selected by an ADR/higher authority; subordinate and not runtime proof |
| `acceptance/` | Acceptance criteria and traceability |
| [`DEVELOPMENT_HANDOFF.md`](DEVELOPMENT_HANDOFF.md) | Recreate a local development environment; not a task ledger or release claim |
| `goals/` | Capability-track index and historical plans/handoffs; not current task selection |
| `.opencode/working-state.md` + task ledger | Active checkout task resume after Git revalidation; does not close/reprioritize product slice |
| `superpowers/product-state.md` + slice ledger | Current Goal/Milestone/slice; choose work only when no active bounded checkout task exists |
| `superpowers/plans/`, `superpowers/specs/` | Active only when explicitly named by current authority, the active checkout task ledger, or product-state's named slice ledger; otherwise dated implementation history |
| `hil/`, `ops/`, `security/`, `dji/` | HIL/field, operations, security, and provider-specific routing |
| `audit/`, `archive/`, `.ai/`, `.ksi/` | Dated evidence or historical material; not product/current-state authority |

Repository code ownership and runtime boundaries are in [`../REPOSITORY_STRUCTURE.md`](../REPOSITORY_STRUCTURE.md).
