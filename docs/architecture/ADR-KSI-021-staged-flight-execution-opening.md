# ADR-KSI-021 — 온보드 임무 실행의 단계적 개방(C2-S0~S4), 그리고 자물쇠를 둘로 나눈다

- 상태: ACCEPTED (2026-08-16, 대표자 지시)
- 관련: ADR-KSI-020(온보드 임무 실행 능력 — 본 ADR이 그 D2·D3를 대체한다),
  ADR-KSI-019 D4(자율성 경계 — 유지, 사유만 갱신), ADR-KSI-007(임무 이원 산출물),
  ADR-KSI-011 D1(FlightEnvelope 이륙점 상대 기준), 목표 원장
  `decision-psdk-flight-execution-authorization`

## 1. 대표자 결정 원문 (2026-08-16)

> "완성도 높은 자율 드론이 되려면 하나씩 해봐야 해요. 무조건 차단하는 건 좋지
> 않습니다."

ADR-KSI-020 D2는 "허용 여부는 FIELD-1 성공 이후 판단"이라고 남겼다. 이 결정이
그것을 앞당긴다 — 다만 **"허용한다 / 안 한다"의 이분법이 아니라 "어느 단계까지
지금 열고, 다음 단계는 무엇을 봐야 여는가"** 로 답한다.

동시에 대표자는 순서를 지정했다:

```text
150m / FlightEnvelope 수직기준 확정
      ↓
고도계산 계약 · 안전게이트 확정
      ↓
지상 / HIL 검증
      ↓
평탄한 현장에서 저위험 첫 실비행
      ↓
경사지 지형추종 실비행
      ↓
자율 매핑 / 순찰 확대
```

그리고 명시 제약: **"기체 직접 실행 허용과 지형인지 경로계획을 한꺼번에 승인하지
않는다. Planner가 경로를 잘 계산하는 것과, 실제 기체가 그 경로를 실행하도록
권한을 주는 것은 별도 게이트로 유지한다."** — 이 ADR은 후자(실행 권한)만
다룬다. 전자(지형인지 경로계획의 완성)는 ADR-KSI-022(수직기준 분리)와 별도
트랙이며, 두 트랙이 합류하는 지점은 §6 C2-S3의 진입 조건에만 있다.

## 2. 왜 자물쇠를 둘로 나누는가

지금까지 이 문제에는 자물쇠가 하나였다 — "빌드된 바이너리에 그 심볼이 있는가".
하나짜리 자물쇠는 열면 끝까지 열린다. 그리고 되돌리려면 재빌드·재배포가
필요하다.

**빌드 자물쇠**와 **런타임 자물쇠**를 분리한다.

| 자물쇠 | 통제하는 것 | 여는 주체 | 되돌리는 속도 |
|---|---|---|---|
| **빌드 (allowlist)** | 이 바이너리가 그 함수를 부를 **수 있는가** | 커밋 + 계약시험 + 결정 원장 결속 | 재빌드·재배포(시간~일) |
| **런타임 (서명 인가)** | 지금 이 기체가 실제로 부를 **것인가** | Core 서명 봉투 + 현장 사람 arming | TTL 만료(분), 즉시 |

이 분리가 만드는 성질: **가장 위험한 전이(실제 이륙)에 새 심볼 허용이 필요
없다.** 프로펠러 없는 START 단계(§6 C2-S2)에서 이미 `DjiWaypointV3_Action`
이 빌드에 들어가 있고, 그 다음부터(S3·S4)는 빌드 자물쇠가 더 열리지 않는다.
실비행 개방은 서명 한 필드로 이뤄지고, 되돌리기도 서명 중단 한 번이다(§8).

두 번째 원칙: **차단 5계열 중 1계열만 연다.** `DjiFlightController_*`(조이스틱·
이·착륙)·`DjiWaypointV2_*`(구세대)·`DjiInterestPoint_*`(선회 비행)·
`DjiFts_*`(비행종료장치·낙하산)는 **어느 단계에서도 열지 않는다** — 코드에
하드코딩해 매니페스트로도 못 열게 한다(§4). C-2는 `DjiWaypointV3_*` 하나로
달성된다.

## 3. 실측 근거

핀된 PSDK 3.16.0(`edge/third_party/psdk/psdk_lib/include/dji_waypoint_v3.h`)
원문:

