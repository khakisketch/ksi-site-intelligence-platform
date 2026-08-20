#!/usr/bin/env bash
# Rebuild and exercise the SQLite/WAL store-forward contract in the pinned
# Manifold 3 development container.  This leaves no build artifacts in the
# worktree and fails before CMake when Docker is unavailable.
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
image_tag="${KSI_EDGE_SQLITE_IMAGE:-ksi-manifold3-build:sqlite-gate}"

case "$(uname -m)" in
  aarch64|arm64) platform="linux/arm64" ;;
  x86_64|amd64) platform="linux/arm64" ;;
  *)
    printf 'Unsupported host architecture for the Manifold 3 SQLite gate: %s\n' "$(uname -m)" >&2
    exit 2
    ;;
esac

if ! command -v docker >/dev/null 2>&1; then
  printf 'Docker is required for the SQLite/WAL development-container gate.\n' >&2
  exit 2
fi

# The Dockerfile context intentionally contains only the Dockerfile: repository
# sources arrive through a read-only bind mount, while the CMake build lives in
# the container's /tmp.  That avoids both a huge build context and root-owned
# build files in the worktree.
docker build --platform "$platform" \
  --file "$repo_root/edge/docker/manifold3-build.Dockerfile" \
  --tag "$image_tag" \
  "$repo_root/edge/docker"

docker run --rm --platform "$platform" \
  --user "$(id -u):$(id -g)" \
  --volume "$repo_root:/workspace:ro" \
  --workdir /workspace \
  "$image_tag" \
  /bin/bash -lc '
    build_dir="$(mktemp -d)"
    trap "rm -rf \"$build_dir\"" EXIT
    cmake -S edge/manifold-runtime -B "$build_dir" \
      -DKSI_BUILD_TESTS=ON \
      -DKSI_REQUIRE_SQLITE=ON \
      -DCMAKE_BUILD_TYPE=RelWithDebInfo
    cmake --build "$build_dir" --parallel
    # The pinned Manifold CMake 3.16 predates ctest --test-dir.
    cd "$build_dir"
    ctest --output-on-failure
  '
