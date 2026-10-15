# VM secret files

이 디렉터리에는 실제 배포 때만 다음 두 파일을 만든다. 파일 자체는 git에 포함하지 않는다.

- `dashboard-session.secret`: `openssl rand -base64 48` 결과
- `oidc-client.secret`: 승인된 IdP가 발급한 Dashboard confidential client secret

두 파일은 줄바꿈을 제외하고 최소 32자여야 한다. Core Mission signing key와 장비 개인키는
이 디렉터리에 복사하지 않는다.

**소유권 요건(2026-10-15 로컬 조립 검증에서 확인)**: `docker compose`의 파일 기반 secret은
컨테이너 안에서 **호스트 파일의 plain bind mount**로 나타나며 long syntax의 `uid/gid/mode`는
적용되지 않는다. Dashboard 컨테이너는 uid 10001로 실행되므로 두 파일을 그 uid로 소유시켜야
한다 — 그렇지 않으면 기동이 `EACCES '/run/secrets/dashboard-session'`으로 실패한다:

```
sudo chown 10001:10001 deploy/secrets/dashboard-session.secret deploy/secrets/oidc-client.secret
chmod 400 deploy/secrets/dashboard-session.secret deploy/secrets/oidc-client.secret
```
