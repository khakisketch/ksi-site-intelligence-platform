# KSI Core 프로덕션 이미지 — services/core/src/ksi_core/production.py 의
# build_production_app() 을 uvicorn 팩토리로 기동한다.
#
# 이 저장소는 uv workspace 다(루트 pyproject.toml [tool.uv.workspace]) — ksi-core
# 는 packages/*(ksi-domain·ksi-mission-contracts 등) workspace 멤버에 의존하므로
# services/core 디렉터리 하나만 복사해서는 `uv sync` 가 의존성을 해석할 수 없다.
# 저장소 전체(.dockerignore 로 apps/·edge/·references/·models/ 등 서버 런타임과
# 무관한 대용량 트리는 제외)를 컨텍스트로 넣는 이유다.
FROM python:3.12.14-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217

# Rasterio's bundled GDAL needs Expat when the production Core assembly imports
# the shared design-surface profile. Keep this native runtime dependency explicit.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# uv 공식 배포 이미지에서 바이너리만 가져온다(astral-sh 권장 방식) — curl 설치
# 스크립트는 빌드마다 네트워크 셸 스크립트를 실행해야 해서 이 방식보다 재현성이
# 낮다.
COPY --from=ghcr.io/astral-sh/uv:0.11.15@sha256:e590846f4776907b254ac0f44b5b380347af5d90d668138ca7938d1b0c2f98d3 /uv /uvx /bin/

WORKDIR /app

# 의존성 해석에 필요한 전체 workspace 를 복사한다 — README/코드가 없어도
# `uv sync` 는 각 workspace 멤버의 pyproject.toml 을 전부 봐야 하므로 부분
# 복사(레이어 캐시 최적화 목적의 "pyproject.toml 만 먼저 복사")는 이 저장소의
# workspace 크기(packages/*, services/*)에서 이득이 크지 않고, .dockerignore 가
# 이미 불필요한 대용량 트리를 걸러낸다.
COPY . .

# --locked: uv.lock 을 신뢰하고 재해석하지 않는다(빌드 재현성 — CI 게이트와 동일
#   원칙, README 관습).
# --all-packages: workspace 전체(ksi-core 가 의존하는 packages/* 포함)를 설치한다.
#
# --no-dev 는 쓰지 않는다 — 실측(2026-08-08, `uv sync --no-dev --dry-run`)으로
# 확인했다: uvicorn 은 이 저장소에서 **dev 전용 의존성 그룹**에만 선언돼 있다
# (루트 pyproject.toml 주석 — "apps/dashboard 로컬 개발 시 scripts/run_core_dev.py
# 가 실제 ASGI 서버를 띄우는 데만 쓴다"). dev 그룹을 포함해 전체를 빌드 시점에
# 동기화해 둔다 — 아래 CMD 가 이 venv 를 직접 실행하므로(런타임 재동기화 없음)
# 여기서 빠뜨리면 uvicorn 자체가 없는 이미지가 된다.
RUN uv sync --locked --all-packages

# non-root — 컨테이너가 침해당해도 프로세스가 root 권한을 갖지 않는다. /app 은
# ksi-core 소유로 바꾸지 않는다(COPY 의 기본 소유자 root, world-readable 권한이면
# 읽기·실행에는 충분하다) — 아래 CMD 가 venv 를 직접 실행해 런타임에 아무것도
# 다시 쓰지 않으므로, 이 유저에게 /app 쓰기 권한을 줄 이유가 없다. 이전 버전은
# CMD 를 ``uv run --locked uvicorn ...`` 으로 실행했는데, ``uv run`` 은 매 기동마다
# venv 를 lock 과 재대조해 "이미 일치해도" 쓰기 가능한 venv 를 요구한다 — 그래서
# chown -R 으로 애플리케이션 트리 전체(설치된 .venv 포함)를 런타임 유저 소유로
# 만들어야 했다. 그 경로에서 RCE 가 나면 자기 소스·의존성을 덮어써 컨테이너
# 수명 동안 지속화할 수 있다(독립 재검토 지적 A4). venv 직접 실행으로 바꾸면
# 이 쓰기 권한 자체가 필요 없어져 그 사고 클래스가 성립하지 않는다.
RUN useradd --create-home --uid 10001 ksi-core
USER ksi-core

EXPOSE 8000

# uv run 을 거치지 않고 빌드 시점에 이미 동기화된 venv 를 직접 실행한다 — 위
# useradd 단락 참조. 이 CMD 는 필수 환경변수(KSI_CORE_DATA_DIR 등, production.py
# 모듈 docstring 참조) 없이는 build_production_app() 이 RuntimeError 로 즉시
# 죽는다 — 그것이 의도된 fail-closed 동작이다. 실행에는 배포자가 env var 를
# 채워야 한다.
CMD ["/app/.venv/bin/uvicorn", "ksi_core.composition.platform_production:build_platform_production_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