| 사실 | 근거 |
|---|---|
| 정확한 심볼 6개 | `DjiWaypointV3_Init`, `DjiWaypointV3_DeInit`(**대문자 I** — `Deinit`으로 적으면 allowlist가 조용히 안 맞는다), `UploadKmzFile`, `Action`, `RegMissionStateCallback`, `RegActionStateCallback` |
| `E_DjiWaypointV3Action` | START(0)/STOP(1)/PAUSE(2)/RESUME(3) — 중단 수단이 API로 존재한다 |
| **상태 폴링 함수가 없다** | 상태는 콜백 전용이고 헤더가 *"User can not execute blocking style operations or functions in callback function"* 이라 못박는다 → 저널을 콜백 안에서 쓰면 안 된다 |
| 사전조건 센싱은 별도 헤더 | `dji_fc_subscription.h`(`STATUS_FLIGHT`·`BATTERY_INFO`·`HOME_POINT_SET_STATUS`·`RTK_POSITION_INFO`·`FLIGHT_ANOMALY` 등)에 있고 **이 헤더는 차단 목록에 없다** → 안전 사전조건 층은 게이트를 1mm도 열지 않고 지금 전부 만들 수 있다 |
| M4D 지원 여부 | **미확인.** `Init()` 반환값(SUCCESS/NONSUPPORT)으로만 판별된다(FIELD-0b U1) |

## 4. 결정 — 이중 잠금 구조

### D1 — 단계별 심볼 유니버스는 코드에, 매니페스트는 부분집합만

`tools/edge/check_shadow_flight_boundary.py`에 `_STAGE_SYMBOL_UNIVERSE`로
하드코딩한다:

```text
C2-S0: {}                                                  (매니페스트 없음 = 오늘까지의 보증)
C2-S1: {Init, DeInit, UploadKmzFile, RegMissionStateCallback, RegActionStateCallback}
C2-S2: C2-S1 ∪ {Action}
C2-S3: C2-S2 와 동일 (빌드 자물쇠는 안 늘어난다 — §2)
C2-S4: C2-S2 와 동일
```

매니페스트(`edge/flight-execution-allowlist.v1.json`)는 해당 단계 유니버스의
**부분집합만** 선언할 수 있다 — 초과분은 로딩 단계에서 거부되고 스캔까지
가지 않는다. **매니페스트를 편집하는 것만으로 `Action`을 열 수 없다** — 단계
자체를 올려야 하고, 단계를 올리면 §7의 8중 방지장치가 동시에 발화한다.

매니페스트가 없거나(경로 미지정) 파일이 없으면 이 게이트는 **2026-08-15 이전과
완전히 동일하게** 동작한다(C2-S0). `tests/contract/test_shadow_flight_boundary_gate.py`
의 기존 11개 판정은 문구 하나 안 바뀐 채 계속 통과한다 — 이것이 회귀가 아니라
확장이라는 증거다.

### D2 — 허용 파일은 단일 디렉터리, 개수 상한

임무 실행 어댑터는 `edge/psdk-app/src/flight_execution/` 안에서만, 최대 4개
파일까지 살 수 있다. `edge/manifold-runtime/**`는 이 매니페스트 아래서도
**영구 0건**이다 — 그 라이브러리의 "DJI 의존 없음" 성질이 깨지면 호스트 CI
전체가 PSDK를 요구하게 된다.

### D3 — 죽은 허가를 남기지 않는다

매니페스트에 있는데 소스 어디에서도 호출되지 않는 심볼은 `stale_allowlist_entries`
로 보고된다(`scan_called_symbols` + `FlightExecutionAllowlist.unused_entries`).
기본 실행에서 실패로 승격하지 않는다(PSDK 없는 호스트 빌드가 기본이라서다) —
CI 잡이 이 필드를 보고 경고한다.

### D4 — 벤더 정의는 `knownVendorDefinitions`로 명시 관리

ADR-KSI-020이 이미 지적한 `DjiFlightController_GetDjiErrorCode` 류의 벤더
정의 잡음은, strict 층이 매니페스트의 `knownVendorDefinitions`와의
**차집합**만 보고하도록 바꿨다 — 매 빌드마다 같은 잡음을 다시 설명하지 않는다.

## 5. 런타임 검증 순서 (전부 fail-closed, typed verdict)

빌드 자물쇠가 열려 있어도, 실제 `Action(START)` 호출 전에 반드시 이 순서를
통과해야 한다. **자동 재시도 없음** — arming nonce 1개는 START 시도 최대
1회다. "안 된 것 같아서 한 번 더"가 이중 이륙의 고전적 경로다.

