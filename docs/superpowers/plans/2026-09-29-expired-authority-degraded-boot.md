# FPC-15A — 만료된 외부 권위의 차단 기동

**Plan ID:** FPC-15A-20260929. **상태:** Task A 로컬 검증 완료; FPC-15 전체/EXT-VAL slice 수용 상태는 변경하지 않는다. **Spec:** [FPC-15](2026-09-28-first-product-completion-roadmap.md), [EXT-VAL owner decision](2026-09-07-external-artifact-validation.md), [운영 runbook §3a](../../ops/DEV_EXTERNAL_RUNBOOK.md). **Goal:** 유효했던 서명 스냅샷이 재시작 시점에 만료돼도 Core의 무관한 경로는 기동하고, 외부 정량 경로는 새 유효 권위가 적용될 때까지 차단한다.

**Architecture:** 서명·조직·스키마·키·receipt-history 확인과 현재 시각의 업무 권위 확인을 분리한다. 오직 서명이 검증된 과거 스냅샷의 만료만 차단 기동 대상으로 허용한다. 기존 외부 journal과 정책 replay를 보존할 수 있도록 동일한 외부 그래프를 조립하되, 만료 후보를 현재 권위로 publish하거나 재조정·receipt append 하지 않는다. 관리자 reload는 기존 유효 권위 검증과 원자적 reconcile 경로를 그대로 사용한다.

**Tech stack:** Core FastAPI, 서명된 authority bundle, durable journals, pytest. 새 의존성 없음.

| 필수 항목 | 결정 |
| --- | --- |
| Requirement IDs | FPC-15, EXT-VAL-01/04/08, INV-053/060: 불확실한 정량 사용 차단, 조직 격리, 과거 결과 불변. |
| Owner module | `services/core/src/ksi_core/domains/external/authority/`의 provider loader/lifecycle 및 workflow config, `services/core/src/ksi_core/composition/production.py`. |
| Acceptance criteria | 만료 전 정상 기동; 스냅샷만 만료된 후 재시작에서 `/ready` 200, `/ready/external-authority` 503/BLOCKED, 외부 분석·권위 참가자 사용 차단; 기존 외부 journal/policy/result replay 보존; 새 유효 서명 bundle의 reload로 복구. 서명 위조·조직 불일치·미래 스냅샷·unsafe 파일·키 부적합·receipt history 불일치는 계속 전체 기동 실패. |
| Contracts affected | wire schema 변경 없음. Provider 상태와 admin reload의 기존 BLOCKED/PROVIDER_CONFIGURED 계약 재사용. |
| Reference assets | `tests/contract/test_external_authority_production_integration.py`, provider/production/workflow config tests, replay tests. Reference repos 불사용. |
| Adoption decisions | REUSE 현재 Core 구성·서명 검증·receipt replay·admin reload. 만료 시에만 historical-validation + blocked-live 상태 도입; 예외를 잡아 external workflow를 생략하는 fallback 금지. |
| Files to change | Provider loader/lifecycle, workflow config의 만료 시 historical binding 경계, production wiring, 전용 contract/replay tests. 범위 외 API/계산 변경 금지. |
| Tests | 실제 서명 fixture에서 만료 전/후·재시작·reload, 과거 정책/result replay, 무관한 Core 경로, invalid input fail-closed; focused suite + Ruff + diff-check. |
| HIL or real-device assumptions | 없음. 합성 서명·DSM과 로컬 Core 시험은 현장/운영 호스트 수용 근거가 아니다. |
| License/data implications | 신규 의존성·고객 자료·자격증명 변경 없음. |
| Rollback | 이 task의 생산 코드·테스트 diff만 역적용; durable journal 변환 없음. |

## Task A — 차단 기동과 복구의 생산 경계

