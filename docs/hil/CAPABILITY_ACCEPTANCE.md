# Capability Acceptance Criteria (Track A Hardware Session Pack)

- 상태: 절차 확정, 실행 대기
- 근거: `packages/domain/src/ksi_domain/capability.py`(`CapabilityVerificationState`),
  `services/core/src/ksi_core/capability/registry.py`(`SPIKE-DJI-01`~`09` ID),
  `packages/domain/src/ksi_domain/spike_evidence.py`(`SpikeEvidence` 11필드),
  `docs/product/DOMAIN_INVARIANTS.md` INV-041, 대표자 지정 기준(2026-07-27)

이 문서는 `docs/hil/HARDWARE_SESSION_PLAYBOOK.md`가 다루는 5개 capability에 대해
**무엇이 있어야 VERIFIED이고 무엇이면 BLOCKED인가**를 표로 고정한다. 판정은 사람이
`SpikeEvidence`를 채우며 내리지만, 그 판정이 자의적이지 않도록 이 표를 기준으로 삼는다.

## 0. 공통 규칙

- **VERIFIED에는 항상 `SpikeEvidence`(11필드) 전체가 필요하다** — `CapabilityRegistry.transition()`이
  코드로 강제한다(`spike_evidence=None`이면 `IllegalCapabilityTransitionError`).
- **"미측정"은 그 자체로 값이 아니다.** `latency_result`·`failure_result`는 빈 문자열을
  허용하지 않는다(`IncompleteSpikeEvidenceError`) — 측정하지 않았다면 "미측정 + 왜
  못 했는지"를 반드시 적는다. 아래 표의 "VERIFIED 불가 사례"는 이 규칙의 구체화다.
- **BLOCKED는 실패가 아니라 정직한 상태다.** 사유만 있으면 초기 등록도, 재전이도
  가능하다(`CapabilityRegistry.register(..., state=BLOCKED, evidence=...)` 또는
  `transition(..., BLOCKED, evidence=...)`). BLOCKED로 세션을 마치는 것 자체는 문제가
  아니다 — 근거 없이 VERIFIED로 적는 것이 문제다.
- 아래 표의 "대응 Capability ID"는 `services/core/src/ksi_core/capability/registry.py`의
  `SPIKE-DJI-xx` 시드와 대조한 것이다. ID가 없는 행(시간동기·Telemetry)은 PRD §20.3의
  9항목에 정확히 대응하는 등록 ID가 없다는 뜻이며, 이 문서가 임의로 새 ID를 만들지
  않는다(레지스트리 SSOT는 `registry.py`) — 대신 해당 capability가 어느 다른 capability의
  전제조건인지를 명시한다.

## 1. Frame 접근 (카메라 프레임)

- **대응 Capability ID**: `SPIKE-DJI-01`("M4D 카메라별 실시간 프레임 접근")
- **세션 단계**: `HARDWARE_SESSION_PLAYBOOK.md` 4단계

| 항목 | VERIFIED 기준 | BLOCKED 기준 |
|---|---|---|
| 프레임 수신 | 실제 프레임 데이터를 최소 1개 이상 수신 | 연결은 되나 프레임 데이터가 전혀 오지 않음 |
| 해상도 | 관측된 실제 해상도(예: `3840x2160`)를 기록 — "지원한다고 문서에 있음"은 불가 | 해상도를 확인할 방법이 없음(포맷 불명 등) |
| 프레임률 | 관측된 실제 fps(예: "약 24~30fps, N초 관측") | fps를 셀 수 있을 만큼 연속 수신이 안 됨 |
| 지속시간 | 최소 10초 이상 끊김 없이 연속 수신한 구간이 1회 이상 | 프레임이 간헐적으로만 오거나 즉시 끊김 |