```text
[0] 컴파일 단계 상수 ≥ 요구 단계인가
[1] NativeActivationSnapshot 유효 (Ed25519·digest·schemaVersion·TTL — INV-011)
[2] Core 서명 비행 인가 유효 (stage·장비·기체 일련번호·짧은 TTL)
[3] 현장 arming 토큰 유효 — nonce를 여기서 소비한다(호출 전, 후가 아니라)
[4] KMZ 바이트 digest == 계약이 선언한 kmzSha256 (ADR-KSI-020 §2 결속)
[5] KMZ 파싱 후 봉투 재도출 검증 (min/max altitude, allowed/excluded volumes)
[6] 보수적 상한 가드 — 평탄도·밀집지역 미선언·낮춘 ceiling (§6 참조, ADR-KSI-022 미확정 상태에서도 안전)
[7] 감독기 준비 + 시계 역행 검사 (내부 heartbeat — INV-012, Core 링크와 무관)
[8] 기체 사전조건 — STATUS_FLIGHT==STOPED, 기체 일련번호 일치, 배터리 여유,
    HOME_POINT_SET_STATUS==set, RTK/GPS 품질 하한, FLIGHT_ANOMALY 없음
[9] durable 기록 확정 ← 여기까지 끝난 뒤에만
[10] UploadKmzFile → Action(START), 반환값 기록
```

콜백 컨텍스트에서 이 순서를 호출하지 않는다(§3의 blocking 금지 제약을 그대로
상속). 실행기는 자기 스레드를 갖고, mission-state 콜백은 유계 큐에만 쓴다.

## 6. 단계 — C2-S0 ~ S4

| 단계 | 여는 심볼 | 진입 조건 | 증거 요구 |
|---|---|---|---|
| **S0** 현재 | 없음 | — | allowlist 파일 부재 = 오늘의 보증 |
| **S1** 업로드만 | `Init`/`DeInit`/`UploadKmzFile`/`Reg*Callback` — **`Action` 없음** | FIELD-0b U1 `Init()` 반환값, FIELD-0a KMZ 수용(H4) | Init·Upload **반환코드 원문**, 빌드 산출물 심볼 집합이 allowlist와 **정확히 일치**(초과 0, 잉여 0) |
| **S2** 프로펠러 없는 START | + `Action` | S1 증거 + §5 런타임 사전조건 전량 구현·호스트 CI 통과 + abort 지연 측정 + 기체 물리 고정(테스트 스탠드/스트랩) + **대표자 서면 승인** | START/STOP **반환코드 원문**, mission-state 콜백 로그 전체, **abort→STOP 발행 지연 p95 실측**, **고의 거부 실증 ≥3건**(만료 계약·digest 불일치 KMZ·arming 없음 각 1건) |
| **S3** 사람 감시 실비행 | **없음**(S2와 동일 — 빌드 자물쇠는 안 늘어난다) | S2 증거 + **ADR-KSI-022(수직기준 분리) 완료** + `SPIKE-DJI-06`(조종기 우선권) VERIFIED + FIELD-1 성공 + §6.1 평탄 현장 가드 + 대표자 서면 승인 | 완주 1회 + **의도적 중단 1회 raw**. 중단을 실증하지 않고 S4로 가지 않는다 |
| **S4** 일상 운용 | **없음** | 서로 다른 현장 ≥3, 서로 다른 날 ≥5회 무사고 + 거부 경로가 실운용 중 발화한 사례 ≥1 | — |

> **S2는 개념적으로 안전하지 않다.** 프로펠러 없이 START하면 기체는 모터를
> 돌리고 이륙을 시도하다 실패한다. DJI가 그 실패를 어떻게 처리하는지(오류
> 반환? 모터 계속 회전? 시동 자동 취소?) **우리는 모른다.** 이 단계의 목적은
> "잘 되는지 보기"가 아니라 **중단 경로를 실측하기**다. "프로펠러 없으니
> 안전"이라고 SOP에 적지 않는다 — 기체 손상 위험이 0이 아님을 명시한다.

### 6.1 S3 진입 조건 — 좁히기만 하는(narrowing-only) 상한 가드

`FlightEnvelope`나 계약 스키마를 지금 고치지 않는다(ADR-KSI-022가 그 분할을
결정한다 — 선점하지 않는다). 대신 Edge 쪽 실행 가드로만 좁힌다. **좁히기만
하는 제약은 그 결정이 어느 쪽으로 나든 유효하거나 잉여가 될 뿐, 틀리지
않는다.**

