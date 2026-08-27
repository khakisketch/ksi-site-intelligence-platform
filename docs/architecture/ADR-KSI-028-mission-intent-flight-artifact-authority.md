# ADR-KSI-028 — Mission Intent, Route Compiler, Final Flight Artifact의 권한 분리

- Status: Accepted
- Date: 2026-08-27
- Requirements: REQ-MSN-101/104, REQ-ACQ-101/103, REQ-SEC-101
- Invariants: INV-001/002, INV-011/012, INV-016, INV-040/041, INV-050, INV-060
- Related: ADR-KSI-019, ADR-KSI-020, ADR-KSI-021, ADR-KSI-023, ADR-KSI-027
- Supersedes: 없음. 기존 KSI_WPML 짝 발급의 구현·Pilot 2 운용 경계는 유지한다.

## Context

KSI Core에는 AOI·카메라·고도·중복도·봉투 정책에서 WPML/KMZ와 서명된 Mission
Contract를 함께 만드는 경로가 이미 있다. 이는 최초 매핑과 재관측의 유효한 후보
경로지만, 현장에서 실제로 실행되는 최종 경로가 항상 그 compiler의 산출물이라는
권한 모델로 확대 해석하면 안 된다.

Pilot 2에서 작성·내보낸 KMZ는 현장 운용의 유용한 기준선이다. 반면 Pilot 2 import/export
비교, 편집 후 의미 보존, 기체 수용, 실행 결과는 아직 FIELD-0a 증거로 닫히지 않았다.
따라서 지금 Core KMZ generator를 삭제하거나 Pilot-native KMZ를 자동 기본값으로
선언하는 것은 둘 다 근거가 부족하다.

또한 경로를 누가 compile했는지와, 어느 바이트를 어떤 정책으로 승인했는지는 다른
문제다. 전자는 transport·도구 선택 문제이고 후자는 Mission Contract·감사·재현성의
문제다.

## Decision

### D1 — Core는 Mission Intent와 최종 Flight Artifact의 권위자다

Core는 다음을 소유한다.

- 관측 목적·AOI·capture/flight envelope·site policy·승인 범위를 담은 `MissionIntent`;
- 검증된 `FlightArtifact`의 source, revision, content digest, validation receipt와
  Mission Contract 결속;
- artifact를 바꾼 뒤 이전 계약·승인·digest를 재사용하지 않는 revision 규칙;
- artifact와 SourceMedia·CoverageReport·Processing lineage의 감사 연결.

Core는 경로 compiler를 독점하지 않는다. Core가 `WHAT/WHY`를 정하고, 최종 artifact의
승인·추적성을 소유하며, 현장 execution과 low-level safety는 기존 경계대로 Pilot 2,
Manifold, DJI Flight Controller에 남는다.

### D2 — FlightArtifact source를 교체 가능한 명시적 입력으로 둔다

초기 source universe는 다음과 같다.

| source | 지위 | 사용 조건 |
|---|---|---|
| `KSI_WPML` | 현재 Core generator가 만드는 candidate/fallback | 현재 software 경로 유지; 실기 수용·실행 주장은 하지 않음 |
| `DJI_PILOT_EXPORT` | Pilot 2가 export한 외부 artifact | 안전한 ZIP/WPML 검증, provenance, revision/digest 결속 후에만 ingest 가능 |
| `DJI_CLOUD_GENERATED` | 향후 후보 | 정확한 account/hardware/path별 공식 근거와 HIL evidence가 생긴 뒤 별도 ADR/adapter로 연다 |

source는 "지원됨" 또는 "실행 가능"의 선언이 아니다. `DJI_PILOT_EXPORT`를 Core가
받는 기능도 Pilot 2가 자동 전달하거나 무인 실행한다는 뜻이 아니다.

### D3 — KSI_WPML은 FIELD-0a 비교 전까지 유지한다

Core generator는 제품 차별성 그 자체로 가정하지 않는다. 그러나 다음 FIELD-0a 증거가
없이는 제거하지 않는다.

