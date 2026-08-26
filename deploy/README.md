# KSI Cloud deployment boundary

`KSI Cloud`는 새 `cloud/` 디렉터리나 하나의 프로세스 이름이 아니다. 이 monorepo에서
다음 세 경계를 함께 배포한 논리 제품 경계다.

| 경계 | 디렉터리 | 책임 |
|---|---|---|
| 사람용 앱 | `apps/` | Dashboard, Field Web, 운영 승인 |
| 서버 런타임 | `services/` | Core, Processing, DJI integration gateway |
| 배포 조립 | `deploy/` | 환경변수, 영속 볼륨, Core/worker/스토리지 조립 |

공통 wire 계약과 라이브러리는 `contracts/`·`packages/`, 현장 장비 런타임은
`edge/`에 남는다. 따라서 KSI Cloud 기능을 추가할 때도 소스를 `cloud/` 아래로
복제하거나 이동하지 않는다.

`compose.yaml`은 Core·Processing Worker·MinIO·NodeODM 로컬 최소 조합이다. 외부 VM
준비에는 additive `compose.vm.yaml`을 함께 사용해 Dashboard production image와 Caddy TLS
ingress를 더한다. DJI Gateway는 RC 기본형 HIL에서 실제 adapter가 선택된 뒤에만
runner/Dockerfile/service를 추가한다. HIL 전 빈 Gateway 컨테이너나 가짜 장비 상태는
어느 조합에도 넣지 않는다.

최초 실행 전:

```bash
cp .env.example .env
cp device-attestation-keys.example.json device-attestation-keys.json
```

두 생성 파일은 git에 포함되지 않는다. `.env`에는 token 원문이 아니라 Core가 검증할
digest만 두며, `device-attestation-keys.json`에는 Manifold 공개키만 둔다. 실제 장비
개인키, 토큰 원문, Core 서명 개인키를 이 두 예제에 기록하지 않는다.

Acquisition coordinator는 `KSI_CORE_ACQUISITION_COORDINATION_ENABLED=true`가 기본이며,
문제가 생기면 이 flag만 내려 기존 Mission/KMZ와 수동 ingest 경로를 보존할 수 있다.
새 Mission 발급 gate의 안전한 기본값은
`KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED=false`, Mission Contract writer는 `1.2`다.
RC 기본형 HIL과 Site profile migration이 끝나기 전에는 이 기본값을 바꾸지 않는다.

외부 VM profile은 `docs/ops/VM_DEPLOYMENT_READINESS.md`를 따른다. 현재 release gate는
개발·합성 데이터까지이며, Cloud 사업자 적법성 승인과 실제 고객 데이터 배포는
`docs/security/CLOUD_PROVIDER_DUE_DILIGENCE.md`가 열려 있는 동안 금지다.

## Optional grounded Copilot

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

외부 사업자와 실제 모델을 승인하기 전에는 독립 `compose.synthetic-staging.yaml`로
production Dashboard/Core 경계를 합성 데이터에만 적용한다. 이 조합에는 worker,
NodeODM, DJI Gateway, Manifold, 장비 key 또는 비행 행동이 없다.

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