| 검사 | 값 | 근거 |
|---|---|---|
| 현장 평탄도 | AOI 안 `max(terrain) − min(terrain) ≤ 10m` | 이내면 이륙점 상대와 지표면 상대의 차이가 그 폭으로 유계 |
| 이륙점 표고 | AOI 표고 범위 **안**에 있어야 함 | 밖이면 부호가 한쪽으로 쏠린다 |
| 유효 상한 | `maxAltitudeM ≤ 135m`(150 − 10 − 여유) | 어느 기준면으로 읽어도 150을 안 넘는다 |
| 밀집 지역 | 현장 속성이 명시적으로 "일반"이어야 함 — 미선언 시 거부 | "주변 최고 장애물 상단" 기준은 아직 계산 못 한다(ADR-KSI-022 대상) |
| DTM/DSM 부재 | 거부 | 평탄도 판정 불가 = 판정 불가 |

10m·135m는 물리적 불가능의 증명이 아니라 **정책값**이다(ADR-KSI-011 D3의
"고도×1.5"와 같은 지위). 우리가 지금 나는 40m급 임무에서는 구속력이 없다 —
**보수적 제약이 지금 아무 비용도 안 든다는 것이 이 절의 요점이다.**

## 7. 실수로 넓어지는 것을 막는 8중 장치

`tests/contract/test_shadow_flight_boundary_gate.py`(38건, 신규 27건):

1. 단계 유니버스가 코드에 있다 — 매니페스트는 부분집합만
2. 매니페스트 스키마 필드(decisionRef·adrRef·knownVendorDefinitions) 고정 — 스키마가 바뀌면 이 시험도 함께 바뀌어야 한다
3. 결정 원장 결속 — `decisionRef`가 비어 있으면 CI 잡이 대조할 근거가 없다는 것을 스키마로 드러낸다
4. ADR 결속 — `adrRef` 필드
5. 경로 유니버스 — 단일 디렉터리, 파일 수 상한, `manifold-runtime/**` 영구 0건(파라미터화 4케이스)
6. **4계열 영구 차단** — 어떤 단계 유니버스에도 없음을 assert + 최상단 단계에서도 거부됨을 확인 + 죽은 코드가 아님을 monkeypatch로 검증
7. **심볼 철자 실측 대조** — `DeInit`(대문자 I) 같은 오타가 allowlist를 조용히 무력화하는 것을 핀된 PSDK 헤더와 대조해 잡는다
8. 기본 빌드는 계속 `--allow-mission-execution` 없이 통과해야 한다(플래그 없음 = C2-S0)

## 8. 중단 경로 — 우리 것과 DJI 것을 나눈다

우리가 보장하는 것은 **정확히 이것뿐**:

> abort 트리거 수신 후 X ms 내에 `Action(STOP)`을 발행하고 반환값을 기록한다.

그 호출이 기체를 호버로 두는지 RTH하는지는 **DJI 소유이며 S2에서 실측한
뒤에만 문서에 적는다.** 측정 전에는 어디에도 "STOP하면 안전하게 멈춘다"고
쓰지 않는다.

**arming/abort CLI는 C++로 만든다.** 매니폴드 Python은 3.8.10이고 우리 도구는
3.12 문법이며 관리자 권한이 없다(`mission-dispatch-cli-python312-runtime-provisioning-undecided`,
open 리스크) — 안전 경로를 3.12 컴패니언 가용성에 걸면 필요한 순간에 없다.

**자동 중단은 넣지 않는다(S2/S3).** 이륙 후에는 "중단"이 "계속"보다 안전하다는
것이 자명하지 않다. STOP의 공중 의미가 미검증이고, 오탐(시계 점프, 일시적
heartbeat 상실) 하나가 비행 중인 기체에 검증되지 않은 상태 전이를 걸게 된다.
RTH·착륙 권한은 이미 DJI FC와 조종자에게 있고, 그쪽이 더 나은 위치다.

- 하트비트 상실 → **신규 행동 금지 + 저널 + 경보.** START 취소는 하지 않는다.
- 계약 TTL이 비행 중 만료 → **저널 + 경보.** 자동 STOP 하지 않는다.
- S3에서 STOP의 공중 의미를 측정한 **뒤에** 대표자가 자동 규칙을 넣을지 판단한다.

## 9. 감사 — 상태가 아니라 영수증

**`IN_FLIGHT`를 만들지 않는다.** `packages/domain/src/ksi_domain/enums.py`의
근거("서버가 아는 사실이 아니다")가 여기서도 그대로 성립한다 — 우리가 아는 건
"Edge가 START를 발행했다고 서명해 보고했다"이지 "기체가 날고 있다"가 아니다.

