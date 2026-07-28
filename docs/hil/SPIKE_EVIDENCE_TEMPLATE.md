# SpikeEvidence 기록 템플릿 (11필드)

- 상태: 절차 확정, 실행 대기
- 정본 계약: `packages/domain/src/ksi_domain/spike_evidence.py` — 이 문서는 그 dataclass의
  11개 필드와 **1:1 대응**한다. 필드명·개수가 바뀌면 이 문서도 함께 갱신해야 한다
  (코드가 SSOT, 이 문서는 그 계약을 채우는 사람을 위한 작성 가이드).

## 사용법

`HARDWARE_SESSION_PLAYBOOK.md`의 각 단계(4~8단계, capability별)가 끝날 때마다 이
템플릿을 1장씩 복사해 채운다. **11개 필드 전부 비어 있으면 안 된다** —
`SpikeEvidence.__post_init__`이 `IncompleteSpikeEvidenceError`로 객체 생성 자체를
막는다(코드로 강제됨, 이 문서를 안 지켜도 이 지점에서 걸린다). `observed_at`은
tz-aware UTC가 아니면 마찬가지로 거부된다.

**빈 값 불가 규칙**: 아래 표의 "빈 값 처리"가 "불가"인 필드는 정말로 아무것도 못 썼다면
그 필드에 `"미기입 — <이유>"`조차 넣어선 안 된다는 뜻이 아니라, **빈 문자열(`""`)이나
공백만 있는 값은 코드가 예외를 낸다**는 뜻이다. "모르겠다"도 값이다 — 단 그게 왜
모르는지까지 적어야 형식적 회피("테스트했음"류)와 구분된다.

---

## 필드별 작성 가이드

### 1. `aircraft_firmware`
- **무엇**: 기체(M4D) 펌웨어 버전 문자열.
- **어떻게**: `HARDWARE_SESSION_PLAYBOOK.md` 3단계(기체 정보·Telemetry 읽기)에서
  PSDK/샘플로 조회한 실제 값. DJI Pilot 2 앱 화면의 표시값도 보조 근거로 쓸 수 있으나,
  가능하면 PSDK 조회값을 우선한다(둘이 다르면 그 사실 자체를 `test_procedure`에 남긴다).
- **형식 예시**: `M4D v08.02.0100` (버전 형식은 실기에서 확인한 그대로 — 이 예시
  숫자는 임의값이며 실측치가 아니다)
- **빈 값 처리**: 불가. 조회 자체가 실패했다면 이 필드가 아니라 애초에 VERIFIED 승격을
  시도하지 않는다(3단계 BLOCKED로 세션 진행을 멈춘다 — `HARDWARE_SESSION_PLAYBOOK.md`
  3단계 판정 기준 참고).

### 2. `rc_firmware`
- **무엇**: RC(RC Plus 2) 펌웨어 버전.
- **어떻게**: `aircraft_firmware`와 같은 3단계에서 함께 조회.
- **빈 값 처리**: 불가(동일 이유).

### 3. `manifold_image`
- **무엇**: Manifold 3 이미지/JetPack 식별자.
- **어떻게**: `tools/hil/collect_env_inventory.sh` 산출물의 `L4T_RELEASE`/`JETPACK_APT`
  필드 값을 그대로 옮긴다. 스크립트가 `MISSING: ...`을 남겼다면 그 문자열을 그대로
  적는다 — 조회 실패 자체가 유의미한 기록이다(단, 이 상태로는 아래 "빈 값 처리"에
  걸리지 않되, VERIFIED 승격의 근거로는 약하다는 점을 `test_procedure`에 함께 밝힌다).
- **빈 값 처리**: 값이 `MISSING: ...` 형태라도 비어있는 문자열은 아니므로 코드 게이트는
  통과한다 — 그러나 승격 여부 판단(사람의 몫)에서는 "환경을 특정 못 함"으로 취급한다.

### 4. `psdk_version`
- **무엇**: 사용한 DJI Payload SDK 버전.
- **어떻게**: 2단계(DJI 공식 샘플 빌드)에서 실제로 빌드한 SDK의 버전(릴리즈 태그·
  CMake 변수·헤더 매크로 등 확인 가능한 방식 중 실기에서 확인한 것). 정확한 조회
  방법은 이 문서 작성 시점에 단정하지 않는다.
- **빈 값 처리**: 불가.

### 5. `build_commit`
- **무엇**: 시험한 KSI 빌드의 git commit SHA.
- **어떻게**: `git rev-parse HEAD` (세션 시작 시 미리 기록 — `HARDWARE_SESSION_PLAYBOOK.md`
  §1 사전 준비).
- **빈 값 처리**: 불가. 이 필드가 없으면 "무엇을 시험했는지" 자체가 재현 불가능하다.

### 6. `test_procedure`
- **무엇**: 무엇을 어떤 순서로 했는지 — **재현 가능한** 절차.
- **어떻게**: 실행한 명령·클릭 순서·API 호출 순서를 그대로. "카메라를 테스트했다" 같은
  요약이 아니라, 다른 사람이 이 글만 보고 같은 시험을 재현할 수 있는 수준으로 적는다.
  `HARDWARE_SESSION_PLAYBOOK.md` 해당 단계의 "실행 항목"을 그대로 복사한 뒤, 실기에서
  실제로 달랐던 부분(다른 명령을 썼다, 순서를 바꿨다 등)을 반영해 고친다.
- **빈 값 처리**: 불가.

