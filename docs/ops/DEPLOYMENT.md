# 플랫폼 배포 템플릿 (Core · MinIO · 볼륨 초기화)

> 이 문서가 있기 전에는 이 시스템을 띄우려면 `production.py` 를 읽어야만 무엇을
> 채울지 알 수 있었다. 저장소에 compose·env 예제가 하나도 없었다.
>
> 현재 기동 입력은 `services/core/src/ksi_core/composition/platform_production.py`와
> `runtime_config.py`를 따른다. 예전 `production.py`/managed `runner.py` 설명은 아래
> 역사적 기록이며 현재 owner/기동 지침이 아니다. 제품 요구사항의 권위는 `docs/00_READ_FIRST.md`다.
> Dashboard+Caddy 외부 VM 조립은 `VM_DEPLOYMENT_READINESS.md`가 별도로 소유한다.
>
> **사람의 로컬 Console 로그인은 이 compose가 아니라 `apps/dashboard`의 `npm run dev`를
> 사용한다.** 그 표준 경로는 loopback OIDC Authorization Code + PKCE를 실제로 거치며
> Bearer 토큰을 붙여넣지 않는다. 이 문서의 opaque token은 Core 저수준 API 진단과
> 승인된 비사람 principal의 저수준 자격이다. Gateway·Edge는 취득 전용 역사적 범위다. 외부 VM의 사람
> 로그인도 OIDC만 허용한다.

## 현재 플랫폼 경로와 실제 준비 조건

- Base `deploy/compose.yaml`: `init-volumes/core/minio`. VM overlay를 합치면
  `init-volumes/core/minio/dashboard/caddy`다. NodeODM·managed 재구성 워커·장비 서비스는 없다.
- 이미지 CMD는 `ksi_core.composition.platform_production:build_platform_production_app`다.
  템플릿은 독립 외부 검사/측정/Analysis/공간데이터 워커나 그 권한·활성화를 생성하지 않는다.
- `ksi-data` 원장과 `ksi-objects` 객체 저장소의 기존 볼륨 식별자는 그대로다. `init-volumes`는
  Core의 uid10001 원장 소유권만 초기화한다. `ksi-odm`은 마운트되지 않는 역사적 선언이다.
  고유한 데이터가 있을 수 있으므로 캐시라고 추정해 삭제하거나 이름을 바꾸지 않는다.
- Base의 Core8000/MinIO9000·9001은 loopback이다. TLS/Dashboard는 VM overlay의 별도
  준비 조건이며 공개되는 것은 Caddy80/443뿐이다. 공개망 배포/DNS/실제 기동은 별도 승인이다.

| 현재 입력 | 조건 / 준비 책임 |
| --- | --- |
| `KSI_CORE_DATA_DIR` | 기존 영속 디렉터리; 컨테이너 원장 마운트와 uid 접근을 실제로 검증 |
| `KSI_CORE_S3_ENDPOINT` / `KSI_CORE_S3_BUCKET` | 실제 저장소와 bucket; MinIO 자격·접근/보존은 별도 운영 입력 |
| `KSI_CORE_PRINCIPAL_TOKENS_JSON` | 비어 있지 않은 digest 전용 목록; 조직/권한/수명과 원문 보호를 별도 확인 |
| DUAL/OIDC 설정 | issuer/audience/JWKS와 **보호된 `KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE`**까지 필수; JWT 설정만으로 부팅 불가 |
| F-01 bootstrap 상한(선택) | `KSI_CORE_SITE_BOOTSTRAP_MAX_SITES_PER_ORG` — 미설정 기본 1,000. 1 이상 정수만; 0·음수·비정수는 부팅 실패 |
| Analysis 선택 구성 | runtime/activation/검증키 3파일 전부 아니면 전무; 등록된 `ANALYSIS_WORKER` 정확히 하나 필요 |
| 외부 workflow 선택 구성 | `KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG`와 `KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG` 함께 아니면 전무 |

### OIDC subject registry v1/v2 — F-01 발급·회수 지침

