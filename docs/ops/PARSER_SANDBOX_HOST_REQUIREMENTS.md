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

Exit 0 = every essential check passed (acceptance can run); exit 2 = blocked, with the
failing check named. The probe runs exactly the recorded evidence commands:

| Check | Command | Requirement |
|---|---|---|
| bwrap-present | `bwrap --version` | bubblewrap installed (0.9.x recorded working) |
| user-namespace | `unshare -Ur true` | **informational** — see the Ubuntu 24.04 note below |
| bwrap-uid-map | `bwrap --ro-bind / / -- /bin/true` | bwrap can set up its user/UID mapping |
| bwrap-net-namespace | `bwrap --unshare-net --ro-bind / / -- /bin/true` | isolated network namespace can be created |

**Ubuntu 24.04 note (verified 2026-10-13 on a fresh noble VM):** the default
`kernel.apparmor_restrict_unprivileged_userns=1` denies raw `unshare -Ur` while granting
user namespaces to bwrap through its own AppArmor profile. A host where unconfined user
namespaces are restricted but bwrap works is still sandbox-capable; the probe therefore
treats a raw-`unshare` failure as a warning and lets the bwrap checks decide READY. A
stock noble cloud image does **not** ship/load the bwrap profile, so bwrap fails there
until the standard profile below is loaded (this is the distro-normal grant, not a
security weakening):

```apparmor
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
```

Do not weaken other host security settings (e.g. `kernel.unprivileged_userns_clone`,
broader AppArmor profiles) merely to make a probe pass on a host that is not meant for
this acceptance.

### Verified verification-host recipe (2026-10-13)

A disposable local QEMU VM is a working verification host; the recipe below produced
probe **READY** (3 passed / 1 warning) and the isolation observation:

- `qemu-system-aarch64 -M virt -cpu host -enable-kvm -m 3072 -smp 4` with AAVMF UEFI
  (`-drive if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.fd` + a
  writable `AAVMF_VARS.fd` copy) and the Ubuntu 24.04 arm64 cloud image; a cloud-init
  seed installs `bubblewrap`/`util-linux`, and the guest loads the profile above
  (`apparmor_parser -r /etc/apparmor.d/bwrap`).
- Isolation observation on that host: unprivileged `bwrap --tmpfs / … --unshare-net`
  shows uid/gid 1000, `FS_HOME_HIDDEN`, `FS_WRITE_DENIED`, `NET_BLOCKED`; the hardened
  pattern (`sudo bwrap … setpriv --reuid=10001 --bounding-set=-all --nnp`) shows
  uid/gid 10001, `CapBnd: 0000000000000000`, `NoNewPrivs: 1`.
- Evidence: `/tmp/opencode/ksi-f04-review-20261013/evidence/vm-sandbox-capability-20261013.txt`
  (probe transcript + observation summary; serial console log alongside).

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
