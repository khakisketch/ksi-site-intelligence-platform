# VM secret files

이 디렉터리에는 실제 배포 때만 다음 두 파일을 만든다. 파일 자체는 git에 포함하지 않는다.

- `dashboard-session.secret`: `openssl rand -base64 48` 결과
- `oidc-client.secret`: 승인된 IdP가 발급한 Dashboard confidential client secret

두 파일은 줄바꿈을 제외하고 최소 32자여야 한다. Core Mission signing key와 장비 개인키는
이 디렉터리에 복사하지 않는다.