- v1(기존 문법): 두 scope 필드가 필수 배열. v2: 필수 `capabilities` + 두 scope 필드 **필수**
  (명시 `null` = KSI가 별도 발급한 자기 조직 전체, 배열 = 명시 목록, 빈 배열 = 접근 없음).
  필드 누락·invalid·미지원 버전은 로드 실패이며 누락이 null(전체)로 승격되지 않는다 — v2 실패 후
  v1 재시도도 없다.
- 발급 짝: `SITE_BOOTSTRAP`은 원칙적으로 org 전체 scope(`null`)와 함께 발급하고, org 전체 scope는
  본사 관리자급(ADR-KSI-015 매핑)에게 발급한다. capability와 scope는 **분리된 발급 결정**이다 —
  생성 행위는 scope를 넓히지 않는다(per-site grant 레코드 없음). explicit site 목록과 함께
  발급하면 새 Site는 재발급 전까지 생성자에게도 보이지 않는다(계약상 허용, lockout을 숨기지 않음).
- 변경·회수: registry 파일 교체 + **재시작/재배포**가 반영 시점이다(부팅 시 1회 로드 — 파일만 바꾼
  실행 중 프로세스는 이전 snapshot을 유지한다). 회수는 재발급(범위 축소) 또는 `REVOKED`(신원
  전체). org 전체 모드에는 개별 site 제외 표현이 없다 — 필요하면 explicit 목록으로 전환한다.
  DUAL에서 별도 opaque 자격이 남아 있으면 그것은 OIDC 회수가 아니다(별도 발급 상태 기록).
- rollback: v1 명시 배열 전환은 승인된 실제 최소권한 목록만 담고, 한 필드 512개/파일 크기 한계를
  넘으면 **자르지 않고 실패**한다. wildcard를 v1로 표현할 수 없으면 compatible reader와 v2 scope를
  유지한 채 capabilities만 빈 배열로 재발급해 생성만 회수한다(wildcard scope rollback 완료를
  주장하지 않는다). 새 journal binding을 읽는 리더 호환 증거 없이는 코드 downgrade를 하지 않는다.
- 교차 조직 중복: legacy opaque 경로는 client 지정 siteId의 동일 409 응답 계약을 유지한다(호환 —
  전역 존재 oracle 잔여 위험은 F-01 기록에 남는다). 신규 v2 bootstrap은 서버 발급 ID라 이 경로가
  없고, 재시도가 scope 밖이면 미지 Site와 같은 404로 접힌다.
- opaque `KSI_CORE_PRINCIPAL_TOKENS_JSON`은 capability 발급 표면이 아니다 — `registryScoped`/
  `capabilities` 예약 필드 주입은 부팅 실패다. 새 MCP/endpoint는 없다.

기존 로그·저널·공개 S3 등의 옵션은 실제 팩토리를 따른다. 이 문서는 새 자격/정책을 발급하거나
보호된 파일의 마운트·공급 경로를 추가하지 않는다. 예제 `.env.example`에는 취득 관련 역사적
필드도 있으므로 복사만으로 현재 production 설정이 완성됐다고 보지 않는다. Mission 서명키와
device attestation 파일은 플랫폼 부팅이 요구하지도 마운트하지도 않는다.

현재 production 팩토리는 `spatial_data`를 주입하지 않는다. 실제 공간데이터 로컬 조립은
`SpatialDataLocalAssemblyConfig`를 명시하는 별도 경로이며 새 환경변수 스위치로 대체하지 않는다.
보호된 데이터/Analysis 구성이 없다는 F02–03 한계는 이 템플릿 변경으로 닫히지 않는다.

현재 템플릿/기동 조건의 연결은 [deploy 안내](../../deploy/README.md)와
[VM 준비 경계](VM_DEPLOYMENT_READINESS.md)에 있다. 준비된 도구의 `compose config`는
구문/병합 검증일 뿐 이미지 빌드·기동·권한·저장·복구나 고객 수용의 증거가 아니다.
템플릿 편집은 이미 실행 중인 컨테이너를 중지하지 않으며 볼륨을 삭제/이전하지 않는다.
fresh sync/image/boot/CI와 production TLS/UDS/ACL/host 증거는 별도 승인·검증까지 미확인이다.

