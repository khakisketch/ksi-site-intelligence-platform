# Physical Site Rebaseline Disposition — Inventory Provenance and Planning-Only Record

Date: 2026-10-07. Authority: ADR-KSI-039 (acquisition/flight/customer
production reconstruction outside long-term Site Intelligence
responsibility); design
`docs/superpowers/specs/2026-10-07-physical-site-platform-rebaseline-design.md`
§6; plan `docs/superpowers/plans/2026-10-07-physical-site-rebaseline-foundation.md`
Task 2.

## 1. Provenance and planning-only meaning

- Frozen source: `docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv`,
  SHA256 `89a9baf3b1f1a593bf65af02810595cea0f677a740ceb0fdf9f2e789071639e3`.
  Do not edit it to manufacture validation results.
- Baseline commit: `72c526ba7b6d423443d9733d1189fccd8b47ada6`, 2378 tracked
  entries. Every CSV row binds one frozen Git object at that commit.
- Row counts by label: PROTECT 82, RECONCILE 1447, RETAIN 362,
  RECONCILE_DOCUMENT 293, ARCHIVE_CANDIDATE 194.
- Validator: `tools/check_physical_site_disposition.py`
  (`validate_disposition_manifest(root, manifest)`), contract tests
  `tests/contract/test_physical_site_disposition.py`.
  Verify with:
  `python tools/check_physical_site_disposition.py --manifest docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv`
  (exit 0 only when all checks pass; exit 1 with safe path/reason findings).
  Requires the baseline commit in local Git history (full clone); a missing
  baseline fails explicitly — no automatic fetch, no silent skip.
- **This inventory authorizes nothing.** No ARCHIVE_CANDIDATE row is execution
  approval, and no generic RECONCILE / RECONCILE_DOCUMENT row permits deletion
  or blanket moves. This baseline predates extraction edits (Task 3+), so any
  later actionable manifest must bind the then-current source revision and
  hash, full consumer closure, and the inverse move — not reuse these rows
  as move orders.

## 2. Label and protection boundaries

- PROTECT (82): private `.ai/` agent state (77 paths) and `references/`
  foreign pins (README, REFERENCE_REPOS_LOCK.yaml, 3 gitlinks). Verified by Git
  metadata only; content is never read, hashed, delivered, or traversed.
  Protection derives from trusted baseline path/type boundaries (`.ai/`,
  `references/`, mode 160000), never from a manifest label alone.
- RETAIN (362): preserve verified consumers; change only in a named approved task.
- RECONCILE (1447) / RECONCILE_DOCUMENT (293): file-level consumer review or
  authority amendment / historical labeling; no blanket move or removal.
- ARCHIVE_CANDIDATE (194): proposed destination
  `archive/acquisition-2026/<path>` (outside `packages/*` and `services/*`
  workspace globs), each gated on the blocking condition
  “Extract platform consumers; reconcile tests/build/CI; verify historical
  readers before move”.

## 3. Candidate groups — paths, evidence, unresolved conditions

Restore route for every group (planning reference only, not an approved move):
content is retrievable as `git show
72c526ba7b6d423443d9733d1189fccd8b47ada6:<path>`; the inverse of a future
approved move returns the file to its current path and re-binds a fresh
manifest at the then-current revision.

### 3.1 edge/manifold-runtime (71)

C++ tactical edge runtime: headers, sources, tests, tools.

