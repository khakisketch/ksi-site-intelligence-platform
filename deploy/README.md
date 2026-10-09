# KSI Cloud deployment boundary

`KSI Cloud`는 새 `cloud/` 디렉터리나 하나의 프로세스 이름이 아니다. 이 monorepo에서
다음 세 경계를 함께 배포한 논리 제품 경계다.

| 경계 | 디렉터리 | 책임 |
|---|---|---|
| 사람용 앱 | `apps/dashboard/` | 인증된 Console·근거 조회·업무 의도 요청 |
| 서버 런타임 | `services/` | 플랫폼 Core·독립 외부 검사/측정/Analysis/공간데이터 워커와 MCP 소비자 |
| 배포 조립 | `deploy/` | 환경변수, 영속 볼륨, Core/스토리지 조립 |

공통 wire 계약과 라이브러리는 `contracts/`·`packages/`다. 과거 `edge/` 장비 출처는
`archive/acquisition-2026/edge/`에 보존하며 플랫폼 런타임이나 지시 진입점이 아니다.
따라서 플랫폼 기능을 추가할 때도 소스를 `cloud/` 아래로 복제하거나 이동하지 않는다.

`compose.yaml`의 서비스는 `init-volumes`·Core·MinIO뿐이다. NodeODM·managed Processing
Worker·DJI Gateway는 기본·VM 조합에 없다. 비행·자율 취득·고객 production 재구성은
ADR-KSI-039에 따라 플랫폼 책임 밖이다. 외부 VM
준비에는 additive `compose.vm.yaml`을 함께 사용해 Dashboard production image와 Caddy TLS
ingress를 더한다. 합친 서비스는 `init-volumes/core/minio/dashboard/caddy`다. 검사/측정/
Analysis/공간데이터 워커의 보호된 구성·활성화와 실제 운영 기동은 별도 검증 대상이다.

템플릿 편집은 기존 컨테이너를 중지하지도, 데이터를 옮기거나 볼륨을 삭제하지도 않는다.
`ksi-data`·`ksi-objects` 식별자와 서비스 설정은 보존한다. `ksi-odm`은 역사적 미사용 선언만
남기며 현재 서비스가 마운트하지 않는다. 그 볼륨에 고유한 데이터가 있을 수 있으므로 삭제/
이름 변경/자동 정리를 허용하지 않는다. 실제 이미지 빌드·기동·배포·운영 복구는 별도 승인이다.

## External reconstruction private candidate

`compose.external-reconstruction.yaml` is an additive `ksi-external-rc`
candidate. It has dedicated volumes and loopback ports and contains Core,
Dashboard, Local OIDC, MinIO and Caddy only; it has no NodeODM, ordinary worker,
DJI service, host Docker socket, or quantitative-authority fallback. Its
versioned systemd, host preflight/bootstrap and lifecycle refusal paths are in
[`external-runtime/README.md`](external-runtime/README.md). It must not be used
to mutate the existing `ksi-phase2-staging` deployment.

The candidate is intentionally activation-blocked until real release evidence,
socket ACL proof and independent external quantitative authorities are supplied.
That boundary is recorded in
[`docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md`](../docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md).

### 역사적 취득 입력 예시 — 현재 플랫폼의 사전 준비가 아님

다음은 이전 취득 팩토리의 입력 생성 예시를 보존한 것이다. 현재 플랫폼 경로는 다음 절이다.
장비 증명 파일을 복사하거나 Mission 키를 만드는 것을 정상 플랫폼 기동 요건으로 삼지 않는다.

```bash
cp .env.example .env
cp device-attestation-keys.example.json device-attestation-keys.json
```

두 생성 파일은 git에 포함되지 않는다. `.env`에는 token 원문이 아니라 Core가 검증할
digest만 두며, `device-attestation-keys.json`에는 Manifold 공개키만 둔다. 실제 장비
개인키, 토큰 원문, Core 서명 개인키를 이 두 예제에 기록하지 않는다.

