# ADR-KSI-023 — RC-first Connected Edge 제품과 기능별 연결 경계

- 상태: ACCEPTED (2026-08-21, 대표자 확정)
- 2026-08-26 대표자 개정: 다섯 integration path의 candidate adapter를 HIL 전에
  구현할 수 있다. 코드 존재와 운영 지원은 분리하며, 정확한 capability evidence와
  별도 feature flag 없이는 production route에 등록하거나 활성화하지 않는다.
- 관련 요구사항: REQ-ACQ-101/102, REQ-WRK-101, REQ-MSN-101,
  REQ-EDGE-101/102, REQ-INT-101, REQ-SEC-101
- 관련 불변식: INV-001/002, INV-010~013, INV-040~042, INV-050/051, INV-060
- 대체 범위: ADR-KSI-004/005/013/017/022의 연결 기본값·provider 단일선택 가정
  (비행 제어·안전·사람 승인 경계는 대체하지 않는다)

> **2026-09-04 경로 정규화(ADR-KSI-033):** D2의 직접 이벤트·미디어와 D5의 Bridge는
> 목표/candidate topology다. 현재 정상 원본 ingress는 SD/저장매체→현장 PC→KSI 웹
> 업로드이며, `EDGE_UPLINK` bounded metadata와 `MEDIA_PULL`/`MEDIA_UPLOAD` 원본
> capability를 서로 추론하지 않는다. 중앙 지속 Liveview 수신은 핵심 제품 경로가 아니다.

## 맥락

Manifold 3를 모든 고객에게 제공하는 이유는 단순 촬영·매핑이 아니라 비행 중
촬영 품질, 로컬 인지, store-and-forward와 향후 승인 범위 안의 재관측이라는 제품
차별성이다. 그러나 Manifold SIM까지 기본값으로 만들면 데이터 회선이 없는 다수
고객에게 제품 성립 조건을 잘못 부과한다.

반대로 RC Plus 2는 Pilot 2 비행 운영과 KSI Cloud 통신의 지상 gateway다. 사람의
KSI 업무 화면은 ADR-KSI-024의 Operations Console이 소유한다. 새 KSI 임무를
발급할 때 RC 인터넷을 요구하면 Wi-Fi를 기본으로 쓰고 RC 4G를 대체·보조 수단으로
쓸 수 있다. 비행 전에 서명·활성화가 끝난 계약은 이후 인터넷 단절로 자동 무효화하면
안 된다(REQ-EDGE-101, INV-012).

핀된 PSDK 3.16 헤더
`edge/third_party/psdk/psdk_lib/include/dji_cloud_api_by_websockt.h`에는
Manifold에서 Pilot 2 WebSocket 채널로 보내는
`DjiCloudApi_SendDataByWebSocket()`만 있다. 반대 방향 수신 API는 이 헤더에 없다.
따라서 Cloud 하향 경로는 문서 추론이 아니라 실장비 HIL로 별도 증명해야 한다.

## 결정

### D1 — 기본 제품은 KSI Site Intelligence Edge다

- 구성은 `Matrice 4D + Manifold 3 + RC Plus 2`다.
- Manifold 3는 로컬 지능을 담당하며 SIM 유무와 무관하게 같은 기능을 제공한다.
- RC Plus 2 인터넷은 **새 Mission 발급 전** 필수다. Wi-Fi가 기본이고 RC 4G는
  대체·보조 transport다.
- 이미 서명·활성화된 Mission Contract는 비행 중 RC 인터넷 단절만으로 중단하거나
  무효화하지 않는다. RC command link loss는 DJI Flight Controller 정책을 따른다.
- Pilot 2가 비행 화면과 이륙·운영을 소유한다.
- RC Plus 2에는 KSI 업무 UI를 표시하지 않는다. RC 인터넷 readiness와 Operations
  Console 사용자 세션은 서로 다른 상태다.

### D2 — Manifold 직접망은 Connectivity Add-on이다

- Manifold SIM이 있으면 Edge 이벤트·선별 미디어·착륙 후 원본 업로드는 직접
  HTTPS를 우선한다.
- 직접망이 없어도 기본 제품은 성립한다. Edge 결과는 검증된 RC/Pilot 경로로
  전달하고, 원본은 유실 없이 queue에 남긴 뒤 착륙 후 동기화한다.
- Add-on entitlement는 전송 경로만 제어하며 Capture Quality Recovery 등 로컬
  지능을 잠그지 않는다.
- 외부에서 Manifold로 들어오는 inbound 포트는 열지 않는다.

### D3 — provider 하나가 아니라 기능별 capability를 선택한다

다음 capability는 정확한 하드웨어·펌웨어·경로·transport·evidence 조합마다 독립
판정한다.

- `WAYLINE_DELIVERY`
- `EDGE_DOWNLINK`
- `EDGE_UPLINK`
- `MEDIA_PULL`
- `MEDIA_UPLOAD`

한 경로가 통과했다고 다른 기능을 추론해 `VERIFIED`로 올리지 않는다. feature
flag는 기능별이며 누락 시 OFF다. 모든 경로는 동일 idempotency key와 digest를
사용해 transport 전환이 Mission, EventBundle, SourceMedia 중복을 만들지 않게 한다.

### D4 — 계약과 신원을 분리한다

- `AcquisitionDeploymentProfile v1`은 운용 모드, gateway, transport, 인터넷 발급
  gate, Manifold direct mode, routing/media/Bridge 정책을 현장별로 고정한다.
