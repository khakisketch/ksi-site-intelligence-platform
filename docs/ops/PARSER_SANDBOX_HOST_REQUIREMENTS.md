# Parser sandbox verification host requirements

Status: 2026-10-13. Operational requirements for the F-03/F-04 parser → `VALIDATED` →
Analysis → Result/Evidence → review acceptance. This document does not change product
behavior, authorization or acceptance: a passing probe only says the sandbox can run;
the acceptance itself is the evidence.

Related: [F-02~04 first-flow checklist](../superpowers/plans/2026-10-10-f02-04-first-flow-input-checklist.md)
§3–§4, [rebaseline ledger](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md)
(`PARSER_SANDBOX_UNAVAILABLE` record), probe tool
`tools/verify_parser_sandbox_host.py`.

## 1. Why this host matters

On the current workstation the bubblewrap parser sandbox cannot run (user namespaces and
UID mapping are denied), so the product stays fail-closed: only input/permission/lease,
file transfer, policy/manifest/digest and pre-launch conditions are verifiable there. The
parser-launch → `VALIDATED` → downstream chain must run on a host where the sandbox
actually works.

## 2. Capability requirements (probe-judged)

Run the probe on the candidate host:

```bash
uv run --locked python tools/verify_parser_sandbox_host.py
# optional reachability additions:
uv run --locked python tools/verify_parser_sandbox_host.py \
    --core-url http://127.0.0.1:8051 --object-origin http://127.0.0.1:9100
```

Exit 0 = every check passed (acceptance can run); exit 2 = blocked, with the failing
check named. The probe runs exactly the recorded evidence commands:

| Check | Command | Requirement |
|---|---|---|
| bwrap-present | `bwrap --version` | bubblewrap installed (0.9.x recorded working) |
| user-namespace | `unshare -Ur true` | unprivileged user namespaces permitted |
| bwrap-uid-map | `bwrap --ro-bind / / -- /bin/true` | bwrap can set up its user/UID mapping |
| bwrap-net-namespace | `bwrap --unshare-net --ro-bind / / -- /bin/true` | isolated network namespace can be created |

Do not weaken host security settings (e.g. `kernel.unprivileged_userns_clone`, AppArmor
profiles) merely to make a probe pass on a host that is not meant for this acceptance.

## 3. Runtime requirements

- Linux host with Python 3.12 and `uv`; the repository checked out at the acceptance
  commit and the locked environment buildable.
- Loopback-reachable object storage (the cached MinIO on 9100 works for synthetic runs;
  a production-compatible S3 endpoint for real runs) with the recorded bucket.
- Protected material directories for the run being exercised: external authority
  provider config/snapshot (+ key registry), analysis runtime/activation/verification
  keys, principal tokens — all owner-private (0700 ancestors / 0600 files, as the
  loaders enforce). Window expiry is renewable with
  `tools/regenerate_external_validation_chain.py`; the analysis activation follows the
  re-signing step in the checklist §3.
- Free loopback ports for issuer/Core/Console (the existing stack ports are fine when the
  host mirrors the copy-stack layout).

## 4. Acceptance outline (evidence, not a claim)

1. Prepare the environment on the verification host exactly as the checklist §3
   provisioning order describes (separate stack; policy subjects; activation; lanes).
2. Run the same artifact/policy/manifest chain: register → seal → inspection with the
   **sandboxed parser** (this is the step the current host cannot run) → `VALIDATED` →
   Analysis worker → Result/Evidence → review.
3. Preserve transcripts, digests and the failing/passing probe output together; the
   ledger entry must state what was actually run on that host.
4. Real A–E materials (checklist §2) additionally exercise format/CRS/vertical-reference
   compatibility and quantitative checkpoints; the sandbox acceptance does not replace
   them, and neither replaces customer acceptance.