`MissionExecutionStatus`는 **한 멤버도 안 늘린다.** 신규 엔드포인트
`POST /v1/edge-sync/missions/{dispatch_id}/flight-start-receipts`를 기존
`activation-receipts`(`edge_dispatch.py:511-548`)와 같은 모양으로 만든다 —
`EDGE_MISSION_PULL` 권한, 장비 바인딩, 멱등(재수신 200), typed verdict.

**거부도 같은 형식으로 기록한다**(`outcome = REFUSED_<verdict>`). 안 그러면
"아무도 시도 안 했다"와 "게이트가 막았다"가 구분되지 않고, 게이트의 가치가
눈에 안 보인다.

대시보드는 이것을 **상태 배지가 아니라 별도 축**으로 그린다 — "START 발행
보고 (시각, 기체 상태 아님)". INV-041의 정직성 규율과 같은 문구 규율이다.
INV-010은 그대로다 — 완료 판정 권위는 여전히 CoverageReport 하나다.

## 10. 되돌리기 (혈액량 작은 순)

| # | 레버 | 무엇이 되돌아가나 | 소요 | 재빌드 |
|---|---|---|---|---|
| 1 | Core가 비행 인가 발급 중단(또는 서명키 회전) | 기존 봉투는 TTL로 만료. 새 START 불가 | 분~시간 | 불필요 |
| 2 | 현장 즉시 — `--deactivate` + arming 자격 회수 | 그 기체만 즉시 | 초 | 불필요 |
| 3 | 단계 롤백 — 매니페스트 `stage`를 낮추고 계약시험 갱신 | 빌드가 그 심볼을 못 부름 | 커밋 1건 + 재배포 | 필요 |
| 4 | **완전 철회 — `edge/flight-execution-allowlist.v1.json` 삭제** | 체커 기본값이 S0이므로 **오늘의 보증으로 정확히 복귀** | 파일 1개 삭제 | 필요 |
| 5 | 코드 제거 — `edge/psdk-app/src/flight_execution/` 삭제, CMake 옵션 제거 | 소스에서도 사라짐 | | 필요 |

**핵심 설계 제약: 되돌리기가 `check_shadow_flight_boundary.py`를 건드리지
않는다.** 체커의 기본값이 전면 차단이고 매니페스트만이 여는 유일한 수단이므로,
레벨 4는 파일 하나 삭제로 끝난다. 그리고 §7의 38개 계약 시험이 문구 그대로
계속 통과하고 있으므로, 되돌아간 상태가 기억이 아니라 **살아 있는 assertion**
으로 남는다.

## 11. ADR-KSI-019 D4와의 정합

ADR-KSI-019 D4("사람: 비행 시작 전 승인")는 **유지한다.** C-2는 그 승인을
없애는 것이 아니라, 승인이 "조종기 앞에서 버튼을 누른다"에서 "현장에서
arming 토큰을 발급한다"로 형태가 바뀌는 것이다 — §5 [2][3]이 그 승인을 서명·
단발 nonce로 강제한다. `check_shadow_flight_boundary` 게이트는 이 결정에서도
완화하지 않는다 — 완화하는 것은 §5의 런타임 인가뿐이고, 빌드 자물쇠는 §6
표대로 S2에서 멈춘다.

## 12. 결과 — 알려진 대가

- 이 ADR은 "안 되는 줄 알았는데 되는 것"을 단계적으로 열고, 그만큼 매 단계마다
  "왜 여기서 멈췄는지"를 설명해야 하는 부담이 생긴다. 그 설명을 문서가 하지
  않으면 다음 세션이 매니페스트를 결함으로 오인하거나, 반대로 무심코 다음
  단계를 승인해 버릴 수 있다 — §6 표가 그 설명의 정본이다.
- M4D가 NONSUPPORT를 반환하면 S1에서 끝난다. 그것이 나쁜 결과가 아니라
  **가장 값싼 결과**다 — 그래서 순서가 이렇다(FIELD-0b U1이 S2 이전에 옴).
- `SPIKE-DJI-06`(조종기/PSDK 동시 제어권)이 S3의 실질적 병목이고, 지금
  `HARDWARE_SESSION_PLAYBOOK.md` §0이 명시적으로 세션 범위 밖으로 남겨뒀다 —
  이걸 여는 별도 세션이 S3 전에 하나 더 필요하다.
- ADR-KSI-013(사진 반출 경로)과 이 ADR은 독립이다 — C-2(임무 시작)와 사진
  자동 회수는 서로 다른 PSDK API 계열(`DjiWaypointV3_*` vs
  `DjiCameraManager_*`)이며, 후자는 이 게이트의 차단 대상이 아니다.
