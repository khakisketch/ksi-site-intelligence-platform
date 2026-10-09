# KSI Cloud External VM Readiness

범위: 승인 전 개발·합성 데이터. 실제 외부 배포·DNS 변경·고객 데이터 업로드는 이 문서만으로
승인되지 않는다. Cloud 사업자 release gate는
`docs/security/CLOUD_PROVIDER_DUE_DILIGENCE.md`가 소유한다.
신규 런타임 버전·라이선스·SBOM 및 취약점 기준은
`docs/ops/EXTERNAL_VM_DEPENDENCY_BASELINE.md`를 함께 따른다.

## 조립 경계

```text
Internet :80/:443
        │
      Caddy
  ┌─────┼──────────┐
  │     │          │
 app   api       objects
  │     │          │
Dashboard Core    MinIO API
         │          │
        └──────────┴─ private compose network
```

- `compose.yaml`: `init-volumes/core/minio` 플랫폼 로컬 최소 템플릿이다.
- `compose.vm.yaml`: Dashboard와 Caddy를 더하는 additive 외부 VM profile이다.
- 합친 서비스는 `init-volumes/core/minio/dashboard/caddy`다. NodeODM·managed 워커·DJI
  Gateway는 없다. 취득 장비 capability는 역사적 범위의 `NOT_VERIFIED`이며 제품 지원이 아니다.
- 외부 publish는 Caddy 80/443뿐이다. Base compose의 Core/MinIO port는
  `127.0.0.1` loopback binding이라 원격에서 접근할 수 없다. MinIO console 9001은 Caddy로
  proxy하지 않는다.
- 기존 서비스 설정/이미지/볼륨 식별자는 보존한다. `ksi-odm`은 역사적 미사용 선언이며
  고유한 데이터가 있을 수 있다. 템플릿 변경은 기존 컨테이너 중지나 데이터/볼륨 삭제가 아니다.

## 준비

1. `deploy/.env.example`을 `.env`로 복사하고 합성 데이터용 값을 채운다.
2. `app.<domain>`, `api.<domain>`, `objects.<domain>` DNS를 VM에 연결한다.
3. 승인된 OIDC client의 callback URL을
   `https://app.<domain>/api/auth/callback/ksi-oidc`로 등록한다.
4. Core audience/issuer/JWKS와 보호된 `KSI_CORE_OIDC_SUBJECT_REGISTRY_FILE`을 함께 준비한다.
   실제 subject→조직/principal/role/범위는 기존 등록 계약을 따른다. JWT claims만으로
   principal이나 신규 Site/WorkArea grant가 자동 생성되는 것이 아니다.
5. `deploy/secrets/README.md`에 따라 session/client secret file을 만든다.
6. [현재 플랫폼 요건](DEPLOYMENT.md)에 따라 원장/S3/bucket와 비어 있지 않은 principal
   digest 목록을 준비한다. 보호된 파일의 안전한 공급·접근 경로는 별도 운영 검증이며 이
   템플릿 정리는 마운트/자격을 추가하지 않는다. Mission 키/device attestation은 요구하지 않는다.

아래는 별도 승인된 운영 환경을 위한 기존 config/start 예시이며 이 문서나 P6 코드 승인으로
실제 이미지 빌드·기동·DNS/IdP/secret 변경이 허용되는 것은 아니다. `.env.example` 및
`compose config` 병합 성공은 보호된 입력·실제 이미지/운영 기동·고객 수용의 증거가 아니다.

```bash
cd deploy
docker compose -f compose.yaml -f compose.vm.yaml --env-file .env config --quiet
docker compose -f compose.yaml -f compose.vm.yaml --env-file .env up -d --build
```

Dashboard는 `EXTERNAL_VM + OIDC + https origins + secret files` 중 하나라도 빠지면
instrumentation 기동 검증에서 실패한다. Core는 OIDC issuer/audience/JWKS/algorithm 설정을
검증하며 보호된 subject 등록 파일도 요구한다. JWKS cache가 만료된 상태에서 issuer 장애가
나면 사람 인증을 fail-closed한다. 승인된 비사람 principal의 opaque 자격은 별도로 유지된다.

