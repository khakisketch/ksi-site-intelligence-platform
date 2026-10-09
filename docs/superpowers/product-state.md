# Product State - KSI-Site-Intelligence-Platform
Updated: 2026-10-09 (P5 final local evidence/handoff; slice/acceptance unchanged)
## Goal
물리적 현장 관측을 근거형 Site State/Change로 연결하는 Site Intelligence 기반이다.
외부 산출물 등록·검사와 공간데이터·고정 분석의 API·MCP 제공은 현재의 두 재사용 경로다
(ADR-KSI-038/039; 새 일반화 State wire 모델·포맷 지원을 만드는 Goal 변경 아님).
원본은 고객 장비에 두며 고객 소유 재구성 경계(ADR-KSI-036)를 유지한다.
첫 플랫폼 검증 목표는 DSM·정사영상의 외부 구역 데이터 활용 + 기존 주간 토공 분석 사례다.
장기 계획·보완 결정: [SDP-20260930](plans/2026-09-30-spatial-data-platform-roadmap.md).
후속 사용자 지시로 개발을 재개했다. 첫 bounded task는
[SDP-CATALOG-20260930](plans/2026-09-30-spatial-asset-catalog-v1.md)이다. `EXT-VAL` 및 아래
milestone/next-slice 목록의 상태·순서는 변경하지 않았다. 이 개발 재개는 slice close·고객
수용·구현 완료를 뜻하지 않는다.
2026-10-07 [ADR-KSI-039](../architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md):
비행·자율 취득·전술 인지/제어·고객 production 재구성은 장기 제품 책임 밖이며 관련 출처는
유지되는 transitional implementation이다. 아래 Next slices의 취득 전용 항목을 out-of-product로
표기한다. 이 Goal/계획 연결은 slice close·수용·milestone 변경이 아니다.
2026-10-07 Human-assigned bounded cleanup work is recorded in the
[rebaseline ledger](plans/2026-10-07-agent-first-platform-rebaseline.md): authority/inventory/neutral
primitives have local foundation evidence atf12857c (full Python9093passed; broad type gate still
unpassed). The [Core assembly successor](plans/2026-10-07-platform-core-assembly.md) is a written
proposal awaiting review at that dated foundation boundary (subsequent P2 approval/closure below), not new execution authority. This link does not close,
reprioritize or replace the Current slice, EXT-VAL/customer acceptance or historical milestones below.
2026-10-08 P2 platform Core assembly technical closure is recorded in the same ledger
(f7779e9/1bc76b5/6b6fc08/26b3c5d/8aaba33; full Python9145passed with one environment-induced
failure adjudicated by a pre-P2 control; broad mypy109/14 pre-existing open). The
[worker/archive successor](plans/2026-10-08-acquisition-separation-and-archive.md) is a written
proposal awaiting review at that dated P2 boundary (subsequent P3 approval/closure below), not new execution authority. No slice/acceptance/milestone change.
2026-10-08 P3 acquisition separation / worker split / source archive technical closure is recorded
in the same ledger: 194+57 blob-identical moves with inverse records (archive/acquisition-2026),
Core/worker acquisition deps dropped, platform imports zero acquisition code (committed boundary
gates), CI historical route (dispatch-only), lock162→157, full suite5996passed/0failed, whole-P3
review + independent runner receipt green. P4 Console (design-owned) and P5 whole verification
were successor work at that dated boundary. Two post-move field-kit adaptations were later
identified by P5's strict hash gate; originals remain recoverable, not all final destinations
are blob-identical. Real customer/operational acceptance stays external. No slice/acceptance/milestone change.
2026-10-09 P4 Console cleanup is technically closed locally at `7f44d11967e9b31524e7f2bbe0ef466c98ad5aec`:
retired acquisition routes/actions removed, approved Home/Sites/five-tab workspace preserved;
actual auth/reload/denial/error/mobile flows and design-owned rendered review verified. Independent
Dashboard typecheck/lint/build exit0, Vitest762/100 and four-viewport E2E77passed/0failed/15explicit
conditional skips; six unchanged Python/fixture hashes reuse the prior independent6013/30/0 receipt.
Exact evidence/limits and deferred minor cleanup are in the [rebaseline ledger](plans/2026-10-07-agent-first-platform-rebaseline.md)
and `apps/dashboard/p4-cleanup-evidence/verification/`. The [P5 integrated-verification plan](plans/2026-10-08-physical-site-rebaseline-integrated-verification-p5.md)
was subsequently approved by Human for all five tasks; canonical approval/progress lives in the
rebaseline ledger, not its frozen proposal header. Tasks1–3 local evidence is at2686789/c5cca2a/e21e0fe:
actual platform SDK/API49passed, full active Python6045passed/30skipped/98warnings/0failed;
strict archive2adaptation gate and broad mypy109/14 remain failed; fresh dependency/image/CI/host
checks are unverified. Tasks4–5 reconcile routing and independent final evidence; no full RB closure,
goal, product slice/EXT-VAL/customer/operational acceptance or release implied. See
[P5 integrated audit](../audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md).
Optional local analysis/storage remains unavailable. Former P4 loopback3241/8041/9041 is now offline;
matching source-bound P4 evidence is reused, not a claim of a live fresh login/result flow.
2026-10-09 final P5 independent source evidence is received at `a8f6e93`:
full active Python6047passed/30skipped/98warnings/0failed, Ruff0, explicit workflow/example scoped
mypy2clean; broad109errors/14files remains FAILED with no added/removed error diagnostics against
pre-P5 control. Whole-P5+repair-delta source reviews have no required residuals; both earlier failed
runs and their RED→GREEN repairs remain in the [rebaseline ledger](plans/2026-10-07-agent-first-platform-rebaseline.md).
The [integrated audit](../audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md) records RB-01..09
and the full objective checklist: strict2archive gate, mixed NodeODM default, fresh sync/image/CI/host,
F01bootstrap/grants and F02–04permitted data/rights/configuration/realconsumer+host/two-cycle acceptance
are OPEN. This closes only the local verification-report work after its recorded closeout checks,
not whole cleanup/goal/product slice/EXT-VAL/customer/operational acceptance. The
[P6 default-template proposal](plans/2026-10-09-platform-only-default-deployment-template.md) is saved
for Human written review, not executed. Existing volumes/configuration are preserved; no install,
activation, push/deploy or external delivery occurred.
Archive: docs/archive/ksi-legacy-2026/ (retired 2026-09-17; historical goals only)
## Milestones
legacy /tmp/... evidence pointers below are transient and non-durable.
| id | milestone | status | evidence |
| --- | --- | --- | --- |
| phase-0 | Phase 0: Capability & Calibration Foundation (SW) | done | commit bcdad4c2064b6f683544434ba1c36cb5dd04d1a5 / 234 passed·5 skipped / mypy 39 files clean / CI green |
| phase-1 | Phase 1 (PRD §25) | done | commit 33a669a / 401 passed·5 skipped / mypy 53 files / C++ ctest 2/2 / CI green |
| phase-2 | Phase 2 (PRD §25) | done | commit 0a5f80b5b7af8a34b28b7b46bb189d02da46b873 · packages/mission-planning/src/ksi_mission_planning/coverage.py:169-247 |
| phase-3 | Phase 3 (PRD §25) | in_progress | 2026-08-07 |
| phase-4 | Phase 4 (PRD §25) | in_progress | 2026-08-07 |
| phase-5 | Phase 5 (PRD §25) | blocked | 2026-08-06 |
| stage-c | Stage C: Phase 1 계약 골격 + C++17 native-control-plane | done | commit a8f98c7 / CI gates+edge-control-plane success |
| track-a | Track A: DJI Hardware Capability Spike | blocked | 2026-08-14 |
| track-b | Track B: Perception Vertical Slice (실기 입력 전환) | blocked | 2026-08-13 |
| core-ingest | Core Edge-Sync Ingest: EventBundle 멱등 수신·영속 (서버 제품 트랙 1) | done | /tmp/claude-1000/-home-ksi-Desktop-KSI-Projects-KSI-Site-Intelligence-Platform/eb40e46c-9d33-4f4b-8898-a75fd0dc43c2/task |
| audit-actionintent-hardening | ActionIntent 계약 강화 — Track A 실기 배선 전 폐쇄 권장 | done | /tmp/claude-1000/-home-ksi-Desktop-KSI-Projects-KSI-Site-Intelligence-Platform/eb40e46c-9d33-4f4b-8898-a75fd0dc43c2/task |
| audit-pipeline-production-lineage | 파이프라인 placeholder 계보 제거 — RunContext 필수화(INV-040/042) | done | /tmp/claude-1000/-home-ksi-Desktop-KSI-Projects-KSI-Site-Intelligence-Platform/eb40e46c-9d33-4f4b-8898-a75fd0dc43c2/task |
| audit-contract-schema-gates | 계약↔스키마↔구현 대조 게이트 — drift 차단 | done | /tmp/claude-1000/-home-ksi-Desktop-KSI-Projects-KSI-Site-Intelligence-Platform/eb40e46c-9d33-4f4b-8898-a75fd0dc43c2/task |
| audit-gate-integrity | 게이트 무결성 — 조용한 no-op·전량 skip 차단 | done | /tmp/claude-1000/-home-ksi-Desktop-KSI-Projects-KSI-Site-Intelligence-Platform/eb40e46c-9d33-4f4b-8898-a75fd0dc43c2/task |
| audit-signing-key-lifecycle | 서명·키 수명주기 강화(INV-011) | done | /tmp/claude-1000/-home-ksi-Desktop-KSI-Projects-KSI-Site-Intelligence-Platform/eb40e46c-9d33-4f4b-8898-a75fd0dc43c2/task |
| audit-edge-sync-ops-hardening | edge-sync 운영 강화 — 인증 도입과 결합 | done | /tmp/claude-1000/-home-ksi-Desktop-KSI-Projects-KSI-Site-Intelligence-Platform/eb40e46c-9d33-4f4b-8898-a75fd0dc43c2/task |
| mission-geometry-route | S1: AOI 지오메트리 + 커버리지 경로 생성 + WPML/KMZ (ADR-KSI-007 잔여 절반) | done | wf_91465b3f-669 · wf_6fdb4688-fc5 · session eb40e46c 최종반증 transcript · 게이트 998p/5s cache-clean |
| core-domain-query | S2: Core 도메인·조회 계층 — Site 상태머신·Mission 영속·Event 트리아지 API·인증 | done | wf_2cc03bc2-56d journal.jsonl (좁은스코프 최종검토 PASS, findings P3x3) — 선행 wf_5f48c547-246(1차 6유닛)·wf_8068da64-d4e(2차 5유닛) 누적 반 |
| dashboard-mvp | S3: 대시보드 MVP — 홈·이벤트 트리아지·임무·현장 + Wizard | done | .ksi 원장 이 항목의 attempt evidence 2건(1차: 최초 구현+E2E 발급 성공+allowedVolumes 실버그 발견수정, 2차: P1 6건 수정+UNKNOWN_SITE/MISSION_ID_CONF |
| ops-serving-hardening | S4: 운영 표면 — Evidence 미디어 스토리지·retention 집행·서명키 수명주기·journal 회전 | done | concurrent repro: 2x parallel pytest tests/contract/test_repo_hygiene_gate.py tests/contract/test_source_media.py x3 rou |
| dashboard-operator-login | 대시보드 운영자 로그인 — 고정 ADMIN 토큰 프록시 취약점(dashboard-unauthenticated-signing-proxy) 폐쇄 | done | 3차 reviewer 최종 판정(agent a8a15591b8f1296ff, /tmp/claude-1000/-home-ksi-Desktop-KSI-Projects-KSI-Site-Intelligence-Platfor |
| dashboard-wizard-split-baseline-mission | 현장등록 Wizard를 현장등록/baseline임무발급 2단계로 분리 — RBAC 정합(risk dashboard-wizard-rbac-mism | done | 2026-08-05 |
| reconstruction-pipeline | 3D 재구성 파이프라인: 원본 사진 입구 → 처리 작업 → 산출물 계보 (B1~B3, ADR-KSI-012/013) | done | wf_4ff07aea-a49 journal.jsonl; uv run pytest tests/ -q -> 1891 passed/20 skipped/3 xfailed; ruff check . all passed; myp |
| hardening-risk-sweep-2026-08 | Track1 하드닝 스윕 — open risk 6건 소프트웨어 해소 | done | coverage_reports.py, odm.py/odm_assets.py, coverage.py, mission_plans.py — 개별 하위 게이트(hardening-rawdetection-box-typeerro |
| phase2-dynamic-object-masking | PRD §15.2 ④ 동적 객체 마스킹/저가중치 — 재구성 파이프라인 | done | 독립 재현(2026-08-12, session 35c4f4c2): 신규 opendronemap/nodeodm:latest 컨테이너(ksi-nodeodm-verify, NodeODM 2.2.4/ODM 3.5.6) 직접 |
| phase2-change-candidate-revisit | PRD §15.2 ⑤ 변화 후보 영역 추가 시점 수집 | abandoned | 2026-08-07 |
| track-b-psdk-liveview-adapter | Track B — PSDK Live View frame source adapter (Python 쪽, 정적 개발) | done | packages/perception/src/ksi_perception/live_view.py + tests/contract/test_live_view_frame_detector_typed.py(19 passed) — |
| hardening-rawdetection-box-typeerror-leak | stale 재감사 med#4 — RawDetection.box 비시퀀스 TypeError 누출 | done | packages/domain/src/ksi_domain/detection_adapter.py:272-280, tests/contract/test_detection_adapter.py::test_structurally |
| hardening-harness-final-position-rename | stale 재감사 #78 — final_position 오명명 정정 | done | tests/replay/harness.py, tests/replay/test_replay_determinism.py — pytest 137 passed |
| hardening-mutation-resistance-tracking-lost | ledger drift — #52 mutation 저항성 결핍이 별도 추적 없이 증발 | abandoned | 2026-08-07 |
| track-a-manifoldctl-package-subcommand | Track A — manifoldctl package 서브커맨드(DPK 패키징, 정적 개발) | done | hil_raw_logs/SESS-20260803T125616Z-PENDING-SN/01_env_inventory/20260803T125944Z__psdk_discovery.log:36-66(dji_app_ctl -- |
| phase-3-kinematic-risk-field | Phase 3 — Kinematic State/CPA-TTC/EquipmentSupportLevel/RiskField (PRD RISK-001~ | abandoned | packages/domain/src/ksi_domain/capability.py:34-47,105-130(SSOT gate, 강등 항상허용); tests/contract/test_capability_gate.py:2 |
| phase-3-active-reobservation-signal | Phase 3 — Active Reobservation 권고 신호 (PRD RISK-005, control boundary 필수) | done | packages/equipment-intelligence/src/ksi_equipment_intelligence/reobservation_signal.py:32-75 (전체 정독, bool 단일 반환·부작용 0건); |
| phase-4-change-detection | Phase 4 — Point Cloud 변화탐지(C2C, PRD §15.4) | done | services/change-detection/src/ksi_change_detection/point_cloud_diff.py:91-92(cKDTree k=1),97(엄격 > 부등호),55-63+84-90(fail- |
| phase-4-bim-linkage | Phase 4 — BIM/as-designed 연계(IFC georeferencing, PRD §5.1.4) | false_positive_complete | services/bim-integration/src/ksi_bim_integration/ifc_reference_model.py:70-85(has_georeferencing 수정), tests/contract/tes |
| phase-4-defect-model-decision | Phase 4 결함탐지 모델 후보 선택 — docs/models/DEFECT_MODEL_CANDIDATES.md 리서치 완료, 대표자 결정 대기 | abandoned | 2026-08-07 |
| phase-3-kinematic-risk-field-v2 | Phase 3 — Kinematic State/CPA-TTC/RiskField (PRD RISK-001~004, EquipmentSupportL | done | packages/equipment-intelligence/src/ksi_equipment_intelligence/, packages/domain/src/ksi_domain/capability.py:34,105-130 |
| phase-4-bim-linkage-v2 | IFC georeferencing 판정을 IfcCoordinateOperation 상위타입 기준으로 정정 + IFC2X3 typed 거부 | abandoned | 2026-08-07 |
| phase-4-bim-linkage-v3 | Phase 4 — BIM 연계 v3 (IfcCoordinateOperation 상위타입 정정, reviewer 2라운드 REFUTED 수정판) | done | services/bim-integration/src/ksi_bim_integration/ifc_reference_model.py:104-142, tests/contract/test_ifc_reference_model |
| phase2-change-candidate-revisit-v2 | PRD §15.2 ⑤ 변화 후보 영역 추가 시점 수집 권고 신호(순수함수, 소비자 배선은 change-detection 결과 API 신설 후 별 | done | services/change-detection/src/ksi_change_detection/revisit_signal.py + tests/contract/test_revisit_signal.py(21 passed)  |
| phase-4-defect-model-decision-v2 | Phase 4 결함탐지 모델 후보 대표자 결정(2026-08-07 정확도 우선 재조사 반영) | done | docs/models/MODEL_DECISIONS.yaml:56-108(MODEL-P4-001 전체) + docs/models/DEFECT_MODEL_CANDIDATES.md 2026-08-07 갱신 절 |
| phase-4-defect-detection-adapter | Phase 4 표면 결함(균열) 탐지 — DefectCandidate 계약 + MixerCSeg 세그멘테이션 adapter (MODEL-P4-0 | done | tests/contract/test_mixercseg_detector.py(10)+test_defect_model_registry.py(10)+test_defect_postprocess.py(7)+test_defec |
| edge-manifold-runtime-mutation-resistance-review | edge/manifold-runtime mutation 저항성 독립 재점검 (#52 대체) | done | edge/manifold-runtime/tools/mutation_check.py — command.cpp(TTL·인가)·supervisor.cpp(heartbeat·fail-closed 상태전이) 안전 불변식 28 |
| equipment-support-level-runtime-gate | 장비 클래스 지원단계 전이 API — INV-041 런타임 강제 | done | services/core/src/ksi_core/equipment_support.py + tests/contract/test_equipment_support_api.py(50 passed) + tests/contra |
| m1-spatial-epoch-pipeline | M1: epoch 파이프라인 종단 완주 — 바이트 영속→정좌표→체적 리포트→화면 | done | PR #2 merge commit 1419c5f; tests/contract/test_odm_live.py; tests/contract/test_geo_spatial_vertical.py; services/chang |
| adr-016-product-scope | ADR-KSI-016: 제품 범위·공간 아키텍처 확정 + 헌법 우선순위 개정 | done | docs/architecture/ADR-KSI-016-product-scope-and-spatial-architecture.md:1-269(ACCEPTED); docs/product/PRODUCT_CONSTITUTI |
| mesh-multi-file-artifact-persistence | mesh(다중파일) 산출물 저장 지원 — 정사영상이 mesh 를 부모로 등록되려면 mesh 자체가 먼저 등록돼야 한다 | done | /tmp/claude-1000/-home-ksi-Desktop-KSI-Projects-KSI-Site-Intelligence-Platform/0bf7c59f-f6c1-443c-8fa9-376420cd0456/scra |
| m3-core-production-assembly | M3 1단계: Core 프로덕션 조립 경로 — env 기반 설정, dev 토큰 없이 fail-closed | done | 커밋 b1e6cbc(구현+fix), 워크플로 journal /home/ksi/.claude/projects/-home-ksi-Desktop-KSI-Projects-KSI-Site-Intelligence-Platfor |
| m3-source-upload-ui | M3: 사진 업로드·재구성 발행 UI — 대시보드에서 핵심 가치를 직접 실행 | done | apps/dashboard/src/components/missions/SourceUploadPanel.tsx(:106-110 봉인버튼 복원, :154-161+:295-320 폴링 lifecycle 단일화); 실기동: |
| m2-change-detection-submission-ui | M2: 두 시점 비교(change-detection·volume-change) 제출 UI — /reports에 실제 결과가 뜨게 | done | .dev-data/core-m2-e2e/{comparison-requests,change-detection,volume-changes,processing-jobs}.jsonl + requestId mission-m2 |
| m3-processing-worker-runtime | M3: 처리 워커 실행 경로 + 래스터 산출물(정사영상·DSM) 등록 — 발행 버튼이 실제 재구성으로 이어지게 | done | 실기동: site-m3-demo-baseline-2-pj2 (issued 2026-08-10T05:18:42Z, SUCCEEDED 2026-08-10T05:22:16Z, 7 artifacts, gsd=0.1 x3 독 |
| m3-worker-orphaned-lease-recovery | 워커 pull 표면이 lease 만료된 RUNNING 작업(죽은 워커)을 후보에서 누락 — 재구성 도중 크래시 시 그 임무의 재처리가 영구히 막 | done | services/core/src/ksi_core/processing_jobs.py list_pending()(now 파라미터+RUNNING-만료 포함 로직); tests/contract/test_processing_ |
| m3-coverage-device-mission-match | 커버리지 보고 장비-임무 대조 (INV-010 무결성 공백) | done | services/core/src/ksi_core/coverage_reports.py:105,318-333,514-519 + tests/contract/test_coverage_reports.py (49 passed) |
| m3-observability | 관측성 — 구조화 로깅 + 기본 메트릭 | done | commit 6dc8c94 + tests/contract/test_observability.py + reviewer transcript ae0f46a0b4b2374b5 |
| m3-auth-token-expiry-rotation | 실사용자 인증 — 토큰 만료·회전 | done | auth.py/production.py/AUTH_TOKEN_ROTATION.md + tests/contract/test_auth.py,test_production_assembly.py + reviewer transc |
| m3-retention-scheduler | retention 집행 스케줄러 연결 | done | tools/retention_scheduler.py + tests/contract/test_retention_scheduler.py,test_retention.py + reviewer transcript aacb3b |
| m2-closed-loop-revisit-mission | M2 폐루프 — 재촬영 권고에서 임무 발급까지 연결 | done | reports/page.tsx,surveyEntryPreset.ts,surveys/new/page.tsx,SurveyWizard.tsx + test/survey-entry-preset.test.ts + real Co |
| data-residency-wizard-wiring | 현장등록 위저드에 dataResidency(INV-050 반출통제) 선언 입력을 추가 | done | apps/dashboard/src/lib/data-residency.ts, apps/dashboard/test/data-residency.test.ts, SiteRegistrationWizard.tsx, SiteRe |
| elapsed-time-live-wiring | 홈 콜아웃·이벤트상세 경과시간 표시를 실시간 갱신으로 전환(ElapsedTime.tsx 배선) | done | apps/dashboard/src/hooks/useTick.ts, TopUnattendedHeadline.tsx, events/AckElapsedFact.tsx, ElapsedTime.tsx, page.tsx, Ev |
| m4a-design-conformance | M4-A: 설계 기준면 대비 절·성토 잔량 — 두 시점 비교에서 설계 대비 시공 판단으로 | done | reviewer 판정: 4개 기준 전부 CONFIRMED, file:line 근거 — design_surfaces.py:641-695(seal은 스토리지 미판독) / design_surface_verifier.py: |
| m4a-geoid-vertical-bridge | M4-A: 정표고(해발) 설계도면을 지오이드 격자로 자동 정합 — 한국 실무 도면 거부 해소 | done | reviewer 판정: 4개 기준 전부 CONFIRMED + 부호·레거시 승격도 CONFIRMED. file:line — vertical_reference.py:1-386(bridge_between/assert_br |
| m4a-ifc-design-surface-tool | M4-A: IFC 설계도면 → 설계면 GeoTIFF 변환 도구 — 만들어둔 BIM 연계를 실제 경로에 연결 | done | tests/contract/test_convert_ifc_design_surface.py:112,142,173,181,190,206,220,238,266 + tests/contract/test_ifc_referenc |
| ops-deployable-compose | 배포 가능한 구성 — compose · env 예제 · 배포 문서 | done | 1차 reviewer: compose.yaml 명명 볼륨 ↔ DEPLOYMENT.md §2 로컬 디렉터리 단절 REFUTED. 2차 reviewer: compose.yaml:66 바인드 · DEPLOYMENT.md: |
| m4c-work-area-progress | M4-C: 작업구역 + 계획 대비 진척 — 잔여량에서 공정관리로 | done | 5개 완료기준 전부 CONFIRMED, file:line — work_area.py:73-92(polygon 수정 API 없음, supersedes만 존재) / work_areas.py:424-497(POST 등록· |
| wf1-progress-zone-integrity-fix | M4-D 착수 전 필수 수정 — 진척 구역 면적 대조 + 즉석 zones 기하 검증 + CRS 재투영 fail-closed | done | reviewer 1(design_progress area-mismatch): CONFIRMED-FIXED, agentId a1d6595d7a4d273c3 / reviewer 2(즉석 zones 폴리곤 검증): CON |
| m4d-report-export | M4-D 현장 보고서 내보내기 — browser-print | done | 정확성(종이==화면): CONFIRMED-OK / 한계표시(정산 근거 아님+한계 안내): CONFIRMED-OK / 계보(어느 리포트로 냈나): 최초 PARTIAL(인쇄 본문에 식별자 없음, CSV에만 있었음) →  |
| processing-controller-work-dir-cleanup | 처리 워커 디스크 무한 적재 + 무한 재시도 수정 — work_dir 정리 + FAILED 수렴 예외 확대 | done | worker.py(재구성 워커) 수정: CONFIRMED-FIXED — cleanup 위치·예외 확대 범위·runner.py로 이어지는 인과관계(WorkerRunError→ran_but_failed→True)까지 직 |
| m4e-region-extraction | M4-E 변화 영역 자동 추출 + 재관찰 초안 핸드오프 (Core 절반) | done | 4렌즈(결정성/부호·면적손계산/볼록껍질노출/AI없음) 전부 CONFIRMED-OK — 결정성은 4개 독립 프로세스(해시시드 상이)로 스트레스 재현까지 완료, 부호·면적은 volume_delta_in_polygon과  |
| manifold3-edge-shadow-vertical-slice | Manifold 3 Edge Shadow 수직 슬라이스 — 임무 전달·위험판정·저장후전달·C++ 파이프라인 | done | e1118d1(워크트리 커밋), main 병합 커밋. pytest 3107 passed/0 failed, ruff clean, mypy 313 files, C++ CTest 4/4(SQLite 실물, 135/135  |
| autonomous-acquisition-closed-loop | Autonomous Acquisition Closed Loop — 실제 M4D 기준 종단 폐루프 1회 완주 | in_progress | 2026-08-14 |
| site-intelligence-e2e-sw | SITE-INTELLIGENCE-E2E-SW — 사진→NodeODM→설계대비→변화영역→지도→재관측 임무 소프트웨어 폐루프 1회 완주 | done | session:8f74ab75-f35b-4488-81bf-82f6f22b6c09 (이 대화 — 사용자 확인 메시지 2026-08-15) |
| crs-metadata-provenance-mismatch | ProcessingArtifact CRS 메타데이터가 실제 파일과 불일치 — Core 신고값을 실측값으로 강제 | done | tests/contract/test_odm_adapter.py::test_dsm_crs_is_read_from_the_real_file_not_assumed_from_site,test_dsm_crs_falls_bac |
| region-extraction-ux-decision | 변화영역 자동추출 트리거 UX — 설계 대비 계산과 자동 연동 vs 별도 버튼 | done | tests/contract/test_region_extraction_end_to_end.py::test_region_extraction_request_is_auto_chained_after_design_conform |
| site-intelligence-e2e-operator | SITE-INTELLIGENCE-E2E-OPERATOR — 개발자 도구·curl·DB 조작 없이 대시보드 UI만으로 폐루프 완주 | done | worker.log 10:40:25-26 (자동연동 무개입 확인), .dev-data/core/missions.jsonl (신규 Mission 확인), 스크린샷(지도 화면) |
| region-extraction-volume-inconsistency | 변화영역 추출 volume이 설계 대비 잔량 총량과 불일치할 수 있음 — 원인 미확정 | done | 워크플로 wf_70382df0-695 (trace 3건 + 결정론적 pytest 재현, sha256 일치 확인) |
| region-extraction-scope-clarity | 변화영역 추출 scope를 UI/API에서 오해 없이 표현 — ROI와 무관하게 site 전체 대상임을 명시 | done | apps/dashboard/src/components/design/DesignConformancePanel.tsx, apps/dashboard/src/app/sites/[siteId]/changes/page.tsx, |
| aol-1-spatial-model-lifecycle | AOL-1 G1: 공간모델 생애주기 — 현장이 '공간모델 없음/있음/오래됨'을 서버가 판단한다 | in_progress | 2026-08-17 세션 reviewer 반증 보고 + 메인 직접 확인(spatial_model.py:38-44 docstring, SpatialModelView:459-472) |
| aol-1-mission-execution-lifecycle | AOL-1 G2: 임무 실행 생애주기 — 발급 기록에서 끝나지 않고 배포·실행·완료 상태를 갖는다 | done | 2026-08-17 세션 reviewer 반증 보고 — 기준 5개 전부 충족 판정, 근거 file:line 포함 |
| aol-1-capture-auto-ingest | AOL-1 G4: 촬영 → 서버 자동 ingest — 사람 손 사진 업로드 제거 (ADR-KSI-018 P1) | in_progress | 2026-08-31 |
| aol-1-mission-to-aircraft-delivery | AOL-1 G3: 임무를 기체까지 보내는 공식 경로 — 현재는 운영자가 KMZ 를 손으로 옮긴다 | proposed | 2026-08-15 |
| aol-3-terrain-aware-planning | AOL-3 G6: 공간모델 인지 경로계획 — DSM/Point Cloud 를 경로계획 입력으로 (AOL-1 이후에만 착수) | in_progress | 2026-08-15 |
| aol-2-reobservation-planning-depth | AOL-2 G5: 재관측 계획 심화 — 초안 AOI 에서 멈추지 않고 변화 정도에 맞춘 촬영계획까지 | done | 2026-08-20 full Python 3591 passed; Dashboard 419 tests; native SQLite WAL 6/6 |
| field-0-ground-integration | FIELD-0 지상 통합 — 비행 없이 매니폴드·기체·임무파일이 실제로 이어지는지 확인 | proposed | 2026-08-15 |
| field-1-first-mapping-flight | FIELD-1 첫 실제 매핑 비행 — 우리 현장 사진으로 공간모델이 처음 만들어진다 | proposed | 2026-08-15 |
| field-2-reobservation-loop-field | FIELD-2 현장 폐루프 — 1회차 분석이 만든 재관측 임무로 2회차를 실제로 난다 | proposed | 2026-08-15 |
| field-3-terrain-aware-flight | FIELD-3 지형추종 비행 — 웨이포인트마다 다른 고도가 실제 비행파일에 실린다 | proposed | 2026-08-15 |
| decision-psdk-flight-execution-authorization | KSI가 매니폴드를 통해 기체를 직접 실행시키는 것을 허용할 것인가 (FIELD-1 이후 판단) | proposed | 2026-08-16 |
| field-0a-kmz-acceptance | FIELD-0a 비행파일 수용성 + 카메라 실측 — 조종기만 있으면 오늘 할 수 있다 (FIELD-1의 유일한 전제) | in_progress | 2026-08-27 |
| decision-flight-ceiling-reference-split | 법적 비행 상한과 DJI 고도 기준을 어떻게 분리할 것인가 (FIELD-3 전 확정) | proposed | 2026-08-16 |
| flight-execution-c2-s1-upload-only | C2-S1: 임무 업로드만 (Action 없이) — 빌드 자물쇠 1단계 개방 | proposed | 2026-08-16 |
| flight-execution-c2-s2-propellerless-start | C2-S2: 프로펠러 없는 START — 개념적으로 안전하지 않은 단계, 매 진입 대표자 서면 승인 | proposed | 2026-08-16 |
| flight-execution-c2-s3-supervised-flight | C2-S3: 사람 감시 하 실비행 — ADR-KSI-022(수직기준) 완료가 전제, 빌드 자물쇠는 안 늘어난다 | proposed | 2026-08-16 |
| flight-execution-c2-s4-routine-operation | C2-S4: 일상 운용 — arming TTL 을 세션 단위로 완화 | proposed | 2026-08-16 |
| full-system-review-2026-08-16 | 전체 시스템 코드 검토 43건 수정 — 대시보드·Core·엣지C++·안전게이트·스키마 | done | session 1c6e3df2 — reviewer 보고 5건 + 변이 실증 6건 + 전체 스위트 직접 실행 |
| two-epoch-crs-gate | 두 시점 비교(변화·물량)를 실제 사진으로 돌리려면 기준점(GCP)이 필요하다 — 좌표계 정책 결정 | done | reviewer 3차 판정 pass — 근거 8건(upload_source_bundle.py:253-271 지역지문 기준점 반영 · :440-460 봉인상태 선판독 · source_media.py:494-501 두  |
| field-1-ground-control | FIELD-1 조사에 한국 좌표계 기준점(GCP) 부착 — 두 시점 비교의 전제 | proposed | 2026-08-18 |
| repository-normalization-r0-r2 | Repository Normalization R0-R2: SSOT, structure, non-runtime cleanup | false_positive_complete | docs/audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json |
| repository-normalization-r0-r2-audit-correction | Repository Normalization R0-R2 fresh-audit correction and re-verification | done | docs/audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json;tests/contract/test_repository_normalization.py;REPOSITORY_STRUCTURE.m |
| terrain-aware-planning-design-baseline | 지형 인지 정사 관측계획 문서·설계 기준 반영 | done | docs/audit/TERRAIN_AWARE_PLANNING_DESIGN_BASELINE_REVIEW.md |
| terrain-aware-planning-software | 지형 인지 정사 계획·다운로드·사후 증거 소프트웨어 흐름 | proposed | 2026-09-06 |
| terrain-aware-planning-field-acceptance | M4D·Pilot 실제 계획 운용과 관측 품질 수용 | proposed | 2026-09-06 |
| pilot-default-external-reconstruction-release | 고객 원본 보관·외부 재구성 기반 KSI Pilot-default 첫 출시 완성 | in_progress | 2026-09-06 |
| external-reconstruction-contract-v1 | 외부 재구성 제출·관측 매니페스트 계약 검증 | done | docs/audit/EXTERNAL_RECONSTRUCTION_CONTRACT_V1_VERIFICATION.md |
| external-reconstruction-ingress-api-v1 | External reconstruction authenticated registration upload sealing and replay API | done | docs/audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md |
| external-artifact-validation-v1 | 외부 재구성 산출물 파일 검사와 용도별 사용 적합성 판정 | in_progress | 2026-09-07 |
| external-single-volume-v1 | 단일 시점 체적 — 외부 산출물의 단일 시점 적치물 체적 측정·검토·재관측 (SV-1..SV-4) | done | docs/superpowers/plans/2026-09-18-single-volume-sv4.md · 커밋 90c7ec5/89d7533/77a3840 · 리허설 .dev-data/sv4-rehearsal/EVIDENCE.md (machine-local) |
## Current slice
- Name: 외부 재구성 산출물 파일 검사와 용도별 사용 적합성 판정
- Acceptance (user-visible end-to-end): EXT-VAL-01 actual sealed derived bytes format and spatial metadata inspection; EXT-VAL-02 customer declarations separated from measured facts; EXT-VAL-03 versioned Core per-use display comparison height volume decisions with evidence-bound positive and negative paths; EXT-VAL-04 explicit remediation without blanket raw-upload or DSM absence denial; EXT-VAL-05 bounded resources transient retry fencing tenant isolation and restart replay; EXT-VAL-06 mounted Core and processing-controller workflow without managed identity impersonation; EXT-VAL-07 reviewed detailed plan contracts tests independent and integrated verification; EXT-VAL-08 durable docs goal evidence and local versus release acceptance boundaries
- Plan ledger: docs/superpowers/plans/2026-09-07-external-artifact-validation.md
## Next slices
- phase-3: Phase 3 (PRD §25)
- phase-4: Phase 4 (PRD §25) — acquisition-only pieces out-of-product per ADR-KSI-039; spatial/inspection reuse scope retained (not a completion claim)
- phase-5: Phase 5 (PRD §25) — acquisition-only pieces out-of-product per ADR-KSI-039; industry reuse scope retained (not a completion claim)
- track-a: Track A: DJI Hardware Capability Spike — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- track-b: Track B: Perception Vertical Slice (실기 입력 전환) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- autonomous-acquisition-closed-loop: Autonomous Acquisition Closed Loop — 실제 M4D 기준 종단 폐루프 1회 완주 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- aol-1-spatial-model-lifecycle: AOL-1 G1: 공간모델 생애주기 — 현장이 '공간모델 없음/있음/오래됨'을 서버가 판단한다
- aol-1-capture-auto-ingest: AOL-1 G4: 촬영 → 서버 자동 ingest — 사람 손 사진 업로드 제거 (ADR-KSI-018 P1) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- aol-1-mission-to-aircraft-delivery: AOL-1 G3: 임무를 기체까지 보내는 공식 경로 — 현재는 운영자가 KMZ 를 손으로 옮긴다 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- aol-3-terrain-aware-planning: AOL-3 G6: 공간모델 인지 경로계획 — DSM/Point Cloud 를 경로계획 입력으로 (AOL-1 이후에만 착수) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-0-ground-integration: FIELD-0 지상 통합 — 비행 없이 매니폴드·기체·임무파일이 실제로 이어지는지 확인 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-1-first-mapping-flight: FIELD-1 첫 실제 매핑 비행 — 우리 현장 사진으로 공간모델이 처음 만들어진다 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-2-reobservation-loop-field: FIELD-2 현장 폐루프 — 1회차 분석이 만든 재관측 임무로 2회차를 실제로 난다 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-3-terrain-aware-flight: FIELD-3 지형추종 비행 — 웨이포인트마다 다른 고도가 실제 비행파일에 실린다 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- decision-psdk-flight-execution-authorization: KSI가 매니폴드를 통해 기체를 직접 실행시키는 것을 허용할 것인가 (FIELD-1 이후 판단) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-0a-kmz-acceptance: FIELD-0a 비행파일 수용성 + 카메라 실측 — 조종기만 있으면 오늘 할 수 있다 (FIELD-1의 유일한 전제) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- decision-flight-ceiling-reference-split: 법적 비행 상한과 DJI 고도 기준을 어떻게 분리할 것인가 (FIELD-3 전 확정) — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- flight-execution-c2-s1-upload-only: C2-S1: 임무 업로드만 (Action 없이) — 빌드 자물쇠 1단계 개방 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- flight-execution-c2-s2-propellerless-start: C2-S2: 프로펠러 없는 START — 개념적으로 안전하지 않은 단계, 매 진입 대표자 서면 승인 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- flight-execution-c2-s3-supervised-flight: C2-S3: 사람 감시 하 실비행 — ADR-KSI-022(수직기준) 완료가 전제, 빌드 자물쇠는 안 늘어난다 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- flight-execution-c2-s4-routine-operation: C2-S4: 일상 운용 — arming TTL 을 세션 단위로 완화 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- field-1-ground-control: FIELD-1 조사에 한국 좌표계 기준점(GCP) 부착 — 두 시점 비교의 전제 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- terrain-aware-planning-software: 지형 인지 정사 계획·다운로드·사후 증거 소프트웨어 흐름 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- terrain-aware-planning-field-acceptance: M4D·Pilot 실제 계획 운용과 관측 품질 수용 — **out-of-product** per ADR-KSI-039 (planning reference only; never a completion candidate)
- pilot-default-external-reconstruction-release: 고객 원본 보관·외부 재구성 기반 KSI Pilot-default 첫 출시 완성 — open as KSI external derived-result registration, inspection and customer/ops acceptance only; capture/customer engine execution excluded per ADR-KSI-039
## Backlog
- [2026-09-30] 승인된 플랫폼 방향의 데이터 제공·외부 재사용·후속 PC/Mesh/레이어·연동 패키지:
  SDP-01..10과 GAP-01..10은 [단일 계획 원장](plans/2026-09-30-spatial-data-platform-roadmap.md)에서 추적.
  기존 EXT-VAL acceptance에 소급 추가하지 않는다. 카탈로그 개발은 재개됐으며 구역 데이터
  제공은 고객 표본·상세 계약·권리/운영 검증이 필요하다.
- [2026-09-30] SDP-CAT-01의 유한 조회 예산은 256 WorkOrders/Site, 2,048 revisions/request,
  256 submissions/WorkOrder, 128 inspections/subject, 64 retained policies/subject다.
  초과는 명시적 503이다. 실제 고객 이력·부하를 측정해 인덱스/페이지 전략과 한도를
  재설계해야 한다. 첫 로컬 소프트웨어 증거는
  [카탈로그 계획](plans/2026-09-30-spatial-asset-catalog-v1.md)에 기록했다.
- [2026-09-17] Two active compatibility mappings for the same pair/zone/policy make the pair decision report VOLUME_AUTHORITY_UNAVAILABLE (ambiguity); admission should refuse a duplicate active mapping or the decision should name the ambiguity - source(run3) - not blocking
- [2026-09-17] Home never shows an external result briefing when its site is already in the attention area (ADR-025 no-repeat rule); consider external results awaiting review as an attention source - source(run3) - not blocking
- [2026-09-17] External result summary component renders "-0 m³" for zero cut - source(run3 screenshot) - cosmetic
- [2026-09-17] `tests/contract/test_external_runtime_deployment_contract.py::test_private_bus_rejects_hard_link_and_detects_substitution` fails on this workstation (deploy bash helper `private_socket_identity` returns 1 after the hard link is removed); files untouched by recent merges, environment-dependent, not blocking the external slice — reproduce on a clean host before changing the helper
- [2026-09-17] ExternalEvidenceValidationStore replay re-validates old-policy issued events after policy rotation + restart (latent boot hazard) (rehearsal observation; not reproduced — provenance: A2-fix session summary, not EVIDENCE.md) - source(investigation) - not blocking — docs/audit/EXTERNAL_PRODUCT_LOOP_FIXTURE_RUN_2026-09-17.md and docs/superpowers/plans/2026-09-07-external-artifact-validation.md (Execution state section)
  - [2026-09-18] Investigated: not reproduced. In-process boot of a copy of the a2 console root (4 policy rotations v4→v7, 18 authority receipts) replays all 8 validations; history is resolved by digest from the retained policy journal and receipt history, bound before the store replays. Closing this hypothesis at slice triage — docs/superpowers/plans/2026-09-07-external-artifact-validation.md (2026-09-18 boot-hazard section)
- [2026-09-18] Core refuses to boot at all when the external authority snapshot is expired at startup (`provider_loading.py` validity check raises → `build_production_app` fails), whereas expiry at runtime only moves provider status to BLOCKED (`test_status_fails_closed_when_the_current_snapshot_expires`); a restart after the ~2h local snapshot window takes down missions/work orders until a signed snapshot is reissued. Owner decision 2026-09-18: degrade to BLOCKED; needs a degraded-boot spec (two time gates; no-external boot fails policy replay), scheduled after AX-4; runbook §3a meanwhile - source(investigation) - not blocking
- [2026-09-17] Dashboard experience audit (27-capture design review + run2 source work-order next-action finding): 21 work items across state honesty, consistency and mobile ergonomics; verify-first items marked, A5 likely covered by AX-1 — docs/superpowers/plans/2026-09-17-dashboard-experience-improvements.md - source(design-review) - not blocking
- [2026-09-18] Selected-request status line renders raw ISO `issuedAt` ("보고 완료 · 2026-09-15T01:00:00Z") in both external result families; overlaps dashboard date-format SSOT (2026-09-17-dashboard-experience-improvements.md B1) - source(design-review) - not blocking
- [2026-09-18] SV-3b render-lag follow-up: selectedRefRef/selectionGenerationRef mirrors update one render after selectRequest; a reload invoked in the same tick is dropped (fail-closed, retry needed) - source(review) - not blocking
- [2026-09-18] Rehearsal evidence doc M-3: the runA/runB differ-by-design list omits the inspection report digest (measurement/evidence/briefing values identical) - source(review) - not blocking
