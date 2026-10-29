# 다른 컴퓨터에서 개발 이어가기

이 문서는 개발 환경을 다시 준비하는 안내다. 완료 판정이나 다음 작업의 별도 원장이 아니다.
실제 진행과 차단 사항은 [현재 원장](ledger/CURRENT.md), 제품 범위는
[제품 상태](superpowers/product-state.md), 구현별 증거는 원장에서 연결한 문서를 따른다.

## 1. 소스와 상태 확인

```bash
git clone https://github.com/khakisketch/ksi-site-intelligence-platform.git
cd ksi-site-intelligence-platform
git status --short --branch
git log -1 --oneline
```

**GitHub에는 커밋하고 푸시한 내용만 있다.** 이 인계는 개발 중인 스냅샷이며 릴리스나
운영 배포 승인이 아니다. 다른 컴퓨터의 미커밋 변경, 미추적 파일,
stash, 로컬 브랜치, `.opencode/` 및 `/tmp/opencode/` 증거는 clone되지 않는다. 인계받은
커밋과 [현재 원장](ledger/CURRENT.md)을 대조하고, 원래 컴퓨터의 작업을 별도 확인하기
전에는 최신 통합 후보가 모두 올라왔다고 가정하지 않는다. 로컬 임시 경로를 가리키는
과거 증거는 새 컴퓨터에서 없어질 수 있으며, 부재를 검증 통과로 해석하지 않는다.

인계 전 GitHub `main`은 `3ace9fc`, 통합 작업의 출발 커밋은 `1c43892`였다. 이는
인계 전 상태를 구별하기 위한 기록이며 최신 원격 상태를 뜻하지 않는다. 실제 인계 시
`git log -1`과 현재 원장으로 받은 내용을 다시 확인한다. 원래 `main` 작업트리와 공용
stash는 별도 로컬 작업으로 보존되어 있으며 이 문서나 clone만으로 이전되지 않는다.

정책상 차단된 다중 프로세스 OIDC 진단 및 출처가 확인되지 않은 별도 진단 파일은 이
인계에 포함하지 않는다. 해당 파일은 원래 컴퓨터에 보존되며, 다른 도구·설정으로
차단된 시험을 재시도하라는 의미가 아니다.

먼저 [제품과 권위 진입점](00_READ_FIRST.md), 저장소 루트의 `AGENTS.md`,
[소스 책임](../REPOSITORY_STRUCTURE.md), [Console 작업 원장](ledger/work/2026-10-26-console.md)을
읽는다. `references/repos/`는 읽기 전용 참고 서브모듈이며 일반 개발·CI에서 내용을
받을 필요가 없다. 취득·비행·고객 재구성 실행은 현행 제품 책임 밖이다.

## 2. 개발 의존성

- Linux 개발 환경, Python **3.12** 및 `uv`, Node.js **22**와 npm이 필요하다. CI는
  Node 22를 사용하며, 별도 패키징 증거는 Linux ARM64의 Node 22.18 범위에 한정된다.
  다른 운영체제·CPU에서도 같은 결과가 난다고 가정하지 않는다.
- 아래 설치는 패키지 레지스트리 접근과 저장공간이 필요하다. 본인 환경에서 실행하기 전에
  네트워크·라이선스·조직 정책을 확인한다. 선택적 모델·SDK·고객 자료는 자동 확보하지 않는다.
- `uv.lock`과 `apps/dashboard/package-lock.json`을 사용한다. lock 갱신은 별도 변경이다.

```bash
# 저장소 루트
uv sync --locked --all-packages

# Console
cd apps/dashboard
npm ci
```

## 3. 로컬 실행과 검증

새 컴퓨터에서 기존 프로세스·포트·로컬 데이터가 없는지 먼저 확인한다. 다음 명령은
개발용 Local Identity, Core, Console을 localhost에 기동한다. `.dev-data/`에 로컬 저널과
개발용 비밀이 만들어지므로 고객 데이터나 운영 자격증명을 넣지 않는다.