**VERIFIED 불가 사례**: "카메라에 연결은 됐다" + 해상도/fps 중 하나라도 미기록 →
`SPIKE-DJI-01`은 `SPIKE_REQUIRED`(재시도 필요) 또는 `BLOCKED`(사유: 특정 실패)로
남긴다. "공식 문서에 프레임 접근 API가 있다고 나와 있음"은 그 자체로 어떤 상태
전이의 근거도 아니다(INV-041 — 문서 언급 ≠ 검증).

## 2. 시간동기 (Frame–Telemetry Timestamp Alignment)

- **대응 Capability ID**: 없음 — PRD §20.3의 9항목이 아니라 §21.1(비기능 요구사항)의
  실측 대상이며, `docs/product/DOMAIN_INVARIANTS.md` INV-025(CONFIRMED 승격의
  `CALIBRATED_POSE` 시점 증거 전제조건)가 이 실측치에 의존한다. 별도 등록 ID가
  필요하다고 판단되면 대표자 결정 레인으로 상신할 사안이며, 이 문서가 임의로 만들지
  않는다.
- **세션 단계**: `HARDWARE_SESSION_PLAYBOOK.md` 7단계
- **도구**: `tools/hil/capture_frame_telemetry_timing.py`

이 capability는 단일 VERIFIED/BLOCKED 판정으로 뭉뚱그리지 않고, **측정을 성공적으로
수행했는가**와 **요구사항(p95 ≤ 50ms)을 만족했는가**를 분리한 2축으로 기록한다 —
"측정했다"와 "목표를 달성했다"는 서로 다른 질문이고, Track A 완료기준은 후자에
의존하기 때문이다(CONFIRMED 위치 정합성이 이 값에 걸려 있다 — INV-025).

```
measurement_status: MEASURED | NOT_MEASURED
acceptance_status: PASS | FAIL | INSUFFICIENT_SAMPLES
```

| measurement_status | acceptance_status | 판정 규칙 |
|---|---|---|
| `MEASURED` | `PASS` | p95 ≤ 50ms **그리고** 최소 표본(권장 ≥100) 충족 |
| `MEASURED` | `FAIL` | p95 > 50ms — 사유는 `requirement_not_met`. **VERIFIED 승격 금지**(표본 수가 충족돼도 마찬가지) |
| `MEASURED` | `INSUFFICIENT_SAMPLES` | 표본 1건 이상 수집했으나 최소 표본(≥100) 미달 — PASS도 FAIL도 주장하지 않는다 |
| `NOT_MEASURED` | (해당 없음) | 표본 0건. 수집 자체가 실패했거나 시도하지 않음 |

| 항목 | 기록 기준 |
|---|---|
| 표본 수 | 실측 표본 수를 그대로 기록. 0건이면 `measurement_status=NOT_MEASURED` |
| p50 / p95 / max | `summarize` 서브커맨드의 실측값(ms). `NOT_MEASURED`면 존재하지 않는다(표본 0건이면 계산 함수 자체가 예외를 낸다) |
| acceptance_status | 위 판정 규칙을 기계적으로 적용한다 — 사람이 임의로 PASS로 올릴 수 없다 |

**"측정 기능이 작동했다" ≠ "요구사항을 만족했다"**: `capture_frame_telemetry_timing.py`가
정상적으로 표본을 수집·요약했다는 사실("도구 자체는 동작한다")은 별도 항목으로 기록할
수 있으나, 그 자체가 시간동기 **요구사항**을 VERIFIED로 올리는 근거가 될 수 없다 —
VERIFIED 승격의 유일한 근거는 `acceptance_status=PASS`뿐이다.

