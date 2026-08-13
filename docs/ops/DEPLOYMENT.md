# 배포 (Core · 처리 워커)

> 이 문서가 있기 전에는 이 시스템을 띄우려면 `production.py` 를 읽어야만 무엇을
> 채울지 알 수 있었다. 저장소에 compose·env 예제가 하나도 없었다.
>
> 값의 정본은 항상 코드다 — Core 는 `services/core/src/ksi_core/production.py`,
> 워커는 `services/processing-controller/src/ksi_processing_controller/runner.py`.
> 이 문서는 그 코드가 요구하는 것을 사람이 읽는 순서로 옮긴 것이고, 어긋나면 코드가 맞다.

## 이 배포가 뜨지 않는 것은 정상이다

Core 는 필수 환경변수가 하나라도 없거나 형식이 틀리면 **기동을 거부한다**(`RuntimeError`).
무엇도 조용히 기본값으로 대체하지 않는다 — 조용한 기본값의 종착지가 "인증 없이 뜬
프로덕션 서버"이기 때문이다. 그래서 첫 배포에서 죽는 것은 실패가 아니라 설계대로다.
로그가 **어느 변수가 왜 문제인지** 말해준다.

---

## 1. 준비물

| 항목 | 왜 필요한가 |
|---|---|
| Docker + Docker Compose | 아래 compose 가 Core·워커·MinIO·NodeODM 을 함께 띄운다 |
| 영속 볼륨 2개 | 원장(`ksi-data`)과 서명키(`ksi-signing-keys`). **이 둘이 백업 대상이다** |
| Mission Contract 서명키 | Core 는 키를 만들지 않는다 — 미리 만들어 둬야 한다(§2) |
| 접근 토큰 | 사람·워커가 Core 를 부를 자격증명(§3) |
| (선택) 지오이드 격자 | 해발 기준 설계도면을 받으려면 필요(§4) |
| (선택) 동적 객체 마스킹 모델 | 재구성 산출물에서 사람·차량을 지우려면 필요 — 기본은 꺼짐(`deploy/.env.example` 의 `KSI_WORKER_DYNAMIC_OBJECT_MODEL_DIR`, `tools/fetch_model.py` 로 받는다) |

## 2. 서명키 먼저 만든다

**Core 는 서명키를 부트스트랩하지 않는다.** 컨테이너는 재생성되는 존재인데(롤링 배포·
재스케줄) 재생성마다 새 키가 생기면, 이미 현장에 발급된 Mission Contract 가 서버 재시작
한 번으로 전부 검증 실패한다. 그건 이 제품의 근본 전제(서버가 죽어도 로컬에서 유효한
계약은 유효하다)를 정면으로 어긴다. 그래서 키는 **컨테이너 밖에 살고 Core 는 읽기만 한다.**

```bash
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

## 3. 접근 토큰 — 원문은 서버에 두지 않는다

Core 는 토큰 **원문을 모른다.** `sha256` digest 만 갖는다. 그래서 프로세스 메모리·로그·
환경변수 어디에도 원문이 존재하지 않는다.

```bash
# 사람(관리자)용
ADMIN_TOKEN=$(openssl rand -hex 32)
printf '%s' "$ADMIN_TOKEN" | sha256sum      # ← 이 digest 를 Core 에 준다
# 워커용
WORKER_TOKEN=$(openssl rand -hex 32)
printf '%s' "$WORKER_TOKEN" | sha256sum
```

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

```bash
cd deploy
cp .env.example .env
$EDITOR .env                     # §2·§3 에서 만든 값을 채운다
docker compose up -d --build
```

`.env` 는 커밋되지 않는다(`.gitignore`).

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
| `tokenSha256 은 소문자 64자리 hex 여야 한다` | 원문 토큰을 그대로 넣었거나 대문자 | `sha256sum` 출력(소문자)을 넣는다 |
| `키 매니페스트를 읽을 수 없다` | `keys.json` 없음/형식 오류 | §2 |
| 기동은 됐는데 `/ready` 가 503 | 원장이 봉인됨 | 응답의 `sealedCount` 확인 후 원장 상태 조사 — 쓰기를 계속하면 안 된다 |
| 워커가 붙지 못함(401) | `KSI_WORKER_CORE_TOKEN` 원문과 Core 의 digest 불일치 | §3 을 다시 한다(원문↔digest 쌍) |
| 재구성이 `EngineIdentityMismatch` 로 거부 | NodeODM 이미지가 바뀌어 엔진 버전이 작업 지시와 다름 | 의도된 거부다 — 작업의 `engineVersion` 과 실제 엔진을 맞춘다 |
| 해발 기준 설계면이 거부됨 | `KSI_GEOID_GRID` 미설정 | §4 |
| `KSI_WORKER_DYNAMIC_OBJECT_MODEL_DIR` 설정 시 워커가 기동 자체를 거부(`RuntimeError` — 정확한 문구는 원인마다 다르다: "존재하는 디렉터리가 아니다" 또는 "동적 객체 탐지기 로드 실패") | 그 경로에 유효한 모델이 없음(경로 없음·digest 불일치·`[dfine]` extra 미설치 등) — 의도된 fail-closed 다, 마스킹이 켜졌다고 믿는데 조용히 꺼진 채 도는 것을 막는다 | `tools/fetch_model.py` 로 모델을 다시 받거나, 마스킹을 원치 않으면 그 변수를 비운다 |

## 8. 백업

- **반드시**: `ksi-data`(원장 — 사라지면 현장·임무·산출물 이력이 사라진다),
  `ksi-signing-keys`(사라지면 발급된 계약을 검증할 수 없다).
- **권장**: `ksi-objects`(사진·점군·정사영상 원본. 재촬영 말고는 복구 수단이 없다).
- 재생성 가능: `ksi-worker-work`·`ksi-odm`(작업 캐시).

## 9. 이 문서가 다루지 않는 것

- **TLS·역방향 프록시**: compose 는 평문 HTTP 8000 을 **localhost 에만** 연다.
  공개망 노출은 배포 환경(로드밸런서·Ingress)이 담당한다 — 여기서 정하지 않는다.
- **대시보드**(`apps/dashboard`): Next.js 앱은 별도 배포 경로다.
- **여러 대 운영·자동복귀 도크**: 첫 유료 현장 전까지 동결(ADR-KSI-016 D5).
