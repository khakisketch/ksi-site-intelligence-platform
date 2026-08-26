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
        ├─ Worker ─┴─ NodeODM
        └─ private compose network
```

- `compose.yaml`: 기존 로컬 최소 조합이며 rollback 경로다.
- `compose.vm.yaml`: Dashboard와 Caddy를 더하는 additive 외부 VM profile이다.
- DJI Gateway service는 없다. 실제 adapter와 다섯 capability는 HIL 전 `NOT_VERIFIED`다.
- 외부 publish는 Caddy 80/443뿐이다. Base compose의 Core/MinIO/NodeODM port는
  `127.0.0.1` loopback binding이라 원격에서 접근할 수 없다. MinIO console 9001은 Caddy로
  proxy하지 않는다.

## 준비

1. `deploy/.env.example`을 `.env`로 복사하고 합성 데이터용 값을 채운다.
2. `app.<domain>`, `api.<domain>`, `objects.<domain>` DNS를 VM에 연결한다.
3. 승인된 OIDC client의 callback URL을
   `https://app.<domain>/api/auth/callback/ksi-oidc`로 등록한다.
4. OIDC access token에 `ksi_principal_id`, `ksi_organization_id`, `ksi_role`을 넣고 Core
   audience를 설정한다. role은 `ADMIN | FIELD_OPERATOR | VIEWER`만 허용된다.
5. `deploy/secrets/README.md`에 따라 session/client secret file을 만든다.
6. Mission signing key와 device attestation 공개키 manifest를 기존 절차로 준비한다.

```bash
cd deploy
docker compose -f compose.yaml -f compose.vm.yaml --env-file .env config --quiet
docker compose -f compose.yaml -f compose.vm.yaml --env-file .env up -d --build
./bin/smoke-vm.sh "$KSI_CLOUD_DOMAIN"
```

Dashboard는 `EXTERNAL_VM + OIDC + https origins + secret files` 중 하나라도 빠지면
instrumentation 기동 검증에서 실패한다. Core는 OIDC issuer/audience/JWKS/algorithm 설정을
검증하고, JWKS cache가 만료된 상태에서 issuer 장애가 나면 사람 인증을 fail-closed한다.
장비·워커 opaque 자격은 OIDC mode에서도 별도로 유지된다.

## Presigned object 경로

Core 내부 S3 I/O는 `http://minio:9000`, 현장에 반환하는 presigned URL은
`https://objects.<domain>`을 사용한다. 두 값을 합치면 브라우저에 Docker DNS 이름이 노출되어
업로드가 실패하므로 `KSI_CORE_S3_PUBLIC_ENDPOINT`를 제거하지 않는다.

## 백업과 restore

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

DGX Spark의 별도 Compose project에서 production Dashboard/Core OIDC·S3·Copilot 경계를
합성 데이터로 검증했다. Tailscale HTTPS `10000`~`10003`, Local Identity, MinIO 실제 PNG,
presigned GET, Site opt-in, 정상 citation, provider 503와 허위 citation 차단, backup/restore가
통과했다. 이 조합은 worker/NodeODM/DJI Gateway를 시작하지 않으며 기존 개발 stack과 volume을
공유하지 않는다.

이는 이 문서의 software staging 준비를 닫지만 실제 external VM release를 승인하지 않는다.
남은 항목은 Cloud 사업자 due diligence, public DNS/ACME, 실제 IdP test tenant, managed secret,
off-host backup/새 VM restore, 고객 데이터 승인이다.
