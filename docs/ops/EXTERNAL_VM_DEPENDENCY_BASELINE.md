# External VM Dependency Baseline

이 문서는 KSI Operations Console 외부 VM 조립에 새로 추가된 런타임 의존성과 release
검증 기준을 고정한다. 버전 고정은 보안 승인이나 실제 고객 데이터 배포 승인을 뜻하지 않는다.

## 고정된 구성요소

| 구성요소 | 고정 위치 | 현재 해석 버전 | 라이선스 | 용도 |
|---|---|---:|---|---|
| Auth.js (`next-auth`) | `apps/dashboard/package.json`, `package-lock.json` | `5.0.0-beta.32` | ISC | OIDC Authorization Code + PKCE, 암호화 서버 세션 |
| PyJWT | `services/core/pyproject.toml`, `uv.lock` | `2.13.0` | MIT | Core OIDC JWT/JWKS 검증 |
| Caddy image | `deploy/compose.vm.yaml` | `2.10.2-alpine` + OCI digest | Apache-2.0 | TLS ingress |
| Node image | `apps/dashboard/Dockerfile` | `22.18-alpine` + OCI digest | MIT | Dashboard build/runtime |
| Playwright Test | `apps/dashboard/package.json`, `package-lock.json` | `1.62.1` | Apache-2.0 | 4개 기준 폭 OIDC·반응형 브라우저 회귀 |
| axe-core | `apps/dashboard/package.json`, `package-lock.json` | `4.13.0` | MPL-2.0 | serious·critical 접근성 자동 검사 |

## Runtime image provenance

운영과 synthetic staging에서 외부 registry로부터 받는 이미지는 모두 **명시 버전 태그와
multi-arch OCI manifest digest**를 함께 적는다. 태그는 사람이 읽는 의도된 릴리스이고,
digest는 실제 pull 대상이다. `:latest`와 tag-only 참조는 허용하지 않는다.
`tools/check_runtime_image_pins.py`가 product-owned root·apps·services·workers Dockerfile,
Manifold build Dockerfile의 `FROM`/외부 `COPY --from`, 모든 `deploy/compose*.yaml|yml`,
그리고 모든 `deploy/bin/*.sh`의 `docker run`을 검사한다. 로컬 Compose build 이름
(`ksi-phase2-*:local`)은 registry pull이 아니므로 예외다. NodeODM은 승인된 multi-arch
manifest digest에 대응하는 upstream release tag가 없으므로, 정적 gate의 유일한
digest-only 예외다. 그 NodeODM/ODM 버전은 처리 프로필과 live `/info` 대조로 별도 검증한다.

| Image | Pinned reference |
|---|---|
| Python | `python:3.12.14-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217` |
| uv | `ghcr.io/astral-sh/uv:0.11.15@sha256:e590846f4776907b254ac0f44b5b380347af5d90d668138ca7938d1b0c2f98d3` |
| Node | `node:22.18-alpine@sha256:1b2479dd35a99687d6638f5976fd235e26c5b37e8122f786fcd5fe231d63de5b` |
| BusyBox | `busybox:1.36@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662` |
| Alpine (backup/restore) | `alpine:3.22@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce` |
| MinIO | `minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e` |
| MinIO client | `minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727` |
| NodeODM | `opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2` |
| Caddy | `caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d` |

태그와 digest를 바꿀 때는 image manifest가 multi-architecture인지, SBOM·취약점 결과와
실제 기동 검증이 새 digest에 대응하는지를 release review에서 대조한다.

제품 소유 정량 runtime은 `Dockerfile.external-inspector`와
`Dockerfile.external-measurement`에서 별도 이미지로 build한다. 두 이미지는 같은 잠긴
workspace를 사용하지만 서로 다른 non-root 기본 identity와 고정 entrypoint를 가진다.
각 Dockerfile 전용 `.dockerignore`는 필요한 workspace source만 allowlist해 Git-ignored 고객
자료·키·배포 비밀이 root build context에 들어오지 못하게 한다. CI의 build/import/EOF 및
private-path sentinel 검증은 source packaging 증거일 뿐 registry digest나 보안 승인이 아니다.
GeoTIFF runtime에 필요한 `libexpat1=2.8.3-1~deb13u1`은 base image가 기록한
`20260824T000000Z` Debian snapshot URL에서 exact version으로 설치해 dpkg package/license
metadata가 최종 이미지와 SBOM에 남도록 한다. live `deb.debian.org` 해석은 사용하지 않는다.

## SBOM 및 취약점 release gate

Lockfile은 재현 가능한 입력 원장이다. 실제 release 후보마다 다음 산출물을 별도 보관한다.

```bash
cd apps/dashboard
npm ci
npm sbom --sbom-format cyclonedx > dashboard.cdx.json
npm audit --omit=dev

cd ../..
uv export --locked --all-packages --all-extras > python-requirements.lock.txt
docker build -t ksi-dashboard:<release-id> apps/dashboard
syft ksi-dashboard:<release-id> -o cyclonedx-json=dashboard-image.cdx.json
syft caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d -o cyclonedx-json=caddy-image.cdx.json

docker build -f Dockerfile.external-inspector -t ksi-external-inspector:<release-id> .
docker build -f Dockerfile.external-measurement -t ksi-external-measurement:<release-id> .
syft ksi-external-inspector:<release-id> -o cyclonedx-json=inspector-image.cdx.json
syft ksi-external-measurement:<release-id> -o cyclonedx-json=measurement-image.cdx.json
trivy image --format json --output inspector-image.scan.json ksi-external-inspector:<release-id>
trivy image --format json --output measurement-image.scan.json ksi-external-measurement:<release-id>
```

`<release-id>`는 승인된 immutable release version으로 치환하고, registry push 뒤 관측한
각 repo digest와 로컬 Docker image ID를 SBOM·scanner 원본과 함께 host binding의
`runtimeProducts`에 결속한다. 도구가 없거나 결과가 해당 digest에서 생성됐음을 입증하지
못하면 release evidence를 만들지 않고 후보 활성화를 차단한다.

생성한 SBOM에는 최소한 이미지 digest, 생성 시각, lockfile commit, scanner 버전을 기록한다.
SBOM과 audit 결과는 원본 사진·위치정보·공간모델을 올리기 전 보안 검토 증거로 남긴다.

2026-08-23 개발 기준 `npm audit --omit=dev`는 production dependency에서 critical 0,
high 9, moderate 2, low 5를 보고했다. high 대부분은 기존
`georaster -> worker-loader -> webpack 4` 계보이고, `nanoid` 1건은 Next의 PostCSS 계보다.
Auth.js 도입으로 이 결과를 해결된 것으로 표시하지 않는다. 지도 raster 호환성과 Next patch
upgrade를 별도 검증하고, 승인되지 않은 high 취약점이 남으면 외부 고객 데이터 release를
차단한다.

## 변경 규칙

- Auth.js beta 변경은 login/logout/refresh failure와 서버 세션 비노출 회귀 검증 후 수행한다.
- JWT algorithm allow-list를 넓히려면 별도 보안 검토가 필요하다.
- 외부 runtime image를 바꾸면 tag와 multi-arch digest를 함께 갱신하고
  `uv run --locked python tools/check_runtime_image_pins.py` 및 실제 기동 검증을 다시 수행한다.
- Caddy에 비공식 plugin을 추가하면 해당 module license와 SBOM을 다시 승인한다.
- `npm audit fix --force`나 호환성 미검증 major upgrade를 release 준비 근거로 사용하지 않는다.