- [x] 기존 생산 fixture로 만료 시 기동 실패를 RED로 재현한다. 만료 전 정상 경로, 만료 후 재시작의 Core readiness/외부 차단, 기존 정책 journal replay, 새 서명 bundle reload를 시험에 명시한다.
- [x] 서명 스냅샷 검증에 별도 역사 시각과 현재 시각 게이트를 둔다. 과거의 실제 유효 구간에서 서명·키·조직·내용을 검증하되 미래 발급, 기한 자체가 잘못된 bundle, invalid signature 등은 거부한다. 현재 만료 시 live resolve/currentness는 항상 실패한다.
- [x] workflow catalog는 만료 기동에서만 동일한 검증된 snapshot/record에 결속해 조립한다. 과거 시간으로 현재 권위를 위장하거나 일반 config 오류를 만료로 처리하지 않는다.
- [x] provider attach는 만료 후보를 publish/reconcile/receipt append 하지 않은 채 BLOCKED로 연결하고, 관리 reload가 유효한 새 bundle을 검증·reconcile·publish하도록 한다. 기존 durable 이력과 무관한 Core 경로를 유지한다.
- [x] malformed/forged/mismatched key 또는 조직, 잘못된 역사, 만료 후 외부 분석, reload 실패·성공, 동시 currentness 경계의 회귀 검증을 한다.

검토 초점: 과거 권위를 현재 권위로 노출, 외부 journal 생략으로 replay 실패, 무검증 catch-all degrade, reload 중 stale generation 사용, rollback/receipt 불변성. 의미·권한·replay 위험이 있어 writer idle 이후 별도 reviewer가 정확한 diff를 검토한다. 커밋·PR·배포·고객 자료·자격증명 변경 없음.


## Task A 로컬 근거 — 2026-09-29

실제 서명 fixture의 만료 시작 실패를 RED로 확인했다. 수정 후 만료 재시작에서 Core `/ready` 200, 외부 readiness 503/BLOCKED, live catalog resolve 거절, receipt 불변을 확인했고 서명된 후속 스냅샷 reload로 복구했다. 앱 연결 직전 snapshot·key 전체 시간 조건을 다시 검사해 key 만료와 clock rollback 시 receipt를 추가하지 않는다. 기존 서명 기반 정량 수명주기 fixture는 정책, 결정, 단일·상대 물량 보고서의 ID/digest를 만료 재시작 후에도 조회하고 모든 관련 journal 바이트가 변하지 않음을 검사한다.

첫 독립 검토는 연결 시 key 만료 재검사 누락과 실제 이력 재생 증거 부족으로 `CHANGES_REQUIRED`였다. 두 항목 보완 후 고정 8파일 diff 재검토는 **PASS**였고 해시 대조 후 현재 작업본에 통합했다. 통합된 집중 provider/workflow/quantitative/replay **89 passed**, Ruff·`git diff --check` 통과(기존 pytest 임시 디렉터리 정리 경고 12건). 이 작업은 서명 스냅샷 만료의 소프트웨어 경로만 닫는다. 스냅샷 유효 중 catalog 권위만 만료되는 경로는 여전히 시작 실패이며, FPC-15의 별도 후속 범위다. 운영 호스트·고객/현장 수용 증거도 아니다.

## Task B — 스냅샷이 유효한 동안 카탈로그 승인만 만료된 기동

**Task ID:** FPC-15B-20260929. **상태:** 로컬 검증 완료. **Owner:** 같은 Core authority/workflow/production 작업 경계. **Dependency:** Task A의 서명·과거 결속·live currentness 분리. **Acceptance:** 실제 서명 fixture에서 snapshot/key는 현재 유효하고 catalog authority record만 과거에 만료된 재시작에서 Core `/ready`는 200, 기존 외부 그래프·이력은 재생, 해당 정량 catalog의 live 승인/발행은 차단된다. 이때 `/ready/external-authority`는 유효한 snapshot provider의 상태만 보고하므로 `PROVIDER_CONFIGURED`일 수 있다. 입력 불일치·위조·미래 효력은 지금처럼 기동을 거절한다. 새 catalog record는 digest가 바뀌므로 갱신된 서명 snapshot과 catalog config를 함께 설치한 뒤 재시작해 복구한다. 기존 mapping의 새 digest 승격은 자동으로 하지 않는다.

