# ADR-KSI-013 — 매핑 원본 미디어 반출 경로

- 상태: ACCEPTED (2026-08-05, 대표자 확정)
- 관련: ADR-KSI-005(연결 아키텍처 — LTE 상시 링크, EventBundle push 채택·텔레메트리
  스트림 제외), ADR-KSI-012(3D 재구성 파이프라인 — 이 ADR이 정하는 경로의 입구),
  `docs/hil/HARDWARE_SESSION_PLAYBOOK.md`(HIL 세션 항목 추가 대상), INV-023(신뢰
  불가 조건에서 fail-closed 원칙과 같은 정직성 태도), REQ-ACQ-103,
  INV-018/040/041/060

## 맥락

지금까지 저장소에 결정돼 있던 것은 **사건 증거(EventBundle)의 LTE push**뿐이다
(ADR-KSI-005 결정 2 — "링크가 상시면 기존 store-and-forward 설계가 그대로
'거의 실시간'이 된다"). 그러나 **매핑용 대량 원본 사진이 기체에서 어떻게
나와 처리 파이프라인 입구(ADR-KSI-012)까지 도달하는지에 대한 결정은 저장소
어디에도 없었다** — EventBundle 하나는 사진 소수 장 규모지만, 매핑 임무 하나는
수백~수천 장 규모다. 크기 축이 다른 문제인데 같은 답을 쓸 수 있다고 암묵
가정해선 안 된다.

## 결정

### D1 — 조종기(RC Plus 2) 경유 전송과 4G 업로드를 함께 채택

대표자 확정. 둘 다 쓰되 역할을 나눈다:

- **조종기(RC Plus 2) 경유**: 비행 종료 후 RC Plus 2가 보유한 미디어를 현장
  서버로 전송한다. 매핑 원본 대량 반출의 주 경로다.
- **4G(ADR-KSI-005의 상시 LTE 링크)**: 비행 중/직후 우선순위 높은 일부(사건
  증거 EventBundle — 기존 결정 그대로)와, 매핑 원본 중 선별된 일부를 우선
  반출하는 보조 경로다.

두 경로는 대체재가 아니라 **크기와 긴급도로 분업**한다 — 사건 증거처럼 작고
긴급한 것은 4G가 맡고, 매핑 원본처럼 크고 비행 종료 후에나 의미 있는 것은
조종기 경유가 맡는다.

### D2 — 검증 전까지 SD카드 수동 오프로드가 fallback이며, 그 사실을 숨기지 않는다

**아직 실기로 검증되지 않은 두 가지를 명시한다** — 이 ADR이 확정하는 것은
"이 경로를 쓰겠다"는 방향이지 "이 경로가 실제로 동작함을 확인했다"가 아니다:

1. **RC Plus 2가 매핑 원본 전량을 실제로 보유·반출하는지.** 기체 SD 카드에만
   남고 RC Plus 2로는 넘어오지 않는 해상도·포맷이 있을 가능성이 검증되지
   않았다. M4D 실기·RC Plus 2 실물 대조 전까지는 "RC 경유로 전량이 나온다"를
   사실로 서술하지 않는다.
2. **4G 실효 처리량.** 20MP 사진 3,000장이면 대략 30GB 안팎이라, 4G 단독으로는
   현실적인 반출 수단이 아니다 — 그래서 D1이 4G를 "일부 우선 반출"로만 배정한
   것이다. 이는 ADR-KSI-005가 LTE 실처리량을 "미확인, 실기 SSH 확보 후
   `ip addr`/`ping`/`curl`로 실측 검증"으로 남겨둔 것과 같은 축의 미검증이며,
   같은 방식(실기 실측)으로만 닫을 수 있다.

**검증 전에는 SD카드 회수·수동 오프로드가 정상 경로로 함께 문서화되어야 한다**
— "임시 우회"로 숨겨두면, 검증이 실패했을 때(① RC가 전량을 안 갖고 있거나 ②
4G가 매핑 원본을 감당 못 하는 경우) 매핑 자체가 막힌다. SD카드 경로는 실패
시의 fallback이 아니라 **검증 완료 전까지의 정상 경로**다.

이 검증 항목(① RC Plus 2 보유 미디어 vs 기체 SD 카드 전량 대조, ② 4G 실효
처리량·업로드 완주 시간 실측)은 `docs/hil/HARDWARE_SESSION_PLAYBOOK.md`에
아직 등록돼 있지 않다 — 이 ADR은 그 필요성만 확정하고, 실제 세션 항목화(어느
SPIKE-DJI 번호에 속할지, PRD §20.3 목록과의 정합)는 별도 편집으로 남긴다.

### D3 — 실제 camera adapter와 임무 귀속 경계가 모두 생기기 전 production 자동 반출 금지

2026-08-31 production wiring 감사에서 `MediaOffloadWorker`가 활성 dispatch의
`missionId`만 받고, 실제 임무 완료 신호·검증된 capture window·임무 시작 전 SD 카드
file-index baseline을 받지 않는다는 점을 확인했다. 호스트 시험용 `FakeMediaSourcePort`를
`DjiCameraManager_DownloadFileList`로 단순 교체하면 SD 카드에 남아 있던 이전 임무나 다른
현장 JPEG까지 현재 임무의 `SourceMediaBundle`로 기록·봉인할 수 있다. 이는 자동화 누락이
아니라 잘못된 계보를 만드는 더 큰 결함이다.

따라서 packaged `ksi_psdk_app`은 `FakeMediaSourcePort`와 자동 media worker를 조립하지 않는다.
과거 build option `KSI_PSDK_APP_ENABLE_MEDIA_OFFLOAD=ON`은 조용히 무시하지 않고 configure
단계에서 fail-closed 한다. `edge/manifold-runtime`의 PSDK-independent conveyor, durable rights
marker와 가짜 포트 테스트는 보존한다.

production option을 열려면 다음을 모두 충족해야 한다.

1. 실제 임무 완료 또는 운영자가 승인한 one-shot 반출 trigger
2. 임무 전 baseline 이후 신규 파일 또는 검증된 capture window에 의한 exact selection
3. list/download 사이 `fileIndex + fileName + fileSize` 재대조와 bounded JPEG download
4. M4D 지상 JPEG 한 장의 원본 digest, rights release와 Pilot 2 album 복구 HIL
5. 두 임무/현장의 파일이 섞이지 않는 cross-mission negative test

이 결정은 자동 반출을 포기하는 것이 아니다. false production path를 제거하고, D2의
`SD/저장매체 → 현장 PC → KSI 웹 업로드`를 검증 전 정상 경로로 유지한다. 소프트웨어 조립
테스트는 이 HIL 또는 DJI capability `VERIFIED`를 대신하지 않는다.

## 결과 — 알려진 대가

- 매핑 임무의 "원본이 서버에 다 도착했다"는 사실을, 검증 전에는 조종기 경유·
  4G만으로 보증할 수 없다 — 운영 절차에 SD카드 대조 단계가 계속 남는다.
- ADR-KSI-012의 재구성 파이프라인은 이 ADR이 정한 반출 경로로 원본이 실제
  도착했다는 것을 전제로 시작된다. 반출 검증(D2)이 완료되지 않은 상태에서
  "원본이 누락 없이 도착했다"고 완료 판정을 내리면 INV-051(원본/파생 계보)이
  전제하는 "원본"의 무결성이 흔들린다 — 반출 경로 검증과 재구성 완료 판정은
  분리해서 다뤄야 한다.
- D3의 임무 귀속 경계가 생길 때까지 zero-touch 자동 ingest 목표는 software-complete가
  아니다. 한 장 다운로드 성공만으로 대량 임무의 완전성·귀속·처리량을 추정하지 않는다.