### Platform Core boot (normal profile)

정상 부팅 프로파일은 `ksi_core.composition.platform_production:
build_platform_production_app` 이다(Docker 이미지 CMD·CI 스모크 동일). 필수
입력은 다음 실제 팩토리의 데이터·S3·principal·인증 설정이다. 예제만 복사해 운영 준비가
완료되는 것은 아니다. [현재 기동 요건](../docs/ops/DEPLOYMENT.md)을 함께 확인한다.

| 필수 | 설명 |
|---|---|
| `KSI_CORE_DATA_DIR` | 원장(append-only journal) 영속 디렉터리 |
| `KSI_CORE_S3_ENDPOINT` / `KSI_CORE_S3_BUCKET` | 증거·산출물 객체 저장소 |
| `KSI_CORE_PRINCIPAL_TOKENS_JSON` | 비어 있지 않은 digest 전용 principal 목록; 실제 권한/수명/조직 범위는 별도 |
| `KSI_CORE_HUMAN_AUTH_MODE`와 issuer/audience/JWKS | 사람 인증이 DUAL/OIDC 일 때; VM은 OIDC |
| `KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE` | DUAL/OIDC에서는 보호된 subject 등록 파일까지 필수; issuer/JWKS만으로 기동하지 않음 |

선택 업무 구성은 서명된 Analysis 3종
(`KSI_CORE_ANALYSIS_RUNTIME_CONFIG_FILE`·`KSI_CORE_ANALYSIS_ACTIVATION_FILE`·
`KSI_CORE_ANALYSIS_ACTIVATION_KEYS_FILE`, 전부 아니면 전무)과 외부 권한 쌍
(`KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG`·
`KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG`, 함께 아니면 전무)다. Analysis 활성화에는
등록된 `ANALYSIS_WORKER`가 정확히 하나여야 한다. 경로를 채우는 것만으로 신뢰·권리·
worker 기동이 생기지 않는다. 나머지 로그/저널/공개 S3 등의 기존 옵션은 실제 팩토리를 따른다.
보호된 파일의 안전한 공급/접근 경로는 운영 입력으로 따로 검증해야 하며, 이 템플릿 변경이
파일·자격·마운트·워커 서비스를 추가하지 않는다.

현재 production 팩토리는 `spatial_data`를 주입하지 않는다. 실제 로컬 공간데이터 조립은
`SpatialDataLocalAssemblyConfig`를 명시하는 별도 경로다. 이 구성 정리로 새 production
환경변수나 활성화 기능이 생겼다고 간주하지 않는다.
플랫폼 부팅은 Mission 서명키 디렉터리(`KSI_CORE_SIGNING_KEYS_DIR`)와 장비 증명
파일(`KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE`)을 요구하지도 읽지도 않으므로
`compose.yaml` core 서비스는 그 둘을 마운트하지 않는다. 레거시 팩토리
(`ksi_core.production:build_production_app`)는 P3 Task 5에서
`archive/acquisition-2026/` 으로 은퇴했으므로(플랫폼 팩토리
`ksi_core.composition.platform_production:build_platform_production_app` 가
정상 부팅 경로) `.env.example` 의 서명키·증명 관련 주석과
`device-attestation-keys.example.json` 은 레거시 기록으로 유지된다.

### 역사적 취득 설정과 출처 — 현재 플랫폼 설정/활성화 절차가 아님

아래는 은퇴한 취득 팩토리의 설정/안전 경계를 보존한다. 활성 플랫폼 조립이나 장비 운영의
지시 진입점이 아니며, archived runner/config는 역사적 증거로만 읽는다.

