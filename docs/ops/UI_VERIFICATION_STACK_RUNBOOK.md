# UI 검증용 합성 스택 런북 (Stage-1 live UI verification)

Status: 2026-10-12 작성. synthetic 전용 — 고객 데이터·정량 E2E·배포 증거가 아니다.
Owner: Dashboard/Platform 검증 작업. 관련: [BROWSER_E2E_CHECKLIST](BROWSER_E2E_CHECKLIST.md),
[DEV_EXTERNAL_RUNBOOK](DEV_EXTERNAL_RUNBOOK.md), rebaseline 원장의 Stage-1 기록.

## 목적

F-03 합성 기록(외부 관측·검사·검증·분석·근거)이 들어 있는 Core에 대해, 실제 OIDC 로그인을
거친 Operations Console을 브라우저로 조작해 사용자 흐름·상태 일치·모바일·접근성을 확인한다.

## 구성 요소와 포트

| 요소 | 실행 | 포트 |
|---|---|---|
| Local OIDC issuer | `uv run python tools/run_local_oidc_issuer.py ...` | 127.0.0.1:9041 |
| Core (production factory) | `python -m uvicorn ksi_core.composition.platform_production:build_platform_production_app --factory` | 127.0.0.1:8041 |
| Operations Console (next dev) | `node node_modules/next/dist/bin/next dev` | 127.0.0.1:3241 |
| MinIO (기존 F-03 캐시 컨테이너) | `f03-prep-minio` (loopback 9100, bucket `ksi-f03-evidence`) | 127.0.0.1:9100 |

helper: `/tmp/opencode/ksi-ui-20261012/ui_stack.py`(issuer+Core+Console supervisor) ·
`/tmp/opencode/f04-consumer-20261012/scripts/launch_core_f04.py`(Core 단독 부팅 참고).

## 보호 자재 (synthetic)

- Analysis 런타임/activation: `~/.cache/ksi-f03-20261010-194828/analysis/*` (0700/0600)
- 외부 authority provider **복사본**: `~/.cache/ksi-ui-20261012/provider/*`
  (원본을 복사한 뒤 `workflow.json`·`external-authority-provider.json` 내부 경로를 복사 위치로
  재작성해야 한다 — 보호 로더는 그룹 쓰기 가능 조상과 stale 절대경로를 거부한다)
- Core 데이터 **복사본**: `~/.cache/ksi-ui-20261012/core-data` (원본 F-03 `f03/core-data` 복사)
- OIDC subject registry: `~/.cache/ksi-ui-20261012/registry.json` (v1)
- Opaque principal tokens: `~/.cache/ksi-ui-20261012/tokens-ui.json`
- issuer secret: `/tmp/opencode/ksi-ui-20261012/identity/secrets/*` (600, 최초 실행 시 자동 생성)

### OIDC 계정 매핑 (registry.json)

| Console 계정 | subject | org | role | grant |
|---|---|---|---|---|
| 기본 개발 계정 | `local-admin` | org-a | ADMIN | `f03-flow-site` + wa-0001..0003 |
| 현장 운영자 | `local-field-operator` | org-a | FIELD_OPERATOR | 동일 |
| 열람자 | `local-viewer` | org-a | VIEWER | 동일 |
| 빈 조직 관리자 | `local-empty-org-admin` | org-local-empty | ADMIN | 없음 |

로그인: Console `/login` → "개발 Operations Console 시작"(기본) 또는
"권한별 화면 테스트 → 다른 개발 계정 선택"(issuer 화면에서 계정 선택).

## 기동

```bash
# 1) MinIO 컨테이너가 살아 있는지 확인 (없으면 F-03 prep 캐시 이미지로 기동)
docker ps --format '{{.Names}} {{.Ports}}' | grep f03-prep-minio

# 2) supervisor 기동 (issuer → Core → Console 순으로 health 확인)
mkdir -p /tmp/opencode/ksi-ui-20261012/logs
setsid nohup python3 /tmp/opencode/ksi-ui-20261012/ui_stack.py \
  > /tmp/opencode/ksi-ui-20261012/logs/supervisor.log 2>&1 &

# 3) 확인
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9041/healthz   # 200
curl -s http://127.0.0.1:8041/ready                                      # {"ready":true}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3241/login     # 200
```

Core 환경 요약(스크립트가 채움): `KSI_CORE_DATA_DIR`(복사본) · `KSI_CORE_PRINCIPAL_TOKENS_JSON` ·
`KSI_CORE_S3_ENDPOINT/BUCKET` + `AWS_*` · `KSI_CORE_ANALYSIS_{RUNTIME_CONFIG,ACTIVATION,ACTIVATION_KEYS}_FILE`
(위 보호 자재) · `KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG`/`KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG`
(복사본) · `KSI_CORE_HUMAN_AUTH_MODE=OIDC` + `KSI_CORE_OIDC_{ISSUER,AUDIENCE,JWKS_URL,SUBJECT_REGISTRY_FILE}`.

## 종료

```bash
kill "$(ps -o ppid= -p "$(cut -d, -f1 /tmp/opencode/ksi-ui-20261012/stack.pids)" | tr -d ' ')" 2>/dev/null || \
  kill $(tr ',' ' ' < /tmp/opencode/ksi-ui-20261012/stack.pids)
sleep 2
ss -ltn | grep -E ':3241|:8041|:9041' || echo "ports free"
```

MinIO 컨테이너는 F-03 캐시 자산이므로 기본적으로 그대로 둔다(필요 시 별도 판단).

## 재현 시 주의 (이번 패스에서 실제로 만난 함정)

1. **dev 러너는 만료된 provider snapshot으로 부팅하지 않는다** — `scripts/run_core_dev.py`는
   `allow_expired` 없이 로드해 `external authority provider is blocked`로 죽는다. FPC-15A의
   degraded boot는 production factory에만 적용되어 있으므로, 이 런북은 production factory로
   Core를 띄운다(외부 정량 경로는 runtime에서 blocked 유지 — 이 상태가 정상이다).
2. **보호 로더 경로 규칙** — provider/analysis/registry 파일은 그룹 쓰기 가능 조상(예: `/tmp/opencode`)
   아래에 두면 `has an unprotected parent`로 거부된다. `~/.cache/ksi-*`(0700)를 사용한다.
3. **provider 복사 후 경로 재작성** — config 내부 절대경로가 옛 위치를 가리키면 같은 오류가 난다.
4. **E2E seed 스크립트는 빈 원장만 허용** — `apps/dashboard/e2e/fixtures/seed_operations_console.py`는
   기존 데이터가 있으면 fail-closed로 거부한다. F-03 데이터에 얹으려 하지 말고, seed가 필요하면
   빈 디렉터리에서 별도 스택을 띄운다.
5. **만료된 Analysis activation** — 기존 F-03 activation은 만료 상태이므로 새 분석 생성은 차단된다
   (읽기·근거 조회는 정상). 새 정량 실행을 주장하지 않는다.

## 이 런북으로 확인 가능/불가능

- 가능: 사용자 흐름(현장·관측 등록 → 작업 → 검사/판정 조회 → 분석 → 결과·근거 → 리뷰 상태),
  저장·재조회, 데스크톱/모바일 레이아웃, 접근성(a11y), 계정별 권한 화면.
- 불가: parser sandbox 포함 정량 E2E(`PARSER_SANDBOX_UNAVAILABLE`), 실자료 적합성, 운영 배포.