### 7. `raw_log_ref`
- **무엇**: 원본 로그 아티팩트 참조.
- **어떻게**: `docs/hil/RAW_LOG_CONVENTIONS.md` 규약을 따른 경로/URI. 세션 도중에는
  로컬 `hil_raw_logs/<session_id>/...` 경로도 가능하나, VERIFIED로 최종 승격하는
  시점에는 durable 저장소로 옮긴 URI를 적는다(로컬 전용 경로만 남기면, Manifold
  재부팅·디스크 정리로 증거가 사라질 수 있다).
- **빈 값 처리**: 불가. "로그 어딘가에 있음" 같은 비특정 문자열도 형식적으로는 코드를
  통과하지만, 이 템플릿의 규칙상 유효한 값이 아니다 — 구체 경로를 요구한다.

### 8. `latency_result`
- **무엇**: 측정된 지연 결과. 측정하지 않았다면 그 사실과 이유.
- **어떻게**: capability마다 다르다.
  - Frame 접근: 지연 개념이 명확치 않다면 "N/A — 이 capability는 지연을 측정 대상으로
    하지 않음"으로 명시.
  - 시간동기: `tools/hil/capture_frame_telemetry_timing.py summarize` 출력의
    p50/p95/max/표본수와 `measurement_status`/`acceptance_status`를 그대로 옮긴다.
    **`docs/hil/CAPABILITY_ACCEPTANCE.md` "시간동기" 행 규칙에 따라, 이 capability는
    `measurement_status=NOT_MEASURED`("미측정 + 이유")로도, `acceptance_status=FAIL`
    (p95 > 50ms — 측정은 했으나 목표 미달)로도 VERIFIED 승격이 불가하다** — 어느
    쪽이든 이 필드에 사유를 적되 승격 자체는 BLOCKED로 처리한다. VERIFIED 승격의
    유일한 근거는 `acceptance_status=PASS`뿐이다.
  - 짐벌: 명령~도달(또는 ack) 지연(ms)의 표본별 값 또는 요약(평균·최대).
- **빈 값 처리**: 불가.

### 9. `failure_result`
- **무엇**: 관측된 실패. 없었다면 "관측된 실패 없음 + 근거".
- **어떻게**: **이 필드가 이 계약의 핵심이다**
  (`packages/domain/src/ksi_domain/spike_evidence.py` 모듈 docstring 참고) —
  "실패를 안 봤다"와 "실패를 찾지 않았다"를 구분해야 한다. 실패가 없었다고 적으려면
  무엇을 몇 번, 어떤 조건에서 시도했길래 실패가 없다고 말할 수 있는지 근거를 함께
  적는다. 예: "관측된 실패 없음 — pitch ±10도 명령 5회 전부 오차 2도 이내로 도달,
  타임아웃·에러 응답 없음."
- **빈 값 처리**: **절대 불가** — 이 dataclass에서 유일하게 모듈 docstring이 별도로
  강조하는 필드다. 빈 문자열은 `IncompleteSpikeEvidenceError`로 즉시 거부된다.

### 10. `operator`
- **무엇**: 시험을 수행한 사람.
- **어떻게**: 실명 또는 조직 내 식별자.
- **빈 값 처리**: 불가.

### 11. `observed_at`
- **무엇**: 시험 시각(UTC, tz-aware).
- **어떻게**: `datetime.now(UTC)` 또는 그 단계를 실제로 수행한 시각. **naive
  datetime이나 UTC가 아닌 offset은 코드가 거부한다**(`__post_init__`의
  `utcoffset() != 0` 검사).
- **빈 값 처리**: `None` 불가, non-UTC tz-aware도 불가(offset이 0이어야 함).

---

## 채움 예시 (형식만 — 값은 전부 플레이스홀더, 실측 전까지 그대로 두지 말 것)

```python
from datetime import UTC, datetime

from ksi_domain.spike_evidence import SpikeEvidence

evidence = SpikeEvidence(
    aircraft_firmware="<실기 측정 — 3단계에서 조회한 실제 M4D 펌웨어 버전>",
    rc_firmware="<실기 측정 — 3단계에서 조회한 실제 RC 펌웨어 버전>",
    manifold_image="<실기 측정 — collect_env_inventory.sh L4T_RELEASE/JETPACK_APT 값>",
    psdk_version="<실기 측정 — 2단계에서 빌드한 실제 PSDK 버전>",
    build_commit="<git rev-parse HEAD 실측값>",
    test_procedure="<실기 세션에서 실제로 수행한 순서 그대로 서술>",
    raw_log_ref="<hil_raw_logs/<session_id>/... 또는 durable 저장소 URI>",
    latency_result="<실측값 또는 '미측정 + 구체적 이유'>",
    failure_result="<관측된 실패 또는 '관측된 실패 없음 + 근거'>",
    operator="<수행자 실명>",
    observed_at=datetime.now(UTC),  # 또는 실제 시험 수행 시각(UTC)
)
```

이 예시를 그대로 커밋하지 않는다 — 플레이스홀더가 남아 있으면 애초에
`SpikeEvidence(...)` 생성 시 `IncompleteSpikeEvidenceError`가 발생해 실행이 막힌다
(플레이스홀더 문자열 자체는 비어있지 않으므로 코드는 통과시킬 수 있다는 점에
주의 — **이 문서의 규칙이 코드보다 엄격한 지점**이다: `<실기 측정 — ...>` 형태의
값이 남아 있는 채로 VERIFIED 승격을 시도하지 않는 것은 사람이 지켜야 하는 규칙이지,
코드가 강제하지 않는다).
