# KSI Site Intelligence Agent Instructions

KSI connects physical-site observations to reusable spatial data and evidence-based analysis. Customers own original data and reconstruction execution; KSI owns registration, inspection, permitted use, and evidence for submitted derived outputs. Flight, autonomous acquisition, tactical control, and customer production reconstruction are outside current product responsibility (ADR-KSI-036/038/039).

## Start here

- Product identity, authority order, and supersessions: [`docs/00_READ_FIRST.md`](docs/00_READ_FIRST.md).
- Current repository ownership/runtime map: [`REPOSITORY_STRUCTURE.md`](REPOSITORY_STRUCTURE.md).
- Active vs historical document routing: [`docs/DOCUMENT_STATUS.md`](docs/DOCUMENT_STATUS.md).
- Current bounded work: check `.opencode/working-state.md` when present; otherwise use [`docs/ledger/CURRENT.md`](docs/ledger/CURRENT.md) and its explicitly named work ledger.
- Product slice, only when no active bounded task exists: [`docs/superpowers/product-state.md`](docs/superpowers/product-state.md) and its named slice ledger.
- Console direction: [`docs/design/CONSOLE_CURRENT_SPEC.md`](docs/design/CONSOLE_CURRENT_SPEC.md).

Read only the relevant owner README, contract, entrypoint, and tests for the task. Revalidate Git and source-bound evidence; cached memory and historical plans are not authority. Do not duplicate current status across documents.

## Rules

- Follow the product authority precedence in `docs/00_READ_FIRST.md`; supporting designs, ledgers, and prototypes cannot change product decisions or acceptance.
- Enforce affected invariants in `docs/product/DOMAIN_INVARIANTS.md` and contracts. Accepted direction alone does not authorize an endpoint, runtime permission, deployment, or product acceptance.
- `REPOSITORY_STRUCTURE.md` owns current source/runtime responsibility; independently operated lifecycles belong in `services/`, import-only reusable code in `packages/`.
- Preserve `docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`. Do not import runtime code from `references/` or modify reference repositories unless the task explicitly says `UPDATE_REFERENCE_PIN`.
- Treat `archive/acquisition-2026/`, `.ksi/`, retired harness records, and dated plans as historical unless current authority explicitly selects them. Do not restore retired roles, routes, or workflows.
- Do not claim accuracy, settlement suitability, vendor/field support, deployment, or customer acceptance from registration, RTK FIX, mocks, imports, or software tests alone. Keep unknowns explicit; use contract/replay tests and real-device/HIL gates where applicable.
- Never let an LLM emit executable flight coordinates or bypass safety policy. Retained historical control boundaries remain in their accepted contracts; they do not activate those routes.

## 은퇴 상태와 에이전트 파일 처리

- KSI-managed 재구성 발급·실행은 은퇴했다. 새 managed ProcessingJob을 발행·전이·lease·등록하지 않으며, NodeODM 워커 체인도 없다. 역사 재구성 기록은 읽기 전용 replay·조회로만 다룬다. 봉인된 역사 profile binding 1건(`ksi-odm-civil-v1`)은 `services/core/src/ksi_core/domains/processing/historical_processing_profiles.py`가 소유하고, 미등록·변조 binding은 replay가 fail-closed로 거부한다.
- 에이전트 파일 처리 규칙: 공간 파일은 `services/spatial-data-mcp`의 `fileReference`(인가된 receipt에서만 파생된 `spatial-data-file-reference.v1` 기술자)로 참조한다. 창 읽기는 `services/processing-controller/src/ksi_processing_controller/spatial_data_worker.py`의 native-window 요청(`plan_external_native_window`)과 `packages/geo-spatial/src/ksi_geo_spatial/external_native_window.py`의 픽셀 상한·창 읽기(`max_output_pixels`·`max_output_bytes`·envelope 한도)를 통해서만 수행한다. 모델에는 권한 있는 자산 참조·작업 ID·한도 있는 메타데이터/통계·근거만 반환한다. 전체 GeoTIFF·전체 픽셀 배열·base64 본문을 도구 응답이나 프롬프트에 넣지 않는다. 실제 파일 접근은 현장/조직 권한·허용 용도·자원 한도·감사를 유지하는 워커가 수행한다.