Acquisition coordinator는 `KSI_CORE_ACQUISITION_COORDINATION_ENABLED=true`가 기본이며,
문제가 생기면 이 flag만 내려 기존 Mission/KMZ와 수동 ingest 경로를 보존할 수 있다.
새 Mission 발급 gate의 안전한 기본값은
`KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=false`, Mission Contract writer는 `1.2`다.
RC 기본형 HIL과 Site profile migration이 끝나기 전에는 이 기본값을 바꾸지 않는다.
CAP-5 runtime route projection도 exact TTL과 refresh margin을 포함한 freshness policy
registry `{}`와 trusted route
configuration `[]`가 기본이라 fail-OFF다. CAP-4 activation, exact current observation,
Mission policy가 모두 충족되기 전에는 신규 route invocation을 허용하지 않는다.

HIL-0의 Gateway runner(`ksi-dji-gateway --config ...`)와 그 빌드 입력
(`Dockerfile.gateway`)·설정 예시(`gateway.config.example.json`)는 P3 Task 6에서
`archive/acquisition-2026/` 으로 blob-identical 이동했다(historical, 제품 지원
아님). 기본 Compose에는 Gateway가 없으며(아래 deploy contract가 단정한다),
`EDGE_ROUTE_OBSERVER` journal 호환성(다음 절)은 보존된 역사적 reader/replay 범위이며
현재 플랫폼에 observation mutation/dispatch 경로가 있다는 뜻이 아니다. 아카이브된 runner 예시의 credential 분리 형태는
`archive/acquisition-2026/deploy/gateway.config.example.json` 원본을 보라.

### Historical EDGE_ROUTE_OBSERVER journal compatibility and rollback

이 절은 역사적 producer/reader의 호환성·안전 조건이다. 현재 플랫폼에서 observer를
provisioning하거나 Gateway를 restart하라는 지시가 아니며 기존 기록을 재작성할 권한도 없다.

PSDK route observation은 `EDGE_ROUTE_OBSERVER`의 전용 token으로만 연다. 기본 예제는
그 principal이나 token을 provisioning하지 않으며, 기존 Gateway/Edge producer가 쓰는
observation journal record는 schema `1.0`을 유지한다. observer record만 schema `1.1`이다.
활성화 전에 먼저 `1.0`과 observer `1.1`을 모두 replay할 수 있는 compatible Core reader를
배포하고, immutable observation journal의 복구 가능한 backup을 확인한다. 그 다음에만
새 observer principal/token digest와 owner-only token file을 명시적으로 provisioning하고
Gateway observation 설정을 그 dedicated file로 바꾼다. `EDGE_DEVICE` 또는 Gateway token을
observer fallback으로 사용하면 안 된다.

첫 `1.1` observer record가 durable journal에 기록되면 reader floor는 `1.1`이다. 그 뒤에는
old Core를 journal 위로 rollback/restore할 수 없다. backup은 disaster recovery용이며
post-`1.1` journal을 truncate, delete, rename, rewrite할 권한을 주지 않는다.

안전한 rollback은 observer publishing을 멈추고, observer 전용 startup configuration을
제거하거나 token을 rotate한 뒤 Gateway를 restart하는 것이다. 별도 in-product revocation API를
가정하지 않는다. compatible Core reader와 전체 immutable journal은 유지하며, observer
principal/token을 없앤다고 legacy producer record를 삭제하거나 broad Edge token으로 바꾸지
않는다.

외부 VM profile은 `docs/ops/VM_DEPLOYMENT_READINESS.md`를 따른다. 현재 release gate는
개발·합성 데이터까지이며, Cloud 사업자 적법성 승인과 실제 고객 데이터 배포는
`docs/security/CLOUD_PROVIDER_DUE_DILIGENCE.md`가 열려 있는 동안 금지다.

## Historical optional grounded Copilot — evidence only

아래 overlay/활성화 설명은 이전 팩토리의 기록이다. 현재 플랫폼 부팅에서 검증된 Copilot
활성화 경로가 아니며 이 명령으로 구성/신뢰/권한이 생기지 않는다. 새 모델 호출·활성화는 별도 범위다.

