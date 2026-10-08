# Independent verification receipt — P4 Python consumer closure (nonvisual)

Scope: Python/test-consumer closure of the P4 corrected-scope harness repair ONLY
(RB-07/RB-09; test-consumer retirement + fixture safety). NOT final P4/UI/design/browser
acceptance. Synthetic/owned fixtures only; no credentials, live data, stack :3241, install,
sync, Git or runtime change.

## Revision / workspace
- Repo: /home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform ; branch main
- HEAD: 9a3bab1ba710d0c8925cf3ae8bd8e301e425a9cf (unchanged before/after)
- Workspace: HEAD + pending task-owned P4 output (207 status entries at start).
- Ambient umask during ALL runs: 0002 (NOT changed/hidden).
- Toolchain: uv 0.11.15; venv python 3.12.13; pytest 9.1.1; ruff 0.16.0; mypy 2.3.0.

## Bound files — SHA256 identical pre and post (no mutation by this verification)
- scripts/run_core_dev.py                                ed8168c7079a798a482555ba2a691a105d568375d4cdd554af8e3b3e5750ff05
- tests/contract/test_core_dev_platform.py               5ae49f877ef3c7cf5df25eb992599f3fe08339792565120481ad1dace18bc753
- tests/contract/test_analysis_pilot_deployment.py       fee10d1df77b6c64dccc62020626de6beb43185aba0fc86f392395d4306a6876
- tests/contract/test_external_analysis_api.py           79a7a432f18dc5bb3ad035bd0f39910e6ba91a060c51c542c678780c268e52c3
- apps/dashboard/e2e/fixtures/seed_operations_console.py 613438062e6834812650920375fe01332eeb582bc6361aacf88f7bed897cb7ef
- apps/dashboard/scripts/run-local-oidc-stack.mjs        9260020b4125fa5246dc4dbe098afde0ca428b57f7743a785699dceab0baeac9
- Retired-mirror ABSENCE confirmed (not on disk; git status D):
  apps/dashboard/src/app/events/[eventKey]/EventActions.tsx, apps/dashboard/src/lib/core-api/missionSiteGate.ts
- Retired sync-test files ABSENT: test_event_actions_gate_dashboard_sync.py, test_mission_site_status_gate_dashboard_sync.py
- Decision doc §7 recovery SHAs verified against baseline 9a3bab1:
  test_event_actions_gate_dashboard_sync.py  = c850916b6351faf44a8b0dd91f317e4290bed639dba90ef20f543996cb0aa822  (MATCH)
  test_mission_site_status_gate_dashboard_sync.py = bae937ebd59954659af1c52a256e6b22c5d05c4613db4cd5d60e81850978221e (MATCH)

## Exact commands / results (exit codes)
1. uv run --no-sync pytest -q -p no:cacheprovider <scoped 82 set>
   test_core_dev_platform(17) + test_analysis_pilot_deployment(30) + test_external_analysis_api(28)
   + test_domain_enums_dashboard_sync(3) + test_site_autonomy_gate_dashboard_sync(4)
   -> 82 passed in 6.12s ; EXIT 0
2. uv run --no-sync pytest -q -p no:cacheprovider <7 OIDC scope files>
   -> 74 passed in 7.56s ; EXIT 0
3. uv run --no-sync ruff check .        (root/CI scope) -> All checks passed! ; EXIT 0
   uv run --no-sync ruff check <changed py runner+3 tests> -> All checks passed! ; EXIT 0
4. uv run --no-sync mypy --follow-imports=silent scripts/run_core_dev.py tests/contract/test_core_dev_platform.py
   -> Success: no issues found in 2 source files ; EXIT 0
5. uv run --no-sync pytest -q -p no:cacheprovider   (FULL active suite, ambient umask 0002)
   -> 6013 passed, 30 skipped, 0 failed, 98 warnings in 738.57s (12m18s) ; EXIT 0   ** GREEN **
6. uv run --no-sync pytest -q -p no:cacheprovider tests/contract/test_external_analysis_worker_loop.py
   -> 19 passed in 12.97s ; EXIT 0   (known timing-sensitive test PASSES; no timing issue observed)

## New/changed test content confirmed (read, not inferred)
- test_core_dev_platform.py +6 cases: test_retired_event_and_mission_actions_are_absent_even_for_an_admin
  (GET /v1/events; GET /v1/events/generated-retired-event; POST .../transitions; GET /v1/missions;
  POST /v1/missions/plans; POST /v1/missions/.../execution-transitions). Uses a generated UNRESTRICTED
  ADMIN (principal generated-boundary-admin / org generated-boundary-org / Role.ADMIN) and asserts
  whoami 200, sites 200, and each retired read/mutation path 404. This is the nonvacuous replacement
  boundary for the retired TS mirrors; it catches remounting acquisition authority.
- test_analysis_pilot_deployment.py: _candidate creates owned roots explicitly 0700 incl nested base
  (tmp_path.mkdir(0700)); +4 tests: positive test_owned_candidate_is_private_under_a_group_writable_host_umask
  (sets umask 0002) and 3 NEGATIVE controls test_group_writable_candidate_directory_is_still_rejected
  [AUTHORITY_DIR/SECRET_DIR/STATE_DIR] asserting PreflightBlocked UNSAFE_DIRECTORY. Production
  deploy/Core directory checks unchanged (no relax).
- test_external_analysis_api.py: only the two owned fixture roots use .mkdir(mode=0o700); no other change.

## Full-suite delta accounting (evidence)
Prior receipt: 5998 passed / 10 failed / 30 skipped (=6038 collected).
Now: 6013 passed / 0 failed / 30 skipped (=6043 collected). Delta +5 =
  -5 retired dashboard-sync tests (no longer collected) +6 new core_dev cases +4 new deploy cases.
Prior 10 failures: 5 P4 stale sync (retired) + 5 deploy/API (fixed by 0700 fixture roots). All resolved
without weakening admission; the 3 unsafe negative controls prove the check still rejects.

## Unsafe-negative coverage (explicit)
Passed under ambient umask 0002:
- Positive: owned candidate admitted when roots are 0700 (deterministic umask 0002).
- Negative x3: chmod 0770 on AUTHORITY/SECRET/STATE dir -> still rejected UNSAFE_DIRECTORY.
Production admission not relaxed.

## No-mutation / concurrent-writer attribution
- Bound file SHAs byte-identical pre/post; HEAD unchanged; retired mirrors + sync tests still absent.
- git status count moved 207->212 during the window, NOT from this verification: T4 design run 27425391
  wrote apps/dashboard visual sources/tests (mtimes 23:00:44-23:03:25) + new p4-cleanup-render-review.md;
  Primary updated decision doc/ledger (23:08:05). All my pytest runs used -p no:cacheprovider (started
  22:59:29) and write only to pytest tmp; ruff/mypy wrote only gitignored caches. No new Python/root files.
- Live stack :3241 not started/stopped/accessed; no duplicate runtime.

## Open checks / NOT verified (out of scope here)
- Final P4 UI/design/browser acceptance and design-owned rendered review (T4/T5) — later receipt.
- Dashboard tsc/eslint/vitest/next build and Playwright e2e — not run here.
- Not a P4 completion claim.
