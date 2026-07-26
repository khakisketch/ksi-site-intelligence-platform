# DJI Hardware Capability Spike 절차 (Track A)

- 상태: 절차 확정, **실행 대기**(실기 M4D + RC Plus 2 + Manifold 3 필요)
- 근거: MASTER_PRD §20.3 SPIKE_REQUIRED 9항목, 독립 검토 2026-07-27 우선순위

## 0. 원칙 — 읽기 먼저, 쓰기는 별도 게이트

Spike는 **읽기 중심**으로 시작한다. 실제 `FlyTo`·`Route Update`·`Yaw` 같은 쓰기 명령은
Telemetry·Camera·Heartbeat 경로가 먼저 검증된 뒤 **별도 게이트**로 진행한다.

이유: 쓰기 경로가 먼저 열리면 어느 계층이 문제인지 분리할 수 없다. 읽기가 안정적으로
동작하는 것을 확인한 뒤에야 "명령이 실패했다"가 명령 자체의 문제라고 말할 수 있다.

INV-001/002는 이 단계에서도 유효하다 — 현재 `ksi_control_plane`에는 기체를 움직이는
코드 경로가 없고, Spike는 그 상태를 바꾸지 않는다.

## 1. 실행 순서 (읽기 단계)

순서에 의미가 있다 — 앞 항목이 실패하면 뒤 항목의 결과를 신뢰할 수 없다.

| # | 항목 | 확인 대상 | 실패 시 |
|---|---|---|---|
| 1 | 환경 인벤토리 | Manifold 3 이미지·JetPack·컴파일러·PSDK 버전 실측 | 이후 전부 중단(기준선 없음) |
| 2 | DJI 공식 샘플 빌드·실행 | 툴체인이 실제로 동작하는가 | KSI 코드 문제와 툴체인 문제를 분리 못 함 |
| 3 | 기체 정보·Telemetry 읽기 | 연결·기체 식별·상태 수신 | 3~7 전부 중단 |
| 4 | 카메라 Live View 접근 | 프레임 수신 가능 여부 | 5~7 중단 |
| 5 | 렌즈 식별·전환 가능성 | 광각/중망원/망원 식별과 전환 | 렌즈 관련 capability만 BLOCKED |
| 6 | 짐벌 상태 읽기 + 제한적 제어 | pitch/yaw 읽기, 소각도 이동 | 짐벌 capability만 BLOCKED |
| 7 | Frame–Telemetry 시간차 실측 | P0-2 모델의 전제 검증(PRD §21.1 p95≤50ms) | 시간동기 정확도 주장 불가 |
| 8 | DPK 빌드·설치·재시작 검증 | 배포 경로가 실제로 동작 | 운영 배포 주장 불가 |

각 항목은 `contracts/schemas/` 대응 capability에 매핑된다(PRD §20.3의 `SPIKE-DJI-01`~`09`).

## 2. 증거 없이는 VERIFIED 없다 — 코드로 강제됨

`CapabilityRegistry.transition(..., VERIFIED)` 는 **문자열 evidence만으로는 거부된다.**
구조화된 `SpikeEvidence`(11개 필드)가 필수다:

```
aircraft_firmware  rc_firmware      manifold_image   psdk_version
build_commit       test_procedure   raw_log_ref      latency_result
failure_result     operator         observed_at(UTC)
```

`failure_result` 는 **빈 값을 허용하지 않는다.** 실패가 없었다면 "관측된 실패 없음 +
근거"를 적는다 — 빈 실패 칸은 "실패를 안 봤다"와 "실패를 찾지 않았다"를 구분할 수 없고,
후자를 전자로 읽으면 검증되지 않은 기능이 VERIFIED가 된다.

레코드 하나라도 비면 `IncompleteSpikeEvidenceError` 로 **객체 생성 자체가 실패한다** —
불완전한 증거를 들고 승격을 시도할 수 없다.

## 3. 세션 진행 방법

```python
from datetime import UTC, datetime
from ksi_core.capability.registry import CapabilityRegistry, seed_prd_spikes
from ksi_domain.capability import CapabilityVerificationState
from ksi_domain.spike_evidence import SpikeEvidence

registry = CapabilityRegistry()
seed_prd_spikes(registry)          # 9항목 전부 SPIKE_REQUIRED, 노출 0건

# ... 실기 시험 수행, 로그 수집 ...

registry.transition(
    "SPIKE-DJI-01",
    CapabilityVerificationState.VERIFIED,
    evidence="카메라 프레임 접근 HIL 통과",
    spike_evidence=SpikeEvidence(
        aircraft_firmware="<실측>",
        rc_firmware="<실측>",
        manifold_image="<실측>",
        psdk_version="<실측>",
        build_commit="<git rev-parse HEAD>",
        test_procedure="<재현 가능한 절차>",
        raw_log_ref="<로그 아티팩트 URI>",
        latency_result="<측정값 또는 '미측정 + 이유'>",
        failure_result="<관측된 실패 또는 '없음 + 근거'>",
        operator="<수행자>",
        observed_at=datetime.now(UTC),
    ),
)
```

승격 후 `list_operational()` 에 나타나며, 그때부터 운영 API(`/capabilities`)에 노출된다.
회귀가 발견되면 `BLOCKED` 로 내리고, 그 시점에 **낡은 증거는 함께 삭제된다**(다음 승격은
새 증거를 요구한다).

## 4. 확인되지 않은 것을 확인된 것으로 적지 않는다

- 공식 문서에 기능이 언급된 것은 `VERIFIED` 가 아니다(PRD §20.1 vs §20.3).
- Dock 3 + M4D 제3자 Payload 제약은 문서상 확인된 **제약**이므로, 해당 항목은 실기
  없이도 `BLOCKED`(사유 필수)로 둘 수 있다 — 이것은 검증이 아니라 차단이다.
- Manifold 3 최대 100 TOPS는 특정 INT8 희소 연산 조건의 이론값이다. 실제 처리량은
  이 Spike의 `latency_result` 로만 주장한다(`docs/edge/MANIFOLD3_TOOLCHAIN.md` 참조).