현장 AI는 기본 compose에 포함되지 않는다. 승인된 OpenAI-compatible provider를
합성 데이터로 검증할 때만 additive overlay를 사용한다.

```bash
docker compose -f compose.yaml -f compose.copilot.yaml config
```

`KSI_COPILOT_ENABLED`의 기본값은 `false`다. 활성화할 때는 base URL, model,
timeout, planner/model version을 명시하고 API key는
`KSI_COPILOT_API_KEY_FILE`이 가리키는 secret file로만 공급한다. 외부 모델에는
원본 사진, presigned URL, 임의 object key를 보내지 않으며 Site의
`aiEgressAllowed`가 명시적으로 켜져 있지 않으면 Core가 호출을 거부한다.

Provider 연결이나 저장형 대화가 실패해도 기존 현장 결과·작업·보고서와 사람 승인
흐름은 계속 동작해야 한다. 실제 고객 데이터 호출은 Cloud 위탁·국외이전·보존
승인 전까지 금지한다.

## Phase 2 synthetic staging on DGX Spark

역사적 staging 경로/증거를 보존한다. 아래 lifecycle·backup/restore 스크립트는 현재 플랫폼
팩토리로 재검증되지 않았으며 정상 기동/복구 지침으로 실행하지 않는다. 이 문서 변경은
그 stack을 재시작/삭제하거나 새 운영 배포를 승인하지 않는다.

외부 사업자와 실제 모델을 승인하기 전에는 독립 `compose.synthetic-staging.yaml`로
production Dashboard/Core 경계를 합성 데이터에만 적용한다. 이 조합에는 worker,
NodeODM, DJI Gateway, Manifold, 장비 key 또는 비행 행동이 없다.

Identity, 합성 Copilot, Core, Dashboard는 non-root 이미지에 읽기 전용 root filesystem,
`cap_drop: ALL`, `no-new-privileges`를 적용한다. 기존 named state volume과 읽기 전용
secret mount는 유지한다. 임시 쓰기는 각 컨테이너의 64 MiB `/tmp`와 Dashboard의
256 MiB `/app/.next/cache` tmpfs로 제한하며 모두 `noexec,nosuid,nodev`다. 캐시는
재기동 때 사라지는 비권위 데이터다. 이 한도는 합성 staging 설정이며 고객 파일 처리
용량이나 production 수용 증거가 아니다. MinIO와 초기화 작업의 권한 모델은 별도다.

```bash
deploy/bin/phase2-staging.sh start
deploy/bin/phase2-staging.sh status
deploy/bin/phase2-staging.sh verify
```

`start`는 owner-only ignored env를 생성하고 전용 volume을 초기화한 뒤 Local Identity,
MinIO, deterministic OpenAI-compatible fixture, Core, Dashboard를 시작한다. 모든 host port는
loopback이며 Tailscale Serve가 아래 Tailnet HTTPS만 연다.

| Surface | Port |
|---|---:|
| Console | 10000 |
| Synthetic Identity | 10001 |
| Core API | 10002 |
| Object API | 10003 |

MinIO console `10004`는 loopback 전용이다. `verify`는 live smoke 뒤 Core/Dashboard를 통제
중지하고 journal/object/signing key bundle을 만든 다음 고유한 격리 volume에 복원하고
서비스를 재기동한다. `stop`은 네 staging Serve port만 해제하며 volume을 보존한다.
`reset`만 staging container와 다섯 전용 volume을 제거한다. 기존 3210/8012/9010 개발
stack과 다른 Serve port는 변경하지 않는다.

이 profile의 AI 서비스는 외부 네트워크 client가 없는 합성 fixture다. production adapter,
tool/citation validation, timeout/provider failure 경로를 실행하기 위한 것이며 실제 외부 AI
승인 증거가 아니다. 상세 수용 경계는
`docs/acceptance/SYNTHETIC_CLOUD_AI_STAGING_ACCEPTANCE.md`에 기록한다.