**"미측정 + 이유" 불가 원칙**: `measurement_status=NOT_MEASURED`인 상태에서
`SpikeEvidence.latency_result`에 "미측정 + 이유"를 적는 것 자체는 유효한 기록이지만,
그 기록으로 이 요구사항을 VERIFIED로 승격하는 경로는 없다 — 대표자 지정 기준이 명시한
대로, 시간동기는 다른 capability(짐벌 등)와 달리 **"측정 안 함 + 정당한 이유"로 VERIFIED
처리하는 경로가 없다.** 표본을 못 모았다면 이 capability는 `BLOCKED`(사유: "PSDK 콜백
미연동" 등 구체적 원인)로 남기고, `latency_result`에는 "미측정 — 사유: <구체적 원인>"을
적되 이는 BLOCKED 상태의 근거이지 VERIFIED 근거가 아니다.

**목표(50ms) 미달(`acceptance_status=FAIL`)도 VERIFIED 승격 근거가 아니다** — 실측을
정직하게 해냈다는 사실과 "요구사항을 만족했다"는 별개다. FAIL은 `BLOCKED`(사유:
"p95 목표 미달 — requirement_not_met")로 남기고, 별도 리스크(`.ksi/goals.json` risk
항목 등)로도 추적한다. "측정했으면 그 수치 그대로 VERIFIED"라는 경로는 없다.

## 3. 짐벌 (Gimbal)

- **대응 Capability ID**: `SPIKE-DJI-03`("기체 Yaw/짐벌 Pitch API와 지연")의 **짐벌
  부분**(기체 Yaw는 `HARDWARE_SESSION_PLAYBOOK.md` §0에 따라 이번 세션 범위 밖 —
  전체 VERIFIED에는 Yaw 부분 증거가 별도로 더 필요하다)
- **세션 단계**: `HARDWARE_SESSION_PLAYBOOK.md` 6단계

| 항목 | VERIFIED 기준 | BLOCKED 기준 |
|---|---|---|
| 명령값 | 보낸 pitch 명령값(deg)을 표본별로 기록 | 명령을 보낼 API 자체를 찾지 못함 |
| 관측값 | 짐벌이 실제로 도달한 pitch(deg)를 표본별로 기록 | 관측(read-back) 방법이 없음 |
| 오차 | `\|명령값 - 관측값\|`을 표본별로 계산·기록 (오차 크기 자체는 PASS 조건 아님) | 오차를 계산할 관측값이 없음 |
| 지연 | 명령 전송~목표 도달(또는 명령 ack) 시간(ms)을 표본별로 기록 | 좌동 |
| 제한조건 | 관측된 기계적 리밋·안전모드 진입 조건을 기록(있다면) | — (선택 항목, 없어도 VERIFIED 가능) |

**최소 표본**: 5회 이상의 명령-관측 쌍(`HARDWARE_SESSION_PLAYBOOK.md` 6단계 판정
기준과 동일).

- **5회 미만**: `SPIKE_REQUIRED`를 유지한다. "잠정 VERIFIED" 같은 중간 상태는 없다 —
  `CapabilityVerificationState`에는 `SPIKE_REQUIRED`/`VERIFIED`/`BLOCKED` 세 값만
  존재하며(`packages/domain/src/ksi_domain/capability.py`), 표본 부족을 사유로 적어도
  VERIFIED로 승격하지 않는다. 다음 세션에서 표본을 보강한다.
- **명령을 보낼 API 자체가 없거나 관측(read-back) 방법이 없음**: `BLOCKED`(구체 사유).
- **5회 이상 + 명령값·관측값·오차·지연 4가지 전부 수치로 기록**: 짐벌 부분 증거
  충족(§0 공통 규칙에 따라 `SpikeEvidence` 11필드가 갖춰지면 승격 근거가 된다).
- **`SPIKE-DJI-03` 전체 VERIFIED는 별도 조건**: 이 표는 짐벌 부분 증거만 다룬다 —
  기체 Yaw 부분 증거가 별도로 채워지기 전까지 `SPIKE-DJI-03` **전체**를 VERIFIED로
  승격하지 않는다(위 "대응 Capability ID" 각주 참고).

**VERIFIED 불가 사례**: "짐벌이 움직이는 것을 육안으로 봤다"만으로는 불가 — 명령값·
관측값·오차·지연 4가지 중 하나라도 수치로 기록되지 않으면 VERIFIED 승격 근거가
부족하다.

## 4. 렌즈 (Lens 식별·전환)

- **대응 Capability ID**: `SPIKE-DJI-02`("광각/중망원/망원 전환과 촬영·초점 제어")
- **세션 단계**: `HARDWARE_SESSION_PLAYBOOK.md` 5단계

| 항목 | VERIFIED 기준 | BLOCKED 기준 |
|---|---|---|
| 렌즈 식별 | 사용 가능한 렌즈 목록(광각/중망원/망원 중 실제 탑재분)을 API로 조회 | 렌즈 목록 조회 API를 찾지 못함 |
| 전환 | 최소 2개 렌즈 간 전환 성공 + 전환 후 각각 프레임 수신 확인(Frame 접근 기준 재사용) | 전환 명령이 응답하지 않거나 전환 후 프레임이 끊김 |
| 촬영 제어 | 스냅샷 명령 결과(성공/실패)를 기록 | — (실패해도 렌즈 전환이 됐다면 이 항목만 별도 BLOCKED 메모, 전체 BLOCKED 아님) |
| 초점 제어 | 초점 명령 결과(성공/실패, 가능한 범위)를 기록 | 좌동 |

**부분 VERIFIED 처리**: 렌즈 전환은 성공했으나 촬영/초점 제어가 실패한 경우, 렌즈
식별·전환 부분만으로 `SPIKE-DJI-02`를 VERIFIED하지 않는다 — 타이틀 자체가 "전환과
촬영·초점 제어"를 함께 요구하므로, 촬영·초점 실패는 `failure_result`에 명시하고
`SPIKE-DJI-02` 전체는 `BLOCKED`(부분 성공, 구체 사유)로 남긴다. 부분 성공을
VERIFIED로 올리려면 대표자 확인이 필요하다(스코프 축소는 공동 결정 레인).

## 5. Telemetry (기체 상태 수신)

- **대응 Capability ID**: 없음 — PRD §20.3 9항목 중 명시적 단일 항목이 아니라, 다른
  다수 capability(`SPIKE-DJI-03`의 Yaw 지연 측정, `SPIKE-DJI-07` Manifold 이벤트 네트워크
  경로, 시간동기 실측)의 **전제조건**이다. `docs/dji/SPIKE_PROCEDURE.md` §1의 3단계가
  이 항목에 해당한다.
- **세션 단계**: `HARDWARE_SESSION_PLAYBOOK.md` 3단계

| 항목 | VERIFIED 기준(전제조건 충족 기준) | BLOCKED 기준 |
|---|---|---|
| 연결 | 기체·RC와의 연결이 성립하고 유지됨 | 연결 자체가 안 됨 |
| 식별 | 기체 SN·모델·펌웨어 버전, RC 펌웨어 버전을 실제로 조회 | 식별 정보 조회 실패 |
| 수신 지속성 | 최소 30초간 Telemetry 스트림이 끊기지 않음 | 스트림이 즉시 끊기거나 아예 수신 안 됨 |
| 수신 주기 | 관측된 주기(Hz)를 기록(목표치 판정은 이 항목의 몫이 아니다 — PRD §21.1 관련 목표는 개별 capability에서 판정) | — |

**주의**: 이 항목은 독립된 `SPIKE-DJI-xx` ID로 VERIFIED 승격하지 않는다 — 위에서 밝힌
대로 별도 등록 ID가 없다. 이 표의 기준은 **3단계가 PASS로 다음 단계에 진행해도 되는지**를
판단하는 게이트로 쓰고, VERIFIED 선언이 필요한 실제 승격 대상은 이 Telemetry 결과가
뒷받침하는 상위 capability(`SPIKE-DJI-01/02/03/07`)들이다.