Paths: `edge/manifold-runtime/CMakeLists.txt`, `edge/manifold-runtime/README.md`,
`edge/manifold-runtime/include/ksi/control_plane/command.hpp`,
`edge/manifold-runtime/include/ksi/control_plane/supervisor.hpp`,
`edge/manifold-runtime/include/ksi/edge/activation.hpp`,
`edge/manifold-runtime/include/ksi/edge/artifact_vault.hpp`,
`edge/manifold-runtime/include/ksi/edge/calibrated_projector.hpp`,
`edge/manifold-runtime/include/ksi/edge/capture_quality_policy.hpp`,
`edge/manifold-runtime/include/ksi/edge/core_sync_http.hpp`,
`edge/manifold-runtime/include/ksi/edge/crypto.hpp`,
`edge/manifold-runtime/include/ksi/edge/curl_https_executor.hpp`,
`edge/manifold-runtime/include/ksi/edge/dfine.hpp`,
`edge/manifold-runtime/include/ksi/edge/event_timing.hpp`,
`edge/manifold-runtime/include/ksi/edge/evidence_attestation.hpp`,
`edge/manifold-runtime/include/ksi/edge/evidence_builder.hpp`,
`edge/manifold-runtime/include/ksi/edge/flight_execution.hpp`,
`edge/manifold-runtime/include/ksi/edge/frame_queue.hpp`,
`edge/manifold-runtime/include/ksi/edge/jpeg_dimensions.hpp`,
`edge/manifold-runtime/include/ksi/edge/media_control.hpp`,
`edge/manifold-runtime/include/ksi/edge/media_offload.hpp`,
`edge/manifold-runtime/include/ksi/edge/mission_kmz.hpp`,
`edge/manifold-runtime/include/ksi/edge/pipeline.hpp`,
`edge/manifold-runtime/include/ksi/edge/risk.hpp`,
`edge/manifold-runtime/include/ksi/edge/runtime_profile.hpp`,
`edge/manifold-runtime/include/ksi/edge/shadow.hpp`,
`edge/manifold-runtime/include/ksi/edge/store_forward.hpp`,
`edge/manifold-runtime/include/ksi/edge/sync.hpp`,
`edge/manifold-runtime/include/ksi/edge/telemetry.hpp`,
`edge/manifold-runtime/include/ksi/edge/tensorrt.hpp`,
`edge/manifold-runtime/include/ksi/edge/world_entity.hpp`,
`edge/manifold-runtime/src/activation.cpp`,
`edge/manifold-runtime/src/artifact_vault.cpp`,
`edge/manifold-runtime/src/calibrated_projector.cpp`,
`edge/manifold-runtime/src/capture_quality_policy.cpp`,
`edge/manifold-runtime/src/command.cpp`,
`edge/manifold-runtime/src/core_sync_http.cpp`,
`edge/manifold-runtime/src/crypto.cpp`,
`edge/manifold-runtime/src/curl_https_executor.cpp`,
`edge/manifold-runtime/src/dfine.cpp`,
`edge/manifold-runtime/src/event_timing.cpp`,
`edge/manifold-runtime/src/evidence_attestation.cpp`,
`edge/manifold-runtime/src/evidence_builder.cpp`,
`edge/manifold-runtime/src/flight_execution.cpp`,
`edge/manifold-runtime/src/frame_queue.cpp`,
`edge/manifold-runtime/src/jpeg_dimensions.cpp`,
`edge/manifold-runtime/src/media_control.cpp`,
`edge/manifold-runtime/src/media_offload.cpp`,
`edge/manifold-runtime/src/mission_kmz.cpp`,
`edge/manifold-runtime/src/pipeline.cpp`,
`edge/manifold-runtime/src/risk.cpp`,
`edge/manifold-runtime/src/runtime_profile.cpp`,
`edge/manifold-runtime/src/shadow.cpp`,
`edge/manifold-runtime/src/store_forward.cpp`,
`edge/manifold-runtime/src/supervisor.cpp`, `edge/manifold-runtime/src/sync.cpp`,
`edge/manifold-runtime/src/telemetry.cpp`, `edge/manifold-runtime/src/tensorrt.cpp`,
`edge/manifold-runtime/src/world_entity.cpp`,
`edge/manifold-runtime/tests/capture_quality_policy_tests.cpp`,
`edge/manifold-runtime/tests/conformance_tests.cpp`,
`edge/manifold-runtime/tests/control_plane_tests.cpp`,
`edge/manifold-runtime/tests/edge_runtime_tests.cpp`,
`edge/manifold-runtime/tests/generated/action_intent_vectors.hpp`,
`edge/manifold-runtime/tests/media_control_tests.cpp`,
`edge/manifold-runtime/tests/source_media_schema_migration_test.py`,
`edge/manifold-runtime/tools/ksi_edge_flight_abort.cpp`,
`edge/manifold-runtime/tools/ksi_edge_flight_arm.cpp`,
`edge/manifold-runtime/tools/ksi_edge_media_prepare.cpp`,
`edge/manifold-runtime/tools/ksi_edge_media_trigger.cpp`,
`edge/manifold-runtime/tools/mutation_check.py`,
`edge/manifold-runtime/tools/tensorrt_differential_runner.cpp`.

- Build/CI: `.github/workflows/ci.yml` configures, builds, and ctests
  `edge/manifold-runtime` (including an ASan build).
- Tests: in-tree C++ ctest suites listed above.
- Contracts: none (native code; no wire contract owned here).
- Restore: baseline blob retrieval per path above.
- Unresolved: which historical readers (HIL evidence, field kits) still need
  these binaries/behaviors; CI jobs must be narrowed or retired file-by-file
  before any move; `tools/edge/` helpers referencing this runtime need
  per-file reconciliation.