- KSI 생성 KMZ의 Pilot 2 import 수용 여부;
- Pilot 2 native mapping export의 provenance와 원본 보존;
- 압축을 푼 XML 수준의 route/waypoint/photo count, 고도 기준, 촬영 trigger,
  거리·예상시간 등 의미 비교;
- 현장 편집이 artifact revision·재검증·재결속으로 연결되는지.

그 결과는 `KSI_WPML_DEFAULT`, `DJI_NATIVE_DEFAULT`, `KSI_WPML_FALLBACK` 중 하나를
별도 FIELD decision record로 고른다. 그 전에는 Pilot 2 수동 import/drawing은
FIELD baseline 및 전문가 복구 경로이며 zero-touch 정상 경로가 아니다.

### D4 — artifact 변경은 항상 새 revision이다

최종 artifact의 바이트 또는 실행 의미를 바꾸는 Pilot 2 편집, Core 재생성, 외부
ingest 재업로드는 모두 다음 과정을 거친다.

```text
검증 → source/provenance 기록 → SHA-256 digest → revision 생성
   → Mission Contract 재결속·서명 → 승인/dispatch 대상으로 제시
```

이전 revision은 감사·재현용으로 보존한다. 새 revision이 준비되지 않았을 때 시스템은
변경된 파일을 조용히 이전 계약의 artifact처럼 실행 대상으로 표시하지 않는다.

### D5 — execution transport의 선택은 이 ADR의 compiler 권한과 분리한다

- 현재 기본 비행 운영·승인·이륙·중단은 Pilot 2/조종자다.
- PSDK execution은 ADR-KSI-021 C2-S0~S4의 단계와 승인·HIL 조건을 그대로 따른다.
- MSDK는 PSDK 또는 직접 transport로 닫히지 않는 명시적인 pre/postflight bridge gap에만
  검토하며, Pilot 2 대체 앱이나 Wayline mission executor가 아니다.
- Cloud, PSDK, MSDK, direct HTTPS, 수동 복구는 capability별 evidence로 선택한다.
  문서·코드 존재만으로 route를 production 활성화하지 않는다.

### D6 — 외부 artifact ingest는 validator가 먼저다

향후 `DJI_PILOT_EXPORT` ingest는 다음 최소 검증을 통과해야 한다.

- archive member 경로·크기·압축폭탄·중복/누락을 안전하게 검사한다;
- WPML 구조와 Mission Intent/FlightEnvelope의 안전 의미를 재도출해 대조한다;
- organization·site·Mission scope와 source provenance를 대조한다;
- exact bytes를 immutable object로 보관하고 digest/revision/validator version을 기록한다.

검증하지 못한 artifact는 `UNVALIDATED_EXTERNAL_ARTIFACT`로 fail-closed하며, 계약에
결속하거나 dispatch 후보로 승격하지 않는다. validator는 기존 HIL 전용 parser를
복제하지 않고, production 소유 모듈로 추출한 뒤 HIL 도구가 그것을 재사용한다.

## Consequences

- Core가 KMZ를 생성하는 현재 흐름은 유지되지만, compiler 선택은 현장 evidence로
  결정 가능한 전략이 된다.
- Pilot 2 native workflow를 받아들여도 Core policy·감사·조직 범위·digest 권한은
  약해지지 않는다.
- artifact authority를 도입하는 변경은 additive record와 dual-reader migration으로
  진행한다. 기존 `pair` record를 in-place 변경하지 않는다.
- 원본·native media와 artifact bytes는 변환해 의미를 잃지 않는다. 처리·전송 경로는
  별도의 data-egress 및 SourceMedia 정책을 계속 따른다.

## Acceptance and rollback

- Acceptance: source별 contract/replay, altered-byte/revision 거부, scope 차단, validator
  악성 archive 거부, 기존 KSI_WPML pair 호환, FIELD-0a evidence record가 필요하다.
- Rollback: 새 source ingest/selection flag만 닫고 KSI_WPML candidate와 Pilot 2
  수동 복구 경로는 남긴다. 단순 네트워크 손실 또는 route rollback으로 유효한
  활성 Mission Contract를 취소하지 않는다.