선택 Analysis runtime/activation/검증키는 전부 아니면 전무이며 `ANALYSIS_WORKER`가
정확히 하나여야 한다. 외부 workflow/provider 설정은 함께 아니면 전무다. 워커 기동/신뢰는
이 VM 템플릿이 생성하지 않는다. 현재 production 팩토리에 `spatial_data` 주입은 없고,
실제 로컬 경로는 `SpatialDataLocalAssemblyConfig`다. 새 환경변수나 활성화 기능을 가정하지 않는다.

## Presigned object 경로

Core 내부 S3 I/O는 `http://minio:9000`, 현장에 반환하는 presigned URL은
`https://objects.<domain>`을 사용한다. 두 값을 합치면 브라우저에 Docker DNS 이름이 노출되어
업로드가 실패하므로 `KSI_CORE_S3_PUBLIC_ENDPOINT`를 제거하지 않는다.

## 역사적 backup/restore 절차 — 현재 플랫폼 복구 증거 아님

아래는 이전 조합의 절차/스크립트를 보존한 기록이다. `backup-vm.sh`, `restore-check-vm.sh`,
`smoke-backup-restore.sh`, `smoke-vm.sh`는 현재 플랫폼에 대한 검증된 운영/복구 절차로
실행하지 않는다. key/worker/ODM 설명도 역사적 범위다. 현재 원장·객체·역사적 볼륨을
보존하며 fresh 환경의 실제 복구/TLS/UDS/ACL/host 검증은 별도 승인까지 미확인이다.

백업 대상은 Core journal, Mission signing key, 원본 object다. worker/ODM cache는 재생성할 수
있다. `deploy/bin/backup-vm.sh <absolute-output-dir>`는 timestamp bundle과 SHA-256 manifest를
만든다. `restore-check-vm.sh <bundle-dir>`는 격리된 임시 Docker volume에 복원해 archive를
실제로 읽을 수 있는지 확인하며 운영 volume은 건드리지 않는다.
`smoke-backup-restore.sh`는 고유한 합성 Docker volume만 만들고 위 두 스크립트를 실제 실행한
뒤 정리한다. 운영 volume 이름은 기본값으로 유지되며 smoke에서는 명시적으로 대체된다.

운영 복구는 다음 원칙을 따른다.

1. Caddy/Dashboard/Core/Worker를 중지한다.
2. 원본 volume을 덮어쓰지 말고 새 project/새 volume에 restore한다.
3. signing key manifest·권한, journal replay, object digest를 확인한다.
4. `/ready`와 대표 object presigned GET/PUT을 합성 데이터로 확인한다.
5. DNS 전환은 별도 승인 후 수행한다.

Restore를 실행해 본 증거가 없는 tar 파일은 백업 완료로 간주하지 않는다.

## 2026-08-25 synthetic staging evidence

이하 dated 증거/판정은 당시 source/조합에만 귀속된다. 현재 플랫폼 기동이나 새 VM 복구,
P6 fresh runtime 검증으로 소급 사용하지 않는다.

DGX Spark의 별도 Compose project에서 production Dashboard/Core OIDC·S3·Copilot 경계를
합성 데이터로 검증했다. Tailscale HTTPS `10000`~`10003`, Local Identity, MinIO 실제 PNG,
presigned GET, Site opt-in, 정상 citation, provider 503와 허위 citation 차단, backup/restore가
통과했다. 이 조합은 worker/NodeODM/DJI Gateway를 시작하지 않으며 기존 개발 stack과 volume을
공유하지 않는다.

이는 이 문서의 software staging 준비를 닫지만 실제 external VM release를 승인하지 않는다.
남은 항목은 Cloud 사업자 due diligence, public DNS/ACME, 실제 IdP test tenant, managed secret,
off-host backup/새 VM restore, 고객 데이터 승인이다.