### 3.2 edge/psdk-tap (29), edge/psdk-app (17), edge/psdk-platform (1), edge/third_party (1)

DJI PSDK tap/app shims, platform glue, and the PSDK pin.

Paths: `edge/psdk-tap/CMakeLists.txt`, `edge/psdk-tap/README.md`,
`edge/psdk-tap/config/app.json.in`, `edge/psdk-tap/config/dji_sdk_app_info.h.example`,
`edge/psdk-tap/include/psdk_tap/clock_util.h`, `edge/psdk-tap/include/psdk_tap/liveview_tap.h`,
`edge/psdk-tap/include/psdk_tap/ndjson_writer.h`, `edge/psdk-tap/include/psdk_tap/pairing.h`,
`edge/psdk-tap/include/psdk_tap/perception_tap.h`, `edge/psdk-tap/include/psdk_tap/shared_state.h`,
`edge/psdk-tap/include/psdk_tap/telemetry_tap.h`, `edge/psdk-tap/src/clock_util.c`,
`edge/psdk-tap/src/liveview_tap.c`, `edge/psdk-tap/src/main.c`,
`edge/psdk-tap/src/ndjson_writer.c`, `edge/psdk-tap/src/pairing.c`,
`edge/psdk-tap/src/perception_tap.c`, `edge/psdk-tap/src/platform/logger_console_glue.c`,
`edge/psdk-tap/src/platform/logger_console_glue.h`, `edge/psdk-tap/src/platform/osal_glue.c`,
`edge/psdk-tap/src/platform/osal_glue.h`, `edge/psdk-tap/src/platform/socket_glue.c`,
`edge/psdk-tap/src/platform/socket_glue.h`, `edge/psdk-tap/src/platform/usb_bulk_glue.c`,
`edge/psdk-tap/src/platform/usb_bulk_glue.h`, `edge/psdk-tap/src/shared_state.c`,
`edge/psdk-tap/src/telemetry_tap.c`, `edge/psdk-tap/tests/ndjson_writer_tests.c`,
`edge/psdk-tap/tests/pairing_tests.c`; `edge/psdk-app/CMakeLists.txt`,
`edge/psdk-app/README.md`, `edge/psdk-app/config/app.json.in`,
`edge/psdk-app/config/dji_sdk_app_info.h.example`,
`edge/psdk-app/src/flight_execution/waypoint_v3_upload_only.cpp`,
`edge/psdk-app/src/flight_execution/waypoint_v3_upload_only.hpp`,
`edge/psdk-app/src/main.cpp`, `edge/psdk-app/src/media/dji_camera_media_source.cpp`,
`edge/psdk-app/src/media/dji_camera_media_source.hpp`,
`edge/psdk-app/src/runtime/psdk_mop_peer_receiver.cpp`,
`edge/psdk-app/src/runtime/psdk_mop_peer_receiver.hpp`,
`edge/psdk-app/src/runtime/psdk_route_companion.cpp`,
`edge/psdk-app/src/runtime/psdk_route_companion.hpp`,
`edge/psdk-app/tests/dji_camera_media_source_tests.cpp`,
`edge/psdk-app/tests/gateway_psdk_companion_interop.py`,
`edge/psdk-app/tests/psdk_mop_peer_receiver_tests.cpp`,
`edge/psdk-app/tests/psdk_route_companion_tests.cpp`;
`edge/psdk-platform/psdk_platform.cmake`; `edge/third_party/PSDK_LOCK.yaml`.

- Build/CI: `ci.yml` `edge-psdk-app-host` job runs `tools/edge/fetch_psdk.py`,
  stages `dji_sdk_app_info.h`, and builds `edge/psdk-app`.
- Consumers: `services/dji-gateway` companion-interop expectations
  (`gateway_psdk_companion_interop.py`); licensed SDK pin in `PSDK_LOCK.yaml`.
- Restore: baseline blob retrieval per path above.
- Unresolved: licensed-vendor boundary (fetch script + lock file need license
  review before any archive copy); companion-interop test ownership after
  gateway extraction.

### 3.3 edge/msdk-field-bridge (2) and edge root files (3)

Paths: `edge/msdk-field-bridge/README.md`,
`edge/msdk-field-bridge/app/src/main/java/com/ksi/fieldbridge/FieldBridgeContract.kt`;
`edge/README.md`, `edge/docker/manifold3-build.Dockerfile`,
`edge/flight-execution-upload-only-allowlist.v1.json`.