## 이 배포가 뜨지 않는 것은 정상이다

Core 는 필수 환경변수가 하나라도 없거나 형식이 틀리면 **기동을 거부한다**(`RuntimeError`).
무엇도 조용히 기본값으로 대체하지 않는다 — 조용한 기본값의 종착지가 "인증 없이 뜬
프로덕션 서버"이기 때문이다. 그래서 첫 배포에서 죽는 것은 실패가 아니라 설계대로다.
로그가 **어느 변수가 왜 문제인지** 말해준다.

---

# 역사적 취득/managed 운영 기록 — 현재 플랫폼 기동/복구 지침이 아님

아래 §1–9는 이전 조합의 입력·서명·취득·재구성·복구 절차를 출처와 함께 보존한다.
과거의 signing-key 바인드, managed worker/NodeODM, device attestation, CAP-5 설명을
현재 base/VM 구성에 적용하지 않는다. 관련 sources는 은퇴했으며 플랫폼 runtime import/
빌드 입력/지시 진입점이 아니다. 아래 명령을 현재 서비스에서 실행하도록 승인하지 않는다.
기존 backup/restore/staging 도구도 현재 플랫폼에서 재검증된 복구 경로로 간주하지 않는다.
특히 역사적 캐시 분류는 현존 볼륨의 고유 데이터나 원본을 삭제할 근거가 아니다.

## 1. 준비물

| 항목 | 왜 필요한가 |
|---|---|
| Docker + Docker Compose | 아래 compose 가 Core·워커·MinIO·NodeODM 을 함께 띄운다 |
| 영속 저장소 2곳 | 원장은 명명 볼륨 `ksi-data`, 서명키는 **호스트 디렉터리 `deploy/signing-keys/`**(볼륨이 아니다 — §2). **이 둘이 백업 대상이다**(§8) |
| Mission Contract 서명키 | Core 는 키를 만들지 않는다 — 미리 만들어 둬야 한다(§2) |
| opaque 접근 토큰 | 저수준 Core 진단과 Gateway·Edge·worker가 Core 를 부를 자격증명(§3) |
| (선택) 지오이드 격자 | 해발 기준 설계도면을 받으려면 필요(§4) |
| (선택) 동적 객체 마스킹 모델 | 재구성 산출물에서 사람·차량을 지우려면 필요 — 기본은 꺼짐(`deploy/.env.example` 의 `KSI_WORKER_DYNAMIC_OBJECT_MODEL_DIR`, `tools/fetch_model.py` 로 받는다) |

## 2. 서명키 먼저 만든다

**Core 는 서명키를 부트스트랩하지 않는다.** 컨테이너는 재생성되는 존재인데(롤링 배포·
재스케줄) 재생성마다 새 키가 생기면, 이미 현장에 발급된 Mission Contract 가 서버 재시작
한 번으로 전부 검증 실패한다. 그건 이 제품의 근본 전제(서버가 죽어도 로컬에서 유효한
계약은 유효하다)를 정면으로 어긴다. 그래서 키는 **컨테이너 밖에 살고 Core 는 읽기만 한다.**

**위치가 정해져 있다 — `deploy/signing-keys/`** 다. compose 가 이 디렉터리를 그대로
컨테이너 안 `/var/lib/ksi/signing-keys` 로 읽기전용 바인드한다(`deploy/compose.yaml`).
다른 곳에 만들면 Core 는 그 키를 볼 수 없다.

```bash
cd deploy
mkdir -p signing-keys && cd signing-keys
KEY_ID="core-$(date +%Y-%m)"
openssl genpkey -algorithm ed25519 -out "$KEY_ID.private.pem"
chmod 600 "$KEY_ID.private.pem"
openssl pkey -in "$KEY_ID.private.pem" -pubout -out "$KEY_ID.public.pem"
```

`keys.json` 매니페스트를 같은 디렉터리에 만든다(형식과 회전 절차는
`docs/security/SIGNING_KEY_LIFECYCLE.md` 가 정본):