**Boundary:** strict catalog resolve가 먼저 성공하면 기존 경로를 그대로 사용한다. 실패했을 때에만 생산 조립은 검증된 provider snapshot의 *정확한* catalog record가 과거에 실제 효력이 있었고 지금은 만료됐다는 증거를 요구해 과거 journal 조립을 허용한다. 이 과거 검사는 currentness/live permission을 제공하지 않는다. 명시적으로 snapshot만 만료됐을 때의 Task A 차단 기동과 달리, 유효한 snapshot provider 자체를 불필요하게 BLOCKED 처리하지 않는다. V2 Analysis의 독립 권위를 만료된 V1 catalog 때문에 강제로 폐쇄하지 않는다.

- [x] 현재 snapshot·만료 catalog fixture로 `CATALOG_AUTHORITY` 생산 기동 실패를 RED로 재현한다. 과거 정량 journal이 있는 재시작과 불변성, 현재 catalog resolve/admission 거절, 새 record/config/snapshot 재시작 복구를 시험한다.
- [x] 생산 config 경로에서만 현재 resolve 우선→만료 이력이 정확히 증명될 때 과거 catalog binding으로 조립하게 한다. signed record·body digest·조직·actor·효력 겹침을 확인한다. 아직 시작하지 않은 record, 기록 불일치, 부적절한 snapshot/key, 일반 config 오류는 허용하지 않는다.
- [x] 현재 정량 작업 차단과 과거 결과 조회가 같은 조립 그래프에서 공존하는지 확인한다. 기존 mapping identity/history는 새 catalog digest로 조용히 승격하지 않는다.
- [x] provider/workflow/production/정량 replay 집중 시험, Ruff, diff-check 후 권한·이력 의미 위험의 독립 검토를 받는다. 운영 runbook에는 catalog만 만료된 기동과 재시작 복구 절차를 실제 검증 결과에 맞춰 수정한다.

**Stop conditions:** 과거 catalog binding을 현재 권한으로 노출해야만 조립 가능하거나, 새 catalog digest로 기존 mapping을 암묵 승격해야만 복구된다면 구현을 멈추고 해당 계약 결손을 기록한다. 커밋·배포·호스트/자격증명 변경 없음.


## Task B 로컬 근거 — 2026-09-29

현재 snapshot/key와 만료 catalog record의 실제 서명 fixture에서 생산 조립의 `CATALOG_AUTHORITY` 실패를 RED로 확인했다. 현재 승인 검사가 먼저 실행되고, 정확히 일치하는 signed 과거 record의 효력 겹침·body digest·조직·actor를 확인한 경우에만 기존 그래프를 재생한다. 만료 record는 live resolve/신규 발행을 허용하지 않는다. 실제 생산 기동 `/ready` 200, snapshot provider `PROVIDER_CONFIGURED`, catalog live resolve 거절을 확인했다.

첫 독립 검토는 새 catalog digest 복구와 기존 mapping/result replay가 다른 fixture라는 증거 공백으로 `CHANGES_REQUIRED`였다. 같은 서명 기반 정량 수명주기에서 old mapping·policy·single/relative report를 유지한 채 catalog만 만료시켜 재시작하고, 새 catalog config와 seq5 signed snapshot을 설치해 다시 재시작하는 경로를 보완했다. 기존 두 mapping의 digest·`execution_policy_ref`는 old authority 그대로이며 신규 발행 불가, 기존 결정·보고서 ID/digest는 조회 가능, 비-receipt journal 바이트 불변, 새 receipt 1건만 추가됨을 확인했다. 독립 재검토 **PASS** 후 고정 해시의 5파일 diff를 통합했다. 통합된 provider/workflow/quantitative/replay **91 passed**, Ruff·`git diff --check` 통과(기존 pytest 임시 디렉터리 정리 경고 12건).

FPC-15의 로컬 소프트웨어 만료 경로 두 가지를 다뤘지만 운영 호스트의 서명 키 교체·카탈로그 배포·장애 복구 절차나 고객 현장 자료로 수용한 것은 아니다. 새 catalog 권위에 맞는 새 mapping 승인도 자동화하지 않는다.
