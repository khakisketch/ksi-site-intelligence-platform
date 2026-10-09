# Site 기록 하네스 매핑 (1회 정리) — 2026-10-09

- Status: 1회 매핑 기록. 기존 계획·원장·Spec·PRD의 문구를 재작성하지 않으며 실행 권한을 만들지 않는다.
- Date: 2026-10-09
- 기준 정책: `/home/ksi/.config/opencode/AGENTS.md` (전역 하네스 정책). 이 기록 작성 시점 SHA256
  `072781ed65c0f69c53a82404e1103ed64519975e314fc7881e49e5da6d115fe2`.
- 범위: `docs/superpowers/plans/*.md`(73건), `docs/superpowers/product-state.md`,
  `.opencode/working-state.md`, 루트/앱/프로토타입 `AGENTS.md`.
- 정본 유지: 새 기록도 `docs/superpowers/plans/`를 쓴다. `docs/plans`, `.compound-engineering/`은 만들지 않는다.

## 구 → 신 매핑

| 구 하네스 표현 | 현행 해석 |
| --- | --- |
| `writing-plans` 등 계획 작성 레시피 필수 | 계획은 native Plan이 담당한다. CE/스킬은 그 결과물에 도움이 될 때만 쓰며, 계획 승인은 실행 권한이 아니다. 범위·보안·외부효과 gate는 유지된다. |
| Developer / Test Runner 좌석 위임·고정 실행 시퀀스 | 실행·검증·통합은 Build가 소유한다. 필요할 때만 범위를 정해 위임한다. 독립 검증은 fresh-context reviewer로 선택 수행하며 수용 권한이 아니다. 퇴역 좌석은 재가동하지 않는다. |
| 작성자→리뷰어→검증자 전체 재실행의 중복 검증 체인 | 같은 revision의 유효한 증거는 재사용하고, 수정 후 영향 범위만 다시 확인한다. 의무적 중복 체인은 없다. |
| Goal mode·auto-continuation·Goal `active` | goal 플러그인은 제거됐다(2026-10-09). 기존 Goal 레코드의 `active`는 inert 기록이며 pause·재개·자동 계속을 만들지 않는다. 장기 상태는 PRD/원장/product-state/checkpoint/Git이 소유한다. |
| 실행 방법·방향 옵션을 사용자에게 선택 요구 | Plan이 근거로 판단한다. 되돌릴 수 있는 세부는 스스로 정하고, 중대한 범위·설계·보안·데이터·비용·권리 결정과 실제 접근 차단만 사용자에게 요청한다. |

## 인벤토리 (수정하지 않음)

`docs/superpowers/plans/*.md` 73건 스캔, 키워드 후보 39건. 아래 위치는 **당시 기록·템플릿**이며
현행 실행 지시가 아니다.

### 계획 레시피 언급 (2건/3줄)

- `2026-10-06-spatial-data-product-continuation.md:296` — "only after approval invoke writing-plans …"
- `2026-10-07-agent-first-platform-rebaseline.md:34` — "Use writing-plans; self-review …"
- `2026-10-07-agent-first-platform-rebaseline.md:2189` — "`writing-plans` produced the P7 … proposal"

### Developer / Test Runner 언급 (21건/139줄)

2026-10-07-agent-first-platform-rebaseline.md(50), 2026-10-06-spatial-data-product-continuation.md(37),
2026-10-04-external-runtime-application-bundle.md(7), 2026-10-06-consumer-hardening.md(5),
2026-09-19-a2h-flow-supported-verification.md(4), 2026-10-05-v2-customer-http-flow.md(4),
2026-10-06-spatial-data-mcp-v1.md(4), 2026-10-06-first-customer-completion.md(3),
2026-10-07-physical-site-rebaseline-foundation.md(3), 2026-10-09-isolated-fresh-platform-verification.md(3),
2026-08-18-m4d-flight-file-fidelity.md(2), 2026-09-17-dashboard-experience-improvements.md(2),
2026-09-17-single-volume-sv3b.md(2), 2026-09-18-single-volume-sv4.md(2),
2026-10-07-platform-core-assembly.md(2), 2026-10-08-acquisition-separation-and-archive.md(2),
2026-10-08-physical-site-rebaseline-integrated-verification-p5.md(2),
2026-10-09-platform-only-default-deployment-template.md(2), 2026-09-17-single-volume-sv2.md(1),
2026-09-22-analysis-mcp.md(1), 2026-10-08-operations-console-cleanup-p4.md(1)