```bash
# apps/dashboard에서: Tailscale 설정을 변경하지 않는 로컬 경로
npm run dev:local
```

개발 서버가 출력한 localhost 주소로 접속한다. `npm run dev`는 별도로 Tailscale Serve
설정을 변경하므로 원하는 경우에만 [Dashboard 안내](../apps/dashboard/README.md)를 보고
사용한다. 단순 로컬 구동은 검사 정책 활성화, 실제 데이터 처리 또는 배포 수용이 아니다.
**localhost 바인딩은 외부 네트워크 격리가 아니다.** 일부 지도는 OpenStreetMap 타일을
요청하며, 이때 열람한 지도 범위와 클라이언트 IP가 제공자에게 노출될 수 있다. 지도 제공자
사용은 별도 [G4 결정](product/BETA_PROGRAM.md)이며 AI 반출 동의와 같지 않다. 확인되지 않은
자료는 사용하지 말고, 합성 시험에서는 외부 요청을 차단한다.

기본 소프트웨어 검증 명령은 다음과 같다. 테스트의 skip은 통과가 아니며, 네트워크·폰트·
이미지·브라우저·호스트 권한 등 환경 차이와 정확한 소스/lock을 함께 기록한다.
Dashboard 빌드는 `next/font/google` 글꼴을 사용하므로 글꼴을 가져오기 위한 외부 접근이
발생할 수 있다. 네트워크 허가가 없으면 이를 차단하고, 이미 준비된 오프라인 글꼴로
검증했는지와 빌드 실패 여부를 구분해 기록한다.
서명·권위 경계 시험은 다른 사용자가 쓸 수 있는 임시 디렉터리 조상을 거부할 수 있다.
그 경우 소유자만 쓸 수 있는 새 임시 디렉터리를 사용하고, 공유 디렉터리의 권한을
바꾸어 시험을 통과시키지 않는다.

```bash
# dev:local을 중지한 뒤, apps/dashboard에서 저장소 루트로 이동
cd ../..
uv run --locked ruff check .
uv run --locked mypy packages services tests tools
uv run --locked pytest -q

# 저장소 루트에서 Console로 이동
cd apps/dashboard
npm test
npm run lint
npx tsc --noEmit
npm run build
```

브라우저·패키징·전체 CI 및 실제 격리 호스트 검증은 위 명령만으로 대체되지 않는다.
실행 조건은 [Dashboard 안내](../apps/dashboard/README.md),
[CI 설정](../.github/workflows/ci.yml),
[파서 호스트 요건](ops/PARSER_SANDBOX_HOST_REQUIREMENTS.md)과 현재 원장을 확인한다.
과거의 합성 검증은 고객 데이터의 권리·정확도·현장 수용이나 원격 CI 통과를 뜻하지 않는다.

