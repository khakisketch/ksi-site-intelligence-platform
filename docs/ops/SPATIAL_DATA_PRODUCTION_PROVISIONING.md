# 공간데이터 운영 레인 provisioning (protected production seam)

- Status: 2026-10-14 작성, 같은 날 검증호스트 실증으로 갱신. 4번 A+B 로컬 구현·계약 증거(`22dd33d`,
  `tests/contract/test_spatial_data_production_adapter.py`)와 VM 실증(공개 실자료 COMPLETED→
  다운로드→독립 오라클 PASS; §9) 기준 문서다.
- Authority: ADR-KSI-036/037/038, SDP-20260930, rebaseline 원장 2026-10-14 항목.
- 이 문서는 운영 절차 형식만 고정한다. **클라우드/고객 S3, 고객/운영 수용, 배포/TLS/CI, 2차
  호스트/주기 재현은 별도 OPEN**이다. 검증호스트 체인(워커→API/MCP 소비, Codex CLI 연결,
  공개 실자료)은 2026-10-14 실증됐다(§9).

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

- 실 S3 버전닝·전체 체크섬 요구는 2026-10-14 VM 체인에서 실증됐다(비버전 버킷은 `input` 503
  `INTEGRITY_MISMATCH`; 버전닝 활성+전체 체크섬 재업로드로 해결, §9). 클라우드/고객 S3 적합성은
  별도다.
- VM 워커→API/MCP 소비 체인과 Codex CLI 연결은 실증 완료(공개 DSM COMPLETED→다운로드→오라클
  PASS). 남은 것은 2차 호스트/주기 재현이다.
- 공개 실자료 수용(라이선스/표시 유지)은 실증 범위에 포함; 고객/운영 수용, 배포/TLS/CI는 별도.
- file-cap 런처 하네스는 검증호스트 운영자 자재이며, 제품측 검토는 §9.1로 종결(제품 코드 변경 없음,
  배포 전제 체크리스트 문서화).

## 9. 검증호스트 체인 — 실증된 요구사항 (2026-10-14)

격리 QEMU VM(uid 10001 워커, file-cap 인터프리터, TLS 종단, 로컬 포워더)에서 실 공개 DSM
181,498,053B를 Codex MCP 요청 → 컨테인먼트 크롭(2000×2000) → COMPLETED → 소비자 다운로드 →
독립 오라클 PASS 11/11로 완주하며 확인된 필수 조건:

1. **오브젝트 스토리지**: 버킷 버전닝 ENABLED + 업로드에 전체 오브젝트 SHA-256. 버전 ID가
   null이면 `versioned_head_identity`가 거부해 `input`이 503이 된다(비버전 버킷의 실패 실측).
2. **워커→Core**: 워커 설정의 `coreOrigin`은 https이며 TLS 신뢰가 필요하다(검증호스트는 로컬
   TLS 종단 + CA를 venv certifi에 오버레이). 오브젝트 오리진은 활성화의
   `trustedEndpointOrigins`와 정확히 일치해야 한다(`http://127.0.0.1:9100`).
3. **컨테인먼트**: 자식은 uid/gid 10001·caps 0·NoNewPrivs 1·Seccomp 2·고정 mountinfo·envelope
   rlimits로 실행되고, 워커는 자식의 네임스페이스를 관측할 수 있어야 한다(동일 uid + 권한;
   검증호스트는 file-cap 인터프리터). 자식의 자체검증은 요청 프레임 v2의
   `authorityNamespaceInodes` 수치 비교를 사용한다(`d286c13`) — 워커 자신의 ns inode를
   제공해야 하며, 커널 관측은 부모가 유지한다.
4. **자재 준비 순서**: 9p 등 읽기 전용 공유는 uid 10001에서 접근이 거부될 수 있으므로 워커/
   자식 런타임은 VM-로컬로 스테이징하고(바이트 동일성 확인), proof는 실 정책/런타임 다이제스트로
   발급하며(`gen_proof`), mountinfo 고정은 holder 시작 이후 마운트 변경이 없어야 유지된다.
5. **수용 envelope**: 검사 봉투(입력/pixels)가 실자료를 못 담으면 MEASURED가 불가하다 — 수용
   목적의 서명 봉투 재발급(제품 정책 아님)이 선행돼야 한다.

증거·하네스: `docs/audit/SPATIAL_DATA_CODEX_LOCAL_ACCEPTANCE_2026-10-14.md`,
`/tmp/opencode/ksi-sdata-vm-sandbox/`(운영자 자재), `evidence/public-sample/`(rig).

### 9.1 하네스 제품측 검토 결과 (2026-10-14, OPEN 해소)

제품측 검토 결론: **제품 코드 변경 없음.** 하네스(holder/launcher/proof/provision)는 운영자
자재로 유지하고, 배포 전제를 아래 체크리스트로 문서화한다. 하네스 README/selftest는
`d286c13` 이전(자식 자체검증 만족 불가) 서술이라 역사 스냅샷으로만 읽는다 — 현재 검증자는
요청 프레임 v2 수치 비교를 쓰고, 공개 실자료 2주기·ortho 크롭이 COMPLETED로 완주했다(감사 문서).

배포 전제 체크리스트(운영 호스트):

1. file-cap 인터프리터: `setcap`(install/chown/setuid/setgid/setpcap/sys_admin/sys_ptrace) +
   오프라인 provision/verify(설치·`getcap`·sha 단언). 파일 캐퍼빌리티가 제거되는
   백업/패키지 갱신/커널 강화 환경에서는 lane이 `ACTIVATION_UNAVAILABLE`로 fail-closed.
2. 전용 uid/gid 10001 예약(로그인·서비스 사용자와 충돌 금지). 워커=자식 동일 uid라
   호스트 DAC는 자식↔워커를 격리하지 않는다 — 전용 호스트/계정 전제.
3. holder 시작 이후 마운트 변경 금지(mountinfo 고정): 업데이트·자동마운트·백업 에이전트의
   마운트 변경 시 proof 재발급·재프로비저닝, 재부팅은 holder/proof 무효.
4. proof는 실 정책/런타임 다이제스트·짧은 valid_until로 발급(수동 `gen_proof` 체크리스트).
5. 런타임은 스테이징 사본 + 바이트 동일성 단언(`diff -r` 패턴)으로 고정; 재배포 시 재스테이징.
6. Seccomp denylist는 심층 방어일 뿐 샌드박스 증명이 아니다(README §7과 동일 취지).
7. holder liveness(cmdline·uid_map·ns 존재)를 launch 전 확인; stale pid 파일 주의.
8. §9.1–9.2(버전닝·전체 체크섬, https/TLS, `trustedEndpointOrigins`)는 배포 게이트로 유지.