```json
{
  "active": "core-2026-08",
  "keys": [{ "keyId": "core-2026-08", "status": "ACTIVE" }]
}
```

필드 이름은 `keyId` 다(`id` 가 아니다). `status` 는 생략하면 `ACTIVE`,
`notAfter` 는 주면 tz-aware ISO 8601 이어야 한다.

Core 는 기동 시 이 매니페스트를 검증한다 — 활성 키가 REVOKED 이거나, 개인키와 공개키가
어긋나거나, 개인키 권한이 느슨하면(`chmod 600` 안 했으면) **기동을 거부한다.**

마지막으로 **소유자를 컨테이너의 uid 로 넘긴다.** Core 는 uid 10001 non-root 로 도는데
개인키는 `0600`(소유자만 읽기)이라 파일 소유자가 10001 이 아니면 읽지 못한다. 권한을
느슨하게 푸는 길은 없다 — 로더가 그룹·타인 비트를 거부한다(위 문단). 소유자를 옮기는
것이 유일한 방법이다.

```bash
cd ..                                     # deploy/
docker run --rm -v "$PWD/signing-keys":/mnt busybox:1.36@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662 chown -R 10001:10001 /mnt
```

`sudo chown -R 10001:10001 signing-keys` 도 같은 결과다. 위 형태를 기본으로 두는 이유는
호스트 root 권한 없이 docker 만으로 되기 때문이고, `init-volumes` 가 볼륨에 하는 일과
같은 방식이다.

**이 뒤로는 키 파일을 사람 계정으로 못 읽고 그 디렉터리에 새 파일도 못 만든다** —
디렉터리 자체의 소유자가 10001 로 바뀌었기 때문이다. 의도된 결과다(키를 아무나 읽을 수
있으면 서명 신뢰가 무너진다). 다만 **키 회전은 그 디렉터리에 새 파일을 만드는 일**이므로,
회전할 때 무엇을 실행해야 하는지를 아래에 못박아 둔다.

### 2-1. 회전·백업 — 소유권을 잠시 되돌린다

회전 절차 자체(새 키쌍 → `keys.json` 갱신 → 이전 키 `notAfter` → 재기동 → 파기)의 정본은
`docs/security/SIGNING_KEY_LIFECYCLE.md` 다. 이 compose 배포에서는 **그 절차 앞뒤로 소유권
전환을 한 번씩 감싼다.**

```bash
cd deploy
UID_ME=$(id -u); GID_ME=$(id -g)

# 1) 작업 전 — 내 계정으로 되돌린다
docker run --rm -v "$PWD/signing-keys":/mnt busybox:1.36@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662 chown -R "$UID_ME:$GID_ME" /mnt

# 2) SIGNING_KEY_LIFECYCLE.md §회전 1~3 을 signing-keys/ 안에서 그대로 실행
#    (새 키쌍 생성 · chmod 600 · keys.json 의 active 교체 · 이전 키 notAfter 부여)

# 3) 작업 후 — 다시 컨테이너 uid 로 넘긴다
docker run --rm -v "$PWD/signing-keys":/mnt busybox:1.36@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662 chown -R 10001:10001 /mnt

# 4) Core 재기동 — 기동 시 매니페스트가 재검증된다
docker compose up -d --force-recreate core
```

백업도 같은 이유로 1) 을 먼저 하거나, 되돌리지 않고 `docker run --rm -v
"$PWD/signing-keys":/mnt busybox:1.36@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662 tar -cf - -C /mnt .` 로 컨테이너를 통해 읽는다.

**3) 을 빼먹으면 재기동한 Core 가 키를 못 읽고 기동을 거부한다** — 조용히 옛 키로 도는
일은 없다(§7 표의 "권한 거부" 행).

## 3. 장비·worker opaque 접근 토큰 — 원문은 서버에 두지 않는다

Core 는 토큰 **원문을 모른다.** `sha256` digest 만 갖는다. 그래서 프로세스 메모리·로그·
환경변수 어디에도 원문이 존재하지 않는다.

