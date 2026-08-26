# External VM Dependency Baseline

이 문서는 KSI Operations Console 외부 VM 조립에 새로 추가된 런타임 의존성과 release
검증 기준을 고정한다. 버전 고정은 보안 승인이나 실제 고객 데이터 배포 승인을 뜻하지 않는다.

## 고정된 구성요소

| 구성요소 | 고정 위치 | 현재 해석 버전 | 라이선스 | 용도 |
|---|---|---:|---|---|
| Auth.js (`next-auth`) | `apps/dashboard/package.json`, `package-lock.json` | `5.0.0-beta.32` | ISC | OIDC Authorization Code + PKCE, 암호화 서버 세션 |
| PyJWT | `services/core/pyproject.toml`, `uv.lock` | `2.13.0` | MIT | Core OIDC JWT/JWKS 검증 |
| Caddy image | `deploy/compose.vm.yaml` | `2.10.2-alpine` | Apache-2.0 | TLS ingress |
| Node image | `apps/dashboard/Dockerfile` | `22.18-alpine` | MIT | Dashboard build/runtime |
| Playwright Test | `apps/dashboard/package.json`, `package-lock.json` | `1.62.1` | Apache-2.0 | 4개 기준 폭 OIDC·반응형 브라우저 회귀 |
| axe-core | `apps/dashboard/package.json`, `package-lock.json` | `4.13.0` | MPL-2.0 | serious·critical 접근성 자동 검사 |

Caddy의 현재 로컬 pull digest는
`sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d`다.
태그와 digest는 release 후보 생성 시 다시 대조하고, 승인된 digest로 배포 manifest를 고정한다.

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
syft caddy:2.10.2-alpine -o cyclonedx-json=caddy-image.cdx.json
```

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
- Caddy에 비공식 plugin을 추가하면 해당 module license와 SBOM을 다시 승인한다.
- `npm audit fix --force`나 호환성 미검증 major upgrade를 release 준비 근거로 사용하지 않는다.
