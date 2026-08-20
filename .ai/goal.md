# Current goal (2026-08-20, closed-loop MVP)

건설현장의 반복 관측을 `오늘 작업 → 사람 승인 → 무파일 수집 →
결정적 변화·공정·상대 물량 계산 → 근거형 Copilot → 재관측 사람 승인`으로
닫는 KSI Site Intelligence MVP의 소프트웨어 기반을 만든다. DJI의 기본 비행
UI를 복제하는 대신 Cloud/Pilot 2를 우선 연결하고, Manifold 3는 비행 중
촬영 품질 보충과 offline store-and-forward에만 쓴다.

이 마일스톤은 REQ-WRK-101, REQ-ACQ-101/102, REQ-INT-101,
REQ-COP-101/102, REQ-SEC-101, REQ-UX-101과 INV-060/061을 추가하고 다음을
구현한다.

- 조직 범위의 일정·Observation Work Order·재관측 초안·내구성 승인
- 실기 capability 증거 전에는 열리지 않는 provider-neutral DJI Gateway
- 서명 Mission/Capture Policy 범위 안의 Manifold 촬영 품질 행동 허용기
- typed read tools와 근거 ID만 쓰고 재관측 초안만 만드는 Copilot
- 현장 사용자에게 파일·KMZ·기술 ID를 숨긴 5단계 `오늘 작업` UX

완료 경계는 소프트웨어다. 실제 DJI Cloud/PSDK adapter, 자동 media 회수,
실제 LLM provider, 생산 조직 데이터 마이그레이션, HIL·FIELD 증거는 없다.
따라서 zero-touch·active acquisition·현장 완료를 주장하지 않는다.

---

# Previous milestone goal (2026-08-20)

FIELD-0a의 확인된 A-file import와 M4D WideCamera 원본 사진 증거를 보존하면서,
Pilot-export KMZ 대조는 공식 FIELD-0a 완료 전제로 남긴다. 운영자가 수용한 이 잔여
리스크는 FIELD-0b HIL 준비를 더 이상 막지 않는다. 현재 milestone은 Manifold 3에서
capture-only DPK 배포 경로와 PSDK 읽기 경로를 안전하게 실증할 준비를 끝내는 것이다.
HIL·FIELD 증거와 프로덕션 writer 활성화는 계속 별도 상태로 둔다.

구현 범위:

- CRITICAL 기계 증거의 Ed25519 artifact attestation 및 operator-provisioned device key registry
- 활성 dispatch의 mission/device/risk policy/calibration/RiskField lineage 대조
- Manifold `EdgePipeline → StoreForwardSyncDriver → CoreRestSyncTransport` 상시 sync와 외부
  0600 개인키 기반 정적 OpenSSL 서명
- Mission Contract v1.3 `issuance={issuerId,siteSequence,issuedAt}`, durable high-water,
  v1.2/v1.3 dual-reader 및 v1.3 이후 rollback/downgrade 거부
- 파일별 captureTime, ProcessingJob 불변 captureWindow, `capturedTo` 전용 freshness,
  site detail 중첩 공간모델 요약과 Dashboard 소비자 전환

명시적 차단/보류: FIELD-0a Pilot-export KMZ(수용 리스크로 기록하되 목표는
`in_progress`), 실제 device key provisioning, Manifold DPK/USB/frame-telemetry HIL,
v1.3 writer 활성화, FIELD-1/2, Core DTM→WPML 지형추종, 프로덕션 배포 및 Git
commit/push. 외부 0600 개인키·DJI App credential·Core token은 운영자가 보안 경로에만
두며, 네트워크 복구 전에는 장비 쓰기를 시도하지 않는다.

---

# Historical goal

현재 작업 트리의 Dashboard 후속 변경을 안전하게 통합하고, 현장 운용을 차단하는 세
항목(Mission Contract 소비자 검증, CRITICAL RiskField 실증거 검증, IFC mm
georeference 이중 배율)을 코드·계약 테스트·원장 증거로 닫는다.

## Scope

- 기존 Dashboard/DSM 테스트 변경의 충돌·중복 검토와 전체 게이트
- Manifold에서 실행 전 Mission Contract 서명·digest·schema·TTL을 fail-closed 검증하는
  구체적 소비자 및 활성화 기록
- CRITICAL 확정 전 등록된 RiskField artifact의 실존, 스토리지 바이트, 계약 내용,
  event 시점·entity 연계를 확인하는 Core 게이트
- IFC mm + georeference의 단위 이중 적용 수정과 설계면 변환 소비자 회귀
- H3/H4 장비 접근 가능성 확인 및 실증거/미검증 상태의 정직한 기록

## Out of scope

- 검증되지 않은 비행·배터리·RTH·카메라·DJI 제어 기능의 지원 승격
- RiskField 3D geometry 합성 정책 자체의 신규 제품 결정
- H2 Cellular Dongle 2/유심 조달
- 프로덕션 배포, Git commit/push/tag/release

## Domain invariants

- INV-011: 계약 활성화 전에 구조·서명·digest·schemaVersion·TTL을 함께 검증한다.
- INV-020: IFC 프로젝트 단위와 map CRS 단위를 섞거나 이중 환산하지 않는다.
- INV-021: 실제 RiskField 증거가 event 시점과 entity를 뒷받침할 때만 CRITICAL 확정을 허용한다.
- INV-010/040/041/050/052: 기존 완료 근거·mock 금지·지원 단계·반출·임무 발급 게이트를 보존한다.