```bash
# Core 저수준 관리자 진단용 — Operations Console 사람 로그인에는 쓰지 않는다.
ADMIN_TOKEN=$(openssl rand -hex 32)
printf '%s' "$ADMIN_TOKEN" | sha256sum | awk '{print $1}'   # ← 이 digest 를 Core 에 준다
# 워커용
WORKER_TOKEN=$(openssl rand -hex 32)
printf '%s' "$WORKER_TOKEN" | sha256sum | awk '{print $1}'
```

`awk '{print $1}'` 를 빼먹지 않는다 — `sha256sum` 은 `<64자리hex>  -` 형태로 뒤에 공백과
대시를 붙여 출력하고, 그걸 그대로 넣으면 Core 가 `tokenSha256 은 소문자 64자리 hex 여야
한다` 로 기동을 거부한다.

- **digest** 는 `KSI_CORE_PRINCIPAL_TOKENS_JSON` 에 넣는다(Core 쪽).
- **원문** 은 사용자에게 전달하고, 워커 것은 `KSI_WORKER_CORE_TOKEN` 에 넣는다.

회전은 같은 `principalId` 로 이전 digest(`notAfter` 로 유예기간 종료 시각)와 새
digest(`notAfter` 없음)를 **함께** 배포한다 — `docs/security/AUTH_TOKEN_ROTATION.md`.

## 4. (선택) 해발 기준 설계도면을 받으려면

`KSI_GEOID_GRID` 를 국가 지오이드 격자 파일로 지정한다. 저장소에 함께 있다
(`data/geoid/KNGeoid24.tif`, 취득·검증 기록은 `docs/geo/GEOID_ACQUISITION.md`).

**미설정이면 해발 기준 설계면은 계산되지 않고 거부된다** — 숫자를 지어내지 않는다.
격자 없이 변환하면 한국에서 20~30m 가 조용히 틀리기 때문이다.

## 5. 띄운다

CAP-5 runtime capability는 기본적으로 fail-OFF다. 운영자가 승인된 배치에 대해
`KSI_CORE_CAPABILITY_FRESHNESS_POLICIES_JSON`과
`KSI_CORE_RUNTIME_ROUTE_CONFIGURATIONS_JSON`을 명시하고, CAP-4 activation에 고정된
freshness policy ID+digest 및 configured deployment digest와 정확히 일치시켜야만 현재
route 관측을 평가한다. 둘 중 하나라도 없거나 다르면 runtime-ready는 false이며 Core가
최신/default policy나 장비 self-report로 보완하지 않는다. 이 설정은 신규 route 호출
자격만 다루며 이미 발급된 signed Mission Contract를 관측 timeout으로 취소하지 않는다.
Freshness registry의 각 값은 `RuntimeRouteFreshnessPolicyV1` 전문이며, Core는
`expiresAt-observedAt`이 그 policy의 `observationTtlSeconds`와 정확히 같을 때만 ingest한다.
Gateway도 같은 policy에 pin된 `minimumRefreshMarginSeconds`를 남기는 poll cadence만
허용한다. ID→digest만 있는 구형 값이나 임의 기본 TTL은 허용하지 않는다.

```bash
cd deploy
cp .env.example .env
cp device-attestation-keys.example.json device-attestation-keys.json
$EDITOR .env                     # §2·§3 에서 만든 값을 채운다
docker compose up -d --build
```

`.env`와 `device-attestation-keys.json`은 커밋되지 않는다(`.gitignore`). 후자는
Manifold의 Ed25519 **공개키** manifest이며, 개인키는 장비 밖으로 복사하지 않는다.

`init-volumes` 서비스가 먼저 한 번 돌아 볼륨 소유권을 맞춘다 — Core 는 uid 10001,
워커는 uid 10002 로 도는 non-root 프로세스인데 Docker 명명 볼륨은 root 소유로 생성되므로,
이 단계가 없으면 원장 파일 하나 못 만들고 죽는다.

## 6. 떴는지 확인한다

```bash
curl -fsS http://127.0.0.1:8000/ready && echo
# {"ready":true}
```

