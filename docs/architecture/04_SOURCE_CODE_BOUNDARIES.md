# KSI Source Code Boundaries

Status: ACCEPTED — 2026-08-21
Scope: RC-first Connected Edge 및 향후 Dock adapter 확장

> **2026-09-04 repository routing:** 전체 저장소 owner/purpose/runtime 표의 정본은
> [`../../REPOSITORY_STRUCTURE.md`](../../REPOSITORY_STRUCTURE.md)다. 이 문서는 Connected Edge
> 소스 의존 방향을 상세화하며, 이름이 비슷한 runtime module을 합치거나 지울 권한이 아니다.

## 선택

KSI는 장비별 최상위 복제도, 기술 계층만으로 된 전역 분리도 사용하지 않는다.
제품 책임을 bounded context로 나누고 외부 장비 차이는 adapter로만 격리하는
하이브리드 구조를 사용한다.

## 검토한 대안

| 방향 | 장점 | 장기 문제 | 판정 |
|---|---|---|---|
| 장비별 최상위(`rc/`, `manifold/`, `dock/`) | 실물 담당자가 위치를 빨리 찾음 | 계약·동기화·보안 규칙이 장비마다 복제되고 Dock 추가 때 분기 증가 | 불채택 |
| 하나의 Integration 서비스에 모두 배치 | 초기 파일 수가 적음 | 정책, SDK, journal, UI projection이 한 모듈에 결합 | 기존 facade에만 한정 |
| 서비스별 별도 repository | 배포·권한 격리가 강함 | 현재 규모에서 계약 변경·테스트·버전 조율 비용이 큼 | 상용 팀 분리 시 재검토 |
| 책임별 context + 장비 adapter | 공통 제품 규칙을 한 번만 구현하고 장비 교체를 격리 | port/contract 규율을 지켜야 함 | **채택** |

현재 단계에서는 monorepo를 유지한다. 독립 배포 주기·접근권한·팀 소유권이 실제로
갈라질 때만 repository 분리를 검토하며, 디렉터리를 미래 조직도처럼 미리 쪼개지 않는다.

`KSI Cloud`는 물리 디렉터리가 아니라 `apps/ + services/ + deploy/`를 묶은 논리적
배포 경계다. 공통 계약은 `contracts/ + packages/`, 현장 장비는 `edge/`가 소유한다.
따라서 `cloud/` 폴더를 새로 만들지 않고 아래 책임 경계를 유지한다.

```text
contracts/                         wire contract와 API 정본
packages/                          서비스 비종속 domain/contract 라이브러리
services/core/                     정책·신원·Site·WorkOrder·Mission·readiness
  src/ksi_core/acquisition/        Profile / Snapshot / readiness bounded context
                                    AcquisitionRun / operation receipt / progress
services/dji-gateway/              RC/Dock/Edge 연결·전송 adapter 경계
  src/ksi_dji_gateway/domain/      capability·transport·요청·receipt
  src/ksi_dji_gateway/ports/       기능별 좁은 SPI
  src/ksi_dji_gateway/routing/     capability별 route 선택
  src/ksi_dji_gateway/persistence/ receipt/idempotency journal
edge/manifold-runtime/             로컬 지능·계약 activation·outbox
edge/psdk-app/                     실제 PSDK application composition
edge/psdk-tap/                     HIL 관측·증거 수집 도구
edge/msdk-field-bridge/            pre/postflight-only MSDK native contract candidate
apps/dashboard/                    사람의 업무·readiness·복구 UI
services/processing-controller/    분석 job orchestration·artifact worker
services/change-detection/         변화·체적 계산 leaf service/library
services/bim-integration/          IFC 변환·참조모델 leaf service/library
services/defect-detection/         결함 model adapter·후처리 leaf service/library
packages/perception/               recorded/offline model evaluation·공유 perception logic
deploy/                            KSI Cloud 환경·영속 볼륨·runtime 조립
```

`edge/**/build*`는 로컬 빌드 산출물이며 source boundary가 아니다. `.gitignore`로
신규 추적을 막되, 기존 로컬 산출물은 자동 삭제하지 않는다.

## 의존 방향

```text
contracts/packages
      ↑
Core domain/API       DJI Gateway domain/ports
      ↑                         ↑
Dashboard client       verified device adapters
                                ↑
                   RC / PSDK / Direct / MSDK / Dock SDK
```

- Core는 DJI SDK나 adapter 구현을 import하지 않는다.
- Gateway domain·routing·persistence는 특정 DJI SDK를 import하지 않는다.
- adapter는 Core 내부 store를 import하지 않고 계약/API를 통해서만 통신한다.
- Manifold runtime은 서버 연결이 없어도 이미 활성화된 Mission Contract와 로컬
  outbox를 유지한다.
- Dashboard는 장비별 SDK 상태를 해석하지 않고 Core의 readiness projection만 읽는다.

## Gateway port와 장비 adapter

| 책임 | Port | 예상 adapter | 비고 |
|---|---|---|---|
| Wayline 전달 | `MissionDeliveryPort` | RC Cloud, Dock Cloud | 새 임무 발급 전 verified 필요 |
| Mission Contract 하향 전달 | `EdgeDispatchPort` | Pilot Cloud, 조건부 MSDK/MOP, direct Edge | 비행 제어 API 금지 |
| Edge 결과 업링크 | `EdgeUplinkPort` | Pilot Cloud, Manifold direct | 동일 idempotency key/digest |
| 미디어 회수·업로드 | `MediaTransferPort` | RC/Dock media, Manifold direct, 조건부 Bridge | 원본 completeness 별도 검증 |

한 adapter가 여러 port를 구현할 수는 있지만, router에는 port capability별로 등록한다.
“provider 하나가 선택되었으므로 모든 기능 지원”이라는 판정은 금지한다.

## 새 기능 배치 규칙

1. 제품 정책·조직 scope·Mission 발급 조건이면 Core bounded context에 둔다.
2. 장비/SDK별 전달 방식이면 Gateway adapter에 둔다.
3. 비행 중 로컬 인지·추적·품질·위험 판단이면 Manifold runtime에 둔다.
4. 비행 안정화·reactive avoidance·RTH는 DJI Flight Controller 소유로 남긴다.
5. 운영자 상태 표시와 pre/postflight action만 Dashboard에 둔다.
6. 실제 장비 구현이 없어도 fail-closed candidate adapter는 만들 수 있지만 빈 성공
   구현과 mock fallback은 금지한다. 코드·SDK build와 무관하게 capability는 실제
   path/hardware/firmware evidence 전까지 `NOT_VERIFIED`로 유지한다.

## 변경 안전장치

- `gateway.py` facade와 journal v1.2 reader는 migration 동안 유지한다.
- 기존 facade는 v1.2 receipt로 rollback 호환성을 유지한다. 새 capability 경로는
  capability·transport가 모두 명시된 경우에만 v1.3 receipt를 쓴다.
- capability별 feature flag는 누락 시 OFF다.
- MSDK Bridge와 Dock candidate adapter의 사전 구현은 허용하되 runtime route 등록과
  flag 활성화는 해당 path의 HIL evidence 전에는 금지한다.
- manual KMZ와 ground ingest recovery 경로는 제거하지 않는다.