새 컴퓨터에서 격리 파서를 실행할 수 있는지 비변경 사전 점검을 하려면 다음을 실행한다.
`READY`는 해당 호스트가 시험을 시작할 수 있다는 뜻이지 파서→검토 전체 시험의 통과가
아니다. `BLOCKED`이면 호스트 보안 설정을 임의로 완화하지 않는다.
등록 중단을 이용한 롤백 복구는 별도의
[Core 안전 경계](../services/core/README.md#restart-only-registration-recovery-stop)를 따른다.
이 문서는 운영 설정을 켜거나 실제 데이터에 시험 요청을 보내라는 승인이 아니다.

```bash
# 현재 apps/dashboard에 있다면 저장소 루트로 이동
cd ../..
uv run --locked --no-sync python tools/verify_parser_sandbox_host.py
```

계정 전환 결함의 선택적 합성 진단은 `apps/dashboard/diagnostics/`에 보존되어 있다. 이전
후보에서는 이전 계정으로 돌아가는 문제가 재현됐다. 이 진단은 로컬 서버와 브라우저를
사용하며 브라우저 요청 필터만으로 운영체제 네트워크 격리가 보장되지 않는다. 검증된
작업 전용 격리 실행 경로가 준비되기 전에는 임의의 호스트에서 실행하거나 브라우저를
다운로드하지 않는다. 이 단일 프로세스 진단은 실제 OIDC 로그인·토큰 갱신·다중 인스턴스
검증이 아니며, 단일 진단 통과만으로 인증 문제가 해결됐다고 단정하지 않는다.
실제 로컬 OIDC 로그인 후에도 같은 경합을 합성 시험에서 재현했지만, 그 시험 설비는
현재 이 컴퓨터의 임시 디렉터리에만 있다. 한 프로세스·갱신 없는 사례이며 다른 컴퓨터로
자동 이전되지 않는다. 자세한 현재 상태는 [작업 원장](ledger/work/2026-10-26-console.md)을 따른다.

다중 프로세스 OIDC refresh·늦은 callback 확장 시험은 실행 보안 정책으로 차단됐다. 다른
도구나 설정으로 재시도하거나 우회하지 않는다.

제목 연속성도 현재 확인된 미해결 항목이다. 이전 합성 시험에서는 화면 이동 중 빈 제목이
관측됐다. `e2e/site-title-continuity.spec.ts`는 현재 기본 로컬·외부 대상 실행에서 모두
명시적으로 제외되며, 이는 통과가 아니다. 격리된 전용 실행 경로도 아직 없다. 공통
Playwright 설정은 시험의 제외·거부 검사보다 개발 서버를 먼저 시작할 수 있으므로 이 진단을
공통 설정으로 실행하지 않는다.
브라우저 요청 필터만으로 운영체제 네트워크 격리를 보장할 수 없다. 현재 상태는
[작업 원장](ledger/work/2026-10-26-console.md)을 따르며, 자동 시험만으로 실제 스크린리더
사용이나 접근성 수용을 주장하지 않는다.

첫 사용 진단 `e2e/zz-owner-journey-probe.spec.ts`도 현재 비활성이다. 이전 합성 시험의
이미지 준비 중 승인되지 않은 외부 패키지 저장소 접근과 설치가 있었고, 안전한 오프라인
전용 실행기는 아직 검증되지 않았다. 기존 증거를 보존하고, 사용자 승인 없이 외부 접속이나
설치를 반복하지 않는다. 자세한 사실과 경계는 [작업 원장](ledger/work/2026-10-26-console.md)을
확인한다.

## 4. 보존과 반출 주의

- `.dev-data/`, `.env*` 실물, 서명키·토큰, 고객 원본·파생 자료와 브라우저 세션/로그는
  GitHub에 올리지 않는다. 실제 데이터 이전은 별도 권한·보관·보안 절차가 필요하다.
- 기존 컴퓨터의 미커밋 작업과 stash는 GitHub로 자동 이전되지 않는다. 보존 대상의 소유권과
  차이를 확인하기 전에는 reset, 강제 push, stash 삭제 또는 일괄 정리를 하지 않는다.
- 루트 `node_modules/`, 루트 `.playwright-cli/`, `docs/design/.playwright-cli/`는 로컬
  생성물로 Git에서 제외한다. 무시 규칙은 기존 파일을 삭제하거나 새 컴퓨터로 이전하지 않는다.
- 현재 저장소는 공개 GitHub 저장소다. 새 커밋뿐 아니라 **푸시될 이력 전체**와 미추적 파일의
  비밀·고객 자료·임시 브라우저 산출물을 점검하고 필요한 소스만 명시적으로 포함한다.
- 운영 배포, 외부 계정·호스트, TLS, 고객 자료와 정확도·현장 수용은 별도 권한과 증거가
  필요하다. 로컬 합성 성공으로 이 경계를 대체하지 않는다.