- `ConnectivitySnapshot v1`은 짧은 TTL의 관측 사실과 capability receipt를 담는다.
- 사람은 `FIELD_OPERATOR`, RC/Dock은 `GATEWAY_DEVICE`, Manifold는 `EDGE_DEVICE`다.
  Gateway와 Edge device ID는 같을 수 없고, 모든 접근은 조직·Site 범위에서
  fail-closed로 대조한다.

### D5 — MSDK는 조건부 preflight/postflight Bridge다

- Pilot 2를 대체하는 KSI 비행 앱을 만들지 않는다.
- Cloud 하향 전달이 실기에서 실패할 때만 이륙 전 Mission Contract/MOP 전달을,
  Cloud 미디어 회수가 실패할 때만 착륙 후 회수를 구현한다.
- Virtual Stick, 이륙, 비행 시작, 경로·짐벌 제어 API는 넣지 않는다.
- Pilot 2 동시 실행이 불가능하면 `Bridge 동기화 → 종료 → Pilot 2 실행` 순서다.
- Bridge도 계약 전달과 원본 완전성을 증명하지 못하면 기본 제품 출시는 차단한다.
  Manifold SIM 필수나 수동 전달을 정상 경로로 조용히 바꾸지 않는다.

### D6 — Dock은 RC 제품 실증 뒤 공통 계약을 재사용한다

- `DOCK_AUTOMATED` profile과 공통 Core coordinator 계약은 지금 정의한다.
- Dock candidate adapter는 공통 port·Cloud protocol 경계를 사전 구현할 수 있다.
  실제 Dock account/hardware route 등록과 feature flag 활성화는 RC 기본형 HIL·FIELD
  이후 별도 Dock evidence가 있을 때만 허용한다.
- Dock 3 연결은 Ethernet 또는 공식 4G를 기본 transport로 취급하고, 현장 Wi-Fi는
  외부 Wi-Fi→Ethernet bridge 운용으로 분리한다.
- Dock+Manifold 병용이 실기·공식 지원으로 확인되면 Edge Dock으로 확장한다.
  실패하면 자동 촬영·서버 분석 중심의 축소 제품으로 고정하고 Edge 전용 기능을
  `UNAVAILABLE`로 표시한다.

## 소스 구조 결정

제품 책임별 bounded context를 먼저 두고 장비 차이는 adapter로만 격리한다.
정본 구조와 의존 규칙은 `docs/architecture/04_SOURCE_CODE_BOUNDARIES.md`다.

- Core: profile·신원·정책·readiness·Mission 발급 gate
- DJI Gateway: 기능별 port·route·receipt journal과 향후 장비 adapter
- Manifold: 로컬 지능·계약 activation·transport-neutral outbox
- Processing: 원본 봉인 이후 분석
- Dashboard: 노트북 중심의 반응형 Operations Console, 사람의 preflight/postflight
  상태·복구 행동과 제한된 모바일 이벤트·분석 UX

`DJI_CLOUD`, `PSDK_MANIFOLD`, `MANIFOLD_DIRECT`, `MSDK_FIELD`, `DJI_DOCK`의
candidate adapter는 HIL 전에 구현할 수 있다. 단, 빈 성공 구현이나 mock fallback은
금지하고 공식 SDK·프로토콜이 확인한 port만 광고한다. SDK·계정·하드웨어가 없거나
지원 근거가 없는 조합은 명시적으로 `NOT_VERIFIED` 또는 `BLOCKED`로 남긴다. 코드
존재는 capability evidence가 아니며 production route 등록 조건으로 사용할 수 없다.

## 현재 구현·검증 경계

2026-08-21 현재 additive Profile/Snapshot 계약, Core readiness API와 신규 Mission
발급 gate, capability router/port/journal 구조, Dashboard readiness projection,
HIL manifest v1.3 소프트웨어는 구현됐다. 이는 실장비 지원 증거가 아니다.

Mission 발급 강제 gate의 production rollout flag는 기본 OFF다. RC 기본형 capability
HIL과 기존 Site profile migration이 끝난 뒤에만
`KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=true`로 켠다. API가 readiness=false를
표시하는 것과 정책을 실제 차단 모드로 전환하는 것은 별도 단계다.

- `WAYLINE_DELIVERY`, `EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`, `MEDIA_UPLOAD`은
  실제 M4D + Manifold 3 + RC Plus 2 조합에서 모두 `NOT_VERIFIED`다.
- Dock 및 MSDK adapter의 code-ready 여부와 HIL support 여부는 독립 상태로 기록한다.
  code-ready adapter도 실제 SDK build와 장비 evidence 전에는 `NOT_VERIFIED`다.
- WorkOrder 승인부터 activation receipt, 착륙 후 media completeness와 Processing
  시작까지 잇는 실제 장비 coordinator는 후속 구현·HIL 대상이다.
- FIELD-0a/0b/1/2 완료 주장은 기존 acceptance 증거가 닫힐 때까지 금지한다.

## Rollback

- Cloud, direct Edge, MSDK Bridge, Dock을 capability별 feature flag로 독립 비활성화한다.
- journal v1.2 reader와 기존 `ZeroTouchGateway` facade를 migration 동안 유지한다.
- 기존 Pilot 2 수동 KMZ, SD/USB, folder ingest를 제거하지 않고 복구·검증 경로로
  유지한다.
- rollback은 새 발급 경로를 닫되 이미 활성화된 유효 Mission Contract를 네트워크
  상태만으로 취소하지 않는다.

## 2026-09-06 ADR-KSI-035 scope amendment

ADR-KSI-035's Pilot-default artifact download/import is a normal planning profile, not evidence
that any of D3's five capability routes works. Current original-media ingress and all automatic
media routes retain their stated `NOT_VERIFIED`/OFF status. A Pilot edit that is not returned
preflight cannot be represented as the signed/activated artifact of a future autonomous profile.