- Consumers: dashboard field surfaces reference acquisition readiness
  concepts (`apps/dashboard/src/app/field/acquisition-readiness.ts`,
  `apps/dashboard/src/lib/core-api/types.ts`); Docker build context for the
  manifold image.
- Restore: baseline blob retrieval per path above.
- Unresolved: whether the upload-only allowlist remains a live guard after
  exclusion; Dockerfile ownership (archive is not a build context).

### 3.4 services/dji-gateway (28)

DJI capability/transport adapter service.

Paths: `services/dji-gateway/README.md`, `services/dji-gateway/pyproject.toml`,
`services/dji-gateway/src/ksi_dji_gateway/__init__.py`,
`services/dji-gateway/src/ksi_dji_gateway/adapters/__init__.py`,
`services/dji-gateway/src/ksi_dji_gateway/adapters/catalog.py`,
`services/dji-gateway/src/ksi_dji_gateway/adapters/ports.py`,
`services/dji-gateway/src/ksi_dji_gateway/adapters/transport.py`,
`services/dji-gateway/src/ksi_dji_gateway/coordinator.py`,
`services/dji-gateway/src/ksi_dji_gateway/core_runtime.py`,
`services/dji-gateway/src/ksi_dji_gateway/domain/__init__.py`,
`services/dji-gateway/src/ksi_dji_gateway/domain/capabilities.py`,
`services/dji-gateway/src/ksi_dji_gateway/domain/models.py`,
`services/dji-gateway/src/ksi_dji_gateway/domain/validation.py`,
`services/dji-gateway/src/ksi_dji_gateway/errors.py`,
`services/dji-gateway/src/ksi_dji_gateway/gateway.py`,
`services/dji-gateway/src/ksi_dji_gateway/open_platform_probe.py`,
`services/dji-gateway/src/ksi_dji_gateway/persistence/__init__.py`,
`services/dji-gateway/src/ksi_dji_gateway/persistence/journal.py`,
`services/dji-gateway/src/ksi_dji_gateway/ports/__init__.py`,
`services/dji-gateway/src/ksi_dji_gateway/py.typed`,
`services/dji-gateway/src/ksi_dji_gateway/routing/__init__.py`,
`services/dji-gateway/src/ksi_dji_gateway/routing/capability_router.py`,
`services/dji-gateway/src/ksi_dji_gateway/runner.py`,
`services/dji-gateway/src/ksi_dji_gateway/runtime_observation.py`,
`services/dji-gateway/tests/test_candidate_adapters.py`,
`services/dji-gateway/tests/test_gateway.py`,
`services/dji-gateway/tests/test_open_platform_probe.py`,
`services/dji-gateway/tests/test_runtime_transport.py`.

- Consumers: Core capability/edge-transport code
  (`services/core/src/ksi_core/capability/runtime_api.py`,
  `services/core/src/ksi_core/domains/edge_transport/edge_dispatch.py`,
  `services/core/src/ksi_core/acquisition/models.py`); dashboard core-api
  types and field acquisition-readiness surface.
- Tests: `tests/contract/test_acquisition_connectivity.py`,
  `test_acquisition_coordination.py`, `test_capability_*` suites, in-service
  gateway tests listed above.
- Restore: baseline blob retrieval per path above.
- Unresolved: mixed Core/gateway responsibility (spec §5: Core assembles
  acquisition connectivity/coordination/capture-quality alongside external
  features) must be split by actual dependency before any archive move.

### 3.5 packages/mission-contracts (13), packages/mission-planning (9)

Mission contract/planning libraries with live Core consumers — the sharpest
mixed-responsibility case.

Paths: `packages/mission-contracts/README.md`, `packages/mission-contracts/pyproject.toml`,
`packages/mission-contracts/src/ksi_mission_contracts/__init__.py`,
`packages/mission-contracts/src/ksi_mission_contracts/action_intent.py`,
`packages/mission-contracts/src/ksi_mission_contracts/consumer.py`,
`packages/mission-contracts/src/ksi_mission_contracts/dispatch.py`,
`packages/mission-contracts/src/ksi_mission_contracts/edge_activation.py`,
`packages/mission-contracts/src/ksi_mission_contracts/edge_dispatch_sync.py`,
`packages/mission-contracts/src/ksi_mission_contracts/models.py`,
`packages/mission-contracts/src/ksi_mission_contracts/py.typed`,
`packages/mission-contracts/src/ksi_mission_contracts/risk_policy.py`,
`packages/mission-contracts/src/ksi_mission_contracts/runtime_profile.py`,
`packages/mission-contracts/src/ksi_mission_contracts/signing.py`;
`packages/mission-planning/pyproject.toml`,
`packages/mission-planning/src/ksi_mission_planning/__init__.py`,
`packages/mission-planning/src/ksi_mission_planning/camera.py`,
`packages/mission-planning/src/ksi_mission_planning/coverage.py`,
`packages/mission-planning/src/ksi_mission_planning/geometry.py`,
`packages/mission-planning/src/ksi_mission_planning/py.typed`,
`packages/mission-planning/src/ksi_mission_planning/reobservation.py`,
`packages/mission-planning/src/ksi_mission_planning/terrain.py`,
`packages/mission-planning/src/ksi_mission_planning/wpml.py`.