### Goal·자동 계속 언급 (6건/7줄)

- `2026-09-28-first-product-completion-roadmap.md:7` — "처음 실행할 순서"는 자동 재개 지시가 아님(이미 경계 문구).
- `2026-09-30-spatial-data-platform-roadmap.md:63` — 보류된 개발 자동 재개 방지.
- `2026-10-06-first-customer-completion.md:25` — "goal mode. Historical operations candidate/evidence remain separate …"
- `2026-10-06-spatial-data-product-continuation.md:1343` — "Generic auto-continuation was NOT taken as …"
- `2026-10-07-agent-first-platform-rebaseline.md:96,100` — goal mode 제안/승인 기록.
- `2026-10-08-physical-site-rebaseline-integrated-verification-p5.md:5` — "do not infer approval from … goal mode".

### 실행 방법·방향 선택 언급 (29건/42줄)

- 템플릿 헤더(line 3)만 있는 계획 18건 — 실행 방법 선택 안내(`subagent-driven-development`/`executing-plans` 등).
- 그 외 실질 위치 19곳: `2026-08-15-aol-1-mapping-autonomy.md:21`,
  `2026-08-15-aol-2-reobservation-depth.md:24`, `2026-08-15-aol3-unit1-terrain-altitude-planner.md:23`,
  `2026-08-17-unblocked-hardening.md:852`, `2026-09-30-spatial-data-delivery-v1.md:9,194,200`,
  `2026-10-06-spatial-data-mcp-v1.md:38`, `2026-10-06-spatial-data-product-continuation.md:351`,
  `2026-10-07-agent-first-platform-rebaseline.md:35,114,157,557,1925,2220,2242`,
  `2026-10-07-physical-site-rebaseline-foundation.md:22`,
  `2026-10-09-isolated-fresh-platform-verification.md:178`,
  `2026-10-09-platform-only-default-deployment-template.md:164`

### product-state / checkpoint / AGENTS

- `product-state.md` Next slices: 구 하네스 표현 없음(마커·out-of-product 표기 유지). Goal 섹션의
  P7/Goal 기록만 아래처럼 보완한다.
- `.opencode/working-state.md`: HEAD·상태가 P7 진행 중으로 stale → 현행 재작성(커밋하지 않음).
- 루트 `AGENTS.md`: 전역 정책과 충돌 없음 → 이 매핑 포인터 문장 1개만 추가.
- `apps/dashboard/AGENTS.md`: Next.js 자동 생성 블록 + 상위 포인터 → 변경 없음.
- `design/ksi-operations-console-a-prototype/AGENTS.md`: 구 호스트(ChatGPT Work Mode/Codex Desktop·
  sites-preview) 안내 → 상단 하네스 주석 추가, 본문은 역사로 보존.

## 적용한 변경 (2026-10-09)

- 신규: 이 매핑 ledger 1건.
- `docs/superpowers/product-state.md`: Goal 섹션 끝에 P7 결과 접수/상태 + Goal inert + 이 매핑 포인터를
  dated 블록으로 추가. Milestones/Current slice/Next slices 섹션은 무변경(해시 고정 검사 유지).
- `.opencode/working-state.md`: 현행 재작성(미커밋 checkpoint).
- 루트·프로토타입 `AGENTS.md`: 위 항목의 최소 주석.
- 같은 날 만료된 P7 trial의 owned 컨테이너/네트워크 정리와 Task3 blocked 상태는 부모 원장에
  기록했다(볼륨/이미지/증거 보존).

## 경계

- 기존 계획·원장·Spec·PRD 문구는 재작성하지 않는다. 이 매핑은 설치·배포·push·실행 권한이 아니다.
- P7-A2는 미승인 상태다. Goal `active`는 inert이며 플러그인 없이 pause할 수 없다 — 상태 전이는
  문서 기록으로만 한다.
