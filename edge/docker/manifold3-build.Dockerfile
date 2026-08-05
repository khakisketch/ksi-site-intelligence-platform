# Manifold 3 정본 빌드 컨테이너 — arm64 Ubuntu 20.04
#
# 목적: 실기(Manifold 3 온보드)의 userland를 그대로 재현한 빌드 환경. 이 컨테이너에서
# 통과하면 gcc 9.4/cmake 3.16.3/glibc 2.31 회귀는 실기 없이도 잡힌다 — "컨테이너가
# 곧 lint"다(ADR-KSI-009 참조).
#
# 실기 실측(2026-08-03 HIL 세션, SESS-20260803T125616Z-PENDING-SN):
#   gcc 9.4.0 / cmake 3.16.3 / glibc 2.31 / Ubuntu 20.04.6 LTS / Python 3.8.10
# 이 Dockerfile은 그 값을 apt로 그대로 재현한다(버전 고정이 아니라 20.04 태그가
# 곧 버전 앵커 — 20.04 apt 저장소가 유지되는 한 이 조합은 안정적으로 재현된다).
#
# 개발 PC가 이미 aarch64이므로 이 이미지를 네이티브로 돌리면 QEMU가 필요 없다.
# CI(x86-64 러너)에서는 QEMU 등록 후 --platform=linux/arm64로 실행한다
# (job 레벨 `container:` 키는 쓰지 않는다 — QEMU 등록보다 먼저 컨테이너가 기동돼
# 실패한다).

# --platform은 이 Dockerfile에 하드코딩하지 않는다 — `docker buildx build --platform
# linux/arm64`(빌드 시)와 `docker run --platform linux/arm64`(CI 실행 시)로 외부에서
# 지정한다. FROM에 상수를 박으면 buildx가 경고하고, CI에서 QEMU 등록 순서 문제와도
# 얽힌다(§ CI job 주석 참조).
FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# 실기와 동일한 빌드 도구 체인. 버전을 고정하지 않는다 — 20.04 apt가 곧 앵커이고,
# 실기 자체도 20.04.6 apt로 설치된 9.4.0/3.16.3이다(고정 버전 지정은 오히려
# "실기가 그 사이 업데이트되면 컨테이너와 다시 벌어진다"는 새 드리프트를 만든다).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    python3 \
    python3-pip \
    pkg-config \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ABI 게이트가 쓰는 도구(readelf 등)는 binutils에 포함(build-essential 의존성으로 이미 옴).

WORKDIR /workspace

# 기본 진입점은 셸 — manifoldctl/CI가 필요한 명령을 넘겨 실행한다.
CMD ["/bin/bash"]
