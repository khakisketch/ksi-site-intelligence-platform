# 공간데이터 운영 레인 provisioning (protected production seam)

- Status: 2026-10-14 작성. 4번 A+B 로컬 구현·계약 증거(`22dd33d`,
  `tests/contract/test_spatial_data_production_adapter.py` 12건) 기준 문서다.
- Authority: ADR-KSI-036/037/038, SDP-20260930, rebaseline 원장 2026-10-14 항목.
- 이 문서는 운영 절차 형식만 고정한다. **라이브 서명키·grant 배치, 실제 S3 보장 확인,
  VM parser/worker chain, Codex CLI 연결, 공개 실자료/고객 수용은 별도 OPEN**이다.

## 1. 무엇이 열리는가

`KSI_CORE_SPATIAL_DATA_CONFIG_FILE`가 없으면 데이터 레인은 **미장착**이다 — 기존 운영 표면·저널·
라우트가 그대로다. 값이 있으면 보호 구성 검증을 통과한 경우에만 기존 spatial-data 요청/상태/취소,
worker route, AI 자산 discovery, S3 준비·다운로드, cleanup loop가 mount된다.

이 레인은 KSI가 재구성·측정을 대신하는 경로가 아니다. 등록≠검증≠정량 사용 가능이고, 준비·전달은
정확도·정산·측량 수용이 아니다.

## 2. 보호 파일 두 개

두 파일 모두 복호화 불가능한 owner-private 파일이다: 정규화된 **절대 경로**, 일반 파일,
소유자 `0600`, 링크 1개, 부모 체인 무그룹/타인 쓰기(스티키 `/tmp` 아래 owner-child 허용).
구성 ≤256 KiB, rights ≤1 MiB.

### 2.1 Core 구성 — `spatial-data-core-config.v1`

필드(JSON, camelCase):

```json
{
  "version": "spatial-data-core-config.v1",
  "processingLocation": "site_onprem",
  "policy": { "...": "sealed SpatialDataPolicyV1" },
  "runtime": { "...": "sealed SpatialDataRuntimeV1" },
  "activation": { "...": "sealed SpatialDataActivationV1" },
  "activationSignature": "<base64(64-byte Ed25519 signature over the canonical activation signing bytes)>",
  "trustedPublicKey": "<base64(32-byte Ed25519 public key)>",
  "revokedActivationDigests": [],
  "spoolRoot": "/absolute/existing/0700/spool",
  "operationTimeoutSeconds": 5.0,
  "grantsFile": "/absolute/owner-private/rights.json",
  "cleanupIntervalSeconds": 300.0
}
```

부팅 시 강제되는 것:

- policy/runtime/activation은 **sealed**(digest=canonical), activation은 exact policy/runtime digest에
  결속. `preparationProfile`도 일치해야 한다.
- Ed25519 디태치 서명이 canonical 형식으로 검증된다. raw digest 재봉인만으로는 통과하지 않는다.
- `activation.workerPrincipalId`는 등록된 `SPATIAL_DATA_WORKER` **신원 1개**(조직 일치, role/device 없음)여야
  한다 — 회전 중 같은 신원의 digest 중복 record는 허용한다.
- `revokedActivationDigests`에 구성 activation이 포함되면 부팅 실패.
- `spoolRoot`는 기존 owner-private `0700` 디렉터리.
- `operationTimeoutSeconds`는 정책 `streamDeadline`·`cleanupDeadline`·envelope `maxDeadline` 이하.
- **만료된 authentic activation은 부팅을 허용**한다 — 보존 이력 replay는 되지만 새 작업/사용은
  기존 `ACTIVATION_UNAVAILABLE`/`CURRENTNESS_UNAVAILABLE`로 fail-closed.

### 2.2 권리 — `spatial-data-rights.v1`

```json
{
  "version": "spatial-data-rights.v1",
  "grants": [ { "...": "sealed SpatialDataGrantV1" } ],
  "revocations": [ { "...": "sealed SpatialDataRevocationV1" } ]
}
```

- 각 ≤512. 모든 record sealed. revocation은 **같은 파일의 grant와 (org, grantId, revision, digest)
  쌍**이어야 한다.
- grant는 현재 policy digest·`site_onprem`에 결속돼야 하고, beneficiary는 부팅 시점에 해석 가능한
  principal(opaque token registry id 또는 ACTIVE OIDC subject mapping, 같은 조직)이어야 한다.
  해석 불가 grant는 부팅 실패다(죽은 권리 설정을 남기지 않는다).