- Consumers: `services/core/pyproject.toml` depends on `ksi-mission-contracts`,
  `ksi-mission-planning`; consumed by mission issuance/plans, contract
  signing, and route generation
  (`services/core/src/ksi_core/domains/missions/mission_plans.py` and related
  issuance paths).
- Tests/contracts: `tests/contract/test_action_intent_conformance.py`,
  capability-contract suites; `edge/manifold-runtime/tests/generated/action_intent_vectors.hpp`.
- Restore: baseline blob retrieval per path above.
- Unresolved: **these packages have verified platform consumers today** —
  archiving requires extracting or replacing those consumers first (Task 3+
  successor work). A move without consumer closure would break Core imports,
  workspace membership, and dependent contract tests.

### 3.6 packages/perception (13)

Paths: `packages/perception/pyproject.toml`,
`packages/perception/src/ksi_perception/__init__.py`,
`packages/perception/src/ksi_perception/dfine.py`,
`packages/perception/src/ksi_perception/dynamic_object_mask.py`,
`packages/perception/src/ksi_perception/live_view.py`,
`packages/perception/src/ksi_perception/onnx_export.py`,
`packages/perception/src/ksi_perception/onnx_manifest.py`,
`packages/perception/src/ksi_perception/onnx_runtime.py`,
`packages/perception/src/ksi_perception/pipeline.py`,
`packages/perception/src/ksi_perception/py.typed`,
`packages/perception/src/ksi_perception/recorded.py`,
`packages/perception/src/ksi_perception/recorded_pipeline.py`,
`packages/perception/src/ksi_perception/registry.py`.

- Consumers: `services/processing-controller/pyproject.toml` depends on
  `ksi-perception`; used by the managed runner/masking code
  (`services/processing-controller/src/ksi_processing_controller/runner.py`,
  `odm_masking.py`).
- Restore: baseline blob retrieval per path above.
- Unresolved: managed-reconstruction versus external-inspection lane split
  (spec §5) is undecided; ONNX/model artifacts and historical readers need
  per-file disposition before any move.

### 3.7 packages/equipment-intelligence (7)

Paths: `packages/equipment-intelligence/pyproject.toml`,
`packages/equipment-intelligence/src/ksi_equipment_intelligence/__init__.py`,
`packages/equipment-intelligence/src/ksi_equipment_intelligence/cpa_ttc.py`,
`packages/equipment-intelligence/src/ksi_equipment_intelligence/kinematic_state.py`,
`packages/equipment-intelligence/src/ksi_equipment_intelligence/py.typed`,
`packages/equipment-intelligence/src/ksi_equipment_intelligence/reobservation_signal.py`,
`packages/equipment-intelligence/src/ksi_equipment_intelligence/risk_field.py`.

- Consumers: `services/core/pyproject.toml` depends on
  `ksi-equipment-intelligence`; consumed by equipment-state observation code
  (`services/core/src/ksi_core/domains/observations/equipment_states.py`,
  `events.py`).
- Restore: baseline blob retrieval per path above.
- Unresolved: same mixed-consumer situation as §3.5 — live Core dependency
  must be extracted or replaced before any archive move.

## 4. Verification evidence

- `.venv/bin/python -m pytest tests/contract/test_physical_site_disposition.py -q` → 7 passed.
- `python tools/check_physical_site_disposition.py --manifest
  docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv` → exit 0
  (2378 unique rows bound to frozen objects).
- Hostile copy exercise (single digest mutated in a `/tmp` copy, real CSV
  untouched): exit 1 with a safe path/reason finding, no moves.
- `git diff --check` clean; `ruff check` and `ruff format --check` clean on
  both new Python files.
- Frozen CSV SHA256 unchanged:
  `89a9baf3b1f1a593bf65af02810595cea0f677a740ceb0fdf9f2e789071639e3`.