**`/health` 가 아니라 `/ready` 를 본다.** `/health` 는 프로세스 생존만 본다 —
원장이 봉인(sealed)돼 모든 쓰기가 503 인 서버를 `/health` 는 건강하다고 답한다.
`/ready` 는 그 경우 503 을 준다. compose 의 healthcheck 도 `/ready` 를 쓴다.

인증까지 확인:

```bash
curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/v1/sites && echo
```

## 7. 자주 나오는 실패

| 증상 | 원인 | 조치 |
|---|---|---|
| `KSI_CORE_* 이 없다` 로 즉시 종료 | 필수 변수 누락 | 로그가 지목한 변수를 `.env` 에 채운다 |
| `tokenSha256 은 소문자 64자리 hex 여야 한다` | 원문 토큰을 그대로 넣었거나, `sha256sum` 출력의 뒤쪽 `  -` 까지 붙여넣었거나, 대문자 | `sha256sum \| awk '{print $1}'` 출력을 넣는다(§3) |
| `키 매니페스트를 읽을 수 없다` | `keys.json` 이 없거나 형식 오류거나, **`deploy/signing-keys/` 가 아닌 다른 곳에 만들었다**(compose 가 바인드하는 경로는 이 하나뿐이다) | §2 — 경로부터 확인한다 |
| `개인키 권한이 너무 열려 있다` | `chmod 600` 누락 | §2 |
| 키는 있는데 Core 가 `keys.json` 을 못 읽는다(권한 거부) | 파일 소유자가 uid 10001 이 아니다 — Core 는 non-root 라 `0600` 파일을 소유자가 아니면 못 읽는다 | §2 마지막 단계(`docker run --rm -v "$PWD/signing-keys":/mnt busybox:1.36@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662 chown -R 10001:10001 /mnt`) |
| 기동은 됐는데 `/ready` 가 503 | 원장이 봉인됨 | 응답의 `sealedCount` 확인 후 원장 상태 조사 — 쓰기를 계속하면 안 된다 |
| 워커가 붙지 못함(401) | `KSI_WORKER_CORE_TOKEN` 원문과 Core 의 digest 불일치 | §3 을 다시 한다(원문↔digest 쌍) |
| 재구성이 `EngineIdentityMismatch` 로 거부 | NodeODM 이미지가 바뀌어 엔진 버전이 작업 지시와 다름 | 의도된 거부다 — 작업의 `engineVersion` 과 실제 엔진을 맞춘다 |
| 해발 기준 설계면이 거부됨 | `KSI_GEOID_GRID` 미설정 | §4 |
| `KSI_WORKER_DYNAMIC_OBJECT_MODEL_DIR` 설정 시 워커가 기동 자체를 거부(`RuntimeError` — 정확한 문구는 원인마다 다르다: "존재하는 디렉터리가 아니다" 또는 "동적 객체 탐지기 로드 실패") | 그 경로에 유효한 모델이 없음(경로 없음·digest 불일치·`[dfine]` extra 미설치 등) — 의도된 fail-closed 다, 마스킹이 켜졌다고 믿는데 조용히 꺼진 채 도는 것을 막는다 | `tools/fetch_model.py` 로 모델을 다시 받거나, 마스킹을 원치 않으면 그 변수를 비운다 |

## 8. 백업

- **반드시**: `ksi-data` 볼륨(원장 — 사라지면 현장·임무·산출물 이력이 사라진다),
  `deploy/signing-keys/` **디렉터리**(사라지면 발급된 계약을 검증할 수 없다 — 볼륨이
  아니라 호스트 경로다).
- **권장**: `ksi-objects`(사진·점군·정사영상 원본. 재촬영 말고는 복구 수단이 없다).
- 재생성 가능: `ksi-worker-work`·`ksi-odm`(작업 캐시).

## 9. 이 문서가 다루지 않는 것

- **TLS·대시보드 외부 VM profile**: 이 로컬 compose는 평문 HTTP를 localhost에만 연다.
  additive `deploy/compose.vm.yaml`과 Caddy 조립은 `VM_DEPLOYMENT_READINESS.md`를 따른다.
- **여러 대 운영·자동복귀 도크**: 첫 유료 현장 전까지 동결(ADR-KSI-016 D5).