- 공급·회수는 KSI 운영자 전용이다. 공개 grant 편집 API는 없다. 같은 payload로 재부팅하면 멱등이고,
  같은 id/revision을 다른 digest로 바꾸면 conflict로 부팅이 실패한다.

## 3. 환경변수

```text
KSI_CORE_SPATIAL_DATA_CONFIG_FILE=/absolute/owner-private/spatial-data-core-config.json
```

기존 필수 env(`KSI_CORE_DATA_DIR`, `KSI_CORE_S3_ENDPOINT`, `KSI_CORE_S3_BUCKET`,
`KSI_CORE_PRINCIPAL_TOKENS_JSON`)는 그대로다. worker/operator principal record가 등록돼야 하며,
OIDC 모드에서는 beneficiary가 subject registry에 ACTIVE로 매핑돼 있어야 한다.

`SPATIAL_DATA_MCP_CLIENT`(AI 소비자)는 `KSI_CORE_PRINCIPAL_TOKENS_JSON`에서 **명시적 scope 배열**과
함께 등록한다(2026-10-14 수정 이후 환경변수 등록이 지원된다):

```json
{
  "tokenSha256": "<64-hex>",
  "principalId": "sdata-mcp",
  "kind": "SPATIAL_DATA_MCP_CLIENT",
  "role": null,
  "deviceId": null,
  "organizationId": "<org>",
  "allowedSiteIds": ["<site>"],
  "allowedWorkAreaIds": ["<area>"]
}
```

scope 배열은 MCP client kind 전용이며 다른 kind에 실리면 부팅이 실패한다.

## 4. 서명 material과 경계

activation 서명은 KSI가 통제하는 서명키로 수행하고 Core는 **검증만** 한다(공개키는 구성 파일에 pin).
로컬 포맷 검증은 `tests/contract/test_spatial_data_production_adapter.py`가 Ed25519 키쌍을 로컬 생성해
고정한다 — 이는 형식 증거이며 운영 발급·키 관리 절차가 아니다. 라이브 발급 도구/보관·회전 절차는
후속 작업으로 남는다. 테스트 키·테스트 구성·테스트 grant를 운영에 사용하지 않는다.

## 5. 기대 동작과 진단

- 부재: `app.state.spatial_data` 없음(레인 미장착).
- 보호 위반·형식/서명/신원/권리 오류: 저널·S3 부수효과 **이전에** 부팅 실패.
- 부팅 성공: `app.state.spatial_data`=wiring, `app.state.spatial_data_cleanup`=cleanup loop.
  서버 shutdown 이벤트에서 loop가 stop된다.
- cleanup: 기존 `run_spatial_data_cleanup_once`를 주기 실행한다. 소유한 정확 출력 버전만 삭제하고
  소스 원본을 열거·삭제하지 않는다.
- 신원 반영: opaque 토큰 폐기·OIDC subject REVOKED는 **다음 Core 재기동**에 반영된다(부팅 시점
  identity snapshot; 요청 자격증명을 저장하지 않는다).

## 6. 확인 명령

```bash
uv run --no-sync pytest -q tests/contract/test_spatial_data_production_adapter.py
uv run --no-sync python tools/check_core_module_boundaries.py
```

부팅 스모크(합성 자료)는 위 테스트가 수행한다: 부재=미장착, 0644/서명/신원/revocation 모순 부팅 실패,
만료 authentic 부팅+`is_current` False, rights 저널 provisioned/revoked 각 1, import 멱등+회수,
manifest key 정확 일치, cleanup loop 실행/정지.

## 7. Rollback

`KSI_CORE_SPATIAL_DATA_CONFIG_FILE`를 제거하고 재기동하면 레인이 다시 미장착된다. 기존 저널·
grant/revocation·job/receipt/audit·원본은 보존되며 삭제되지 않는다.

## 8. 남은 게이트 (이 문서로 닫히지 않음)

- 실 S3에서 버전 ID·전체 체크섬·정확 버전 삭제 보장의 운영 확인.
- VM에서 parser→worker→API/MCP 소비 chain 실행, Codex CLI 한 환경 연결·예제 workflow.
- 공개 실자료 수용(라이선스/표시 유지), 고객/운영 수용, 배포/TLS/CI.
