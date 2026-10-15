# External inspector/measurement rootless profile — Task 5c operational verification

Status: LOCAL VERIFICATION RECORD. This is synthetic, approved-host verification evidence.
It is not customer/field acceptance, deployment approval, CI evidence, or a claim that the
profile is production-supported on any other host.

## Environment

- Approved host: local QEMU/AAVMF VM (`ksi-vmcheck`, Ubuntu 24.04 arm64), launcher user
  `ksi-inspector` (uid 997), worker user `ksi-validator` (uid 999), rootless Docker 29.9
  (socket owner 997, mode 0600), cgroup v2, systemd 255 user manager.
- Live services exercised: `ksi-external-inspector.service` and
  `ksi-external-measurement.service` (systemd-activated listeners
  `inspection.sock` / `measurement.sock`, socket mode 0660 + validator ACL, parent 0710).
- Verification tool (repo): `tools/task5c_host_enforcement_verify.py` — runs ON the approved
  host as the launcher user, creates uniquely named transient slices and containers, prints
  `PASS`/`FAIL` per proof, and cleans up. Evidence log:
  `/tmp/opencode/ksi-task5c-20261015/harness-run.log` (27 PASS, 0 FAIL, `HARNESS OK`).

## Proof results (live, 2026-10-15)

| Required proof | Result | Evidence |
|---|---|---|
| user-manager `StartTransientUnit(..., "fail", ...)` | PASS | Duplicate creation of the same slice under `mode="fail"` is rejected (`SystemdRuntimeUnavailable`); slice created through the same `LibsystemdUserManager` the daemons use |
| exact child `ControlGroup` descent | PASS | `control_group = /user.slice/user-997.slice/user@997.service/ksi.slice/ksi-measurement.slice/<attempt slice>`, parent slice name `ksi-measurement.slice` |
| retained cgroup identity / controllers / non-assumed CPU | PASS | `cgroup.controllers = cpu memory pids`; `cpu.stat usage_usec = 0` on the fresh slice; unit `InvocationID` + `ObjectPath` captured |
| Engine API 1.44 `CgroupParent` slice-unit mapping | PASS | Container created with `CgroupParent=<attempt slice>`; `/proc/<pid>/cgroup = 0::…/<attempt slice>/docker-<id>.scope` — the container actually lands under the attempt slice |
| fixed scope controls | PASS | `cpu.weight = 100` on the created slice (CPUWeight property applied) |
| bounded attach + anonymous-spool / response-close | PASS | Real measurement entrypoint run with captured frames: `SECONDARY_STAGED` (anonymous `O_TMPFILE` spool on `/work`) → `PRIMARY_MOUNT_VERIFIED` → typed `FAILED` terminal; stdout framed bytes fully consumed (clean close), stderr 0 bytes, exit 0 |
| `populated=0` | PASS | `cgroup.events` `populated 0` while empty → `populated 1` with the container running → `populated 0` after exit |
| stable final CPU before exact Docker removal | PASS | Two 300 ms-separated reads of the slice's `cpu.stat usage_usec` equal (`69613 == 69613`); exact `DELETE /containers/<id>` then returned 204 |
| exact `StopUnit` + unit/cgroup disappearance before staging cleanup | PASS | `stop_exact` applied; the unit and its cgroup directory are gone afterwards (`cgroup_gone=True`) |
| container UID mapping / read-only input bind | PASS | `User=10004:10004` in effect; input mount `RW=false`; active probe reports `UID 10004 10004` and `ROFS_WRITE DENIED (OSError)` |
| no-network | PASS | `NetworkMode=none`; active probe `NET_CONNECT DENIED (ConnectionRefusedError)`, `/proc/net/dev` shows only `lo` |
| workspace ownership | PASS | Active probe: `WORK 10004 10004 0o40700` (uid/gid/mode as required by the entrypoint checks) |
| hostile input through the real lane | PARTIAL (host-backed) | A real registration whose "ortho" was a grayscale copy was correctly rejected `UNSUPPORTED_RASTER` by the sandboxed parser while the DSM measured cleanly; the 40-case adversarial suite (`tests/contract/test_external_inspector_adversarial_inputs.py`) runs in-process. A hostile artifact driven end-to-end through the Core lane is not yet run |
| cancellation / kill latency / orphan recovery | PARTIAL | Live incident 2026-10-15: a one-off systemd transient-slice creation ambiguity left a pre-parent attempt; both daemons correctly fail-closed (latched, immediate connection resets) and were recovered with the documented procedure (preserve journal + staging, stop leftover attempt slices, restart). Bounded kill-latency numbers and an end-to-end orphan-recovery drill were NOT measured |

## Recorded operational evidence (prior runs, same host)

- Attempt journals `/var/lib/ksi-external-runtime/launcher/journal/attempts.jsonl` and
  `measurement-journal/attempts.jsonl`: `INTENDED → STAGING_ALLOCATED → INPUT_BOUND →
  RUNTIME_PARENT_CREATING → RUNTIME_PARENT_BOUND → CONTAINER_CREATING → CONTAINER_BOUND →
  CLEANUP_REQUIRED (BACKEND_COMPLETED|BACKEND_FAILED) → CLEANED`, with the runtime-parent
  receipt recording `controllers cpu/memory/pids`, `baselineCpuCounter 0`, unit name,
  control group, and invocation identity.
- Full parser-to-review chain (2026-10-15, generation v19): registration → sandboxed
  parser inspection (all outcomes MEASURED) → sandboxed measurement checkpoint
  VALIDATED (3/3, zero error) → mapping admitted → ELIGIBLE → analysis COMPLETED
  (net +0.008 m³, numerically verified) → operator review ACKNOWLEDGED. This exercises the
  contained lanes end-to-end with real bytes under the profile above.

## Open items / limits

- The decisive pytest selection `-k 'host_'` currently collects only the in-process
  import-boundary case; converting `tools/task5c_host_enforcement_verify.py` into
  `test_host_*` cases executed on the approved host remains open. Until then the
  script-driven verification above is the standing evidence.
- Cancellation kill-latency, orphan-recovery drill, and hostile-input end-to-end are
  partial as noted; "unavailable is failure" still applies to those three.
- No cloud/customer host, no production TLS/deployment, no CI, no customer artifact.
  Unknown facts stay explicit; nothing here promotes device/field/customer acceptance.
