#!/usr/bin/env bash
# manifoldctl 공통 함수 — 설정 로딩·ssh 헬퍼·로깅·git 상태 조회.
# 단독 실행되지 않는다 — manifoldctl이 source한다.
set -euo pipefail

MANIFOLD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFOLD_REPO_ROOT="$(cd "$MANIFOLD_SCRIPT_DIR/../.." && pwd)"

# --- 로깅 ---
# 설정 로드보다 먼저 정의한다 — 폴백 경고(아래)가 이 함수를 바로 써야 한다.
mf_log()  { echo "[manifoldctl] $*" >&2; }
mf_die()  { echo "[manifoldctl] ✗ $*" >&2; exit 1; }

# --- 설정 로드 ---
# manifold.env가 있으면 우선 사용, 없으면 example의 기본값으로 폴백한다(문서 예시가
# 그대로 동작해 처음 쓰는 사람이 즉시 doctor를 돌려볼 수 있게 하기 위함).
# 단, 폴백은 절대 침묵하지 않는다 — example의 호스트/경로는 실제 실기와 다를 수 있고,
# 이 저장소는 '조용한 no-op'을 극도로 경계한다(감사 #11: 잘못된 host/경로로 조용히
# 배포될 위험).
_env_file="$MANIFOLD_SCRIPT_DIR/manifold.env"
if [ ! -f "$_env_file" ]; then
  mf_log "⚠ scripts/manifold/manifold.env 없음 — manifold.env.example 기본값으로 폴백한다."
  mf_log "⚠ example의 MANIFOLD_SSH_HOST/REMOTE_ROOT가 실제 실기와 다르면 잘못된 대상에 배포될 수 있다."
  mf_log "⚠ manifold.env.example을 복사해 scripts/manifold/manifold.env로 만들 것(gitignored, 머신별 설정)."
  _env_file="$MANIFOLD_SCRIPT_DIR/manifold.env.example"
fi
# shellcheck source=/dev/null
set -a
source "$_env_file"
set +a

: "${MANIFOLD_SSH_HOST:?manifold.env에 MANIFOLD_SSH_HOST 필요}"
: "${MANIFOLD_REMOTE_ROOT:?manifold.env에 MANIFOLD_REMOTE_ROOT 필요}"
: "${MANIFOLD_BUILD_IMAGE:?manifold.env에 MANIFOLD_BUILD_IMAGE 필요}"

# --- ssh 헬퍼 — BatchMode 강제(비대화형, 키 인증 실패 시 즉시 에러로 원인이 드러남) ---
mf_ssh() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$MANIFOLD_SSH_HOST" "$@"
}

mf_rsync_to_device() {
  # $1: 로컬 경로(끝에 / 필요 시 호출자가 붙인다), $2: 원격 상대 경로(REMOTE_ROOT 기준)
  # 호출 시점은 항상 build_dir(빌드 산출물 디렉터리) 하나뿐이다 — 저장소 전체를
  # 옮기지 않는다. 예전에 있던 '.git/.venv/node_modules/apps 등' exclude는 저장소
  # 전체 sync를 가정한 죽은 패턴이라 오해를 부른다(감사 #9) — 실제 호출 대상에 맞춰
  # CMakeFiles(중간 오브젝트·의존성 캐시, 실기에서 쓸 일 없고 용량만 큼)만 제외한다.
  rsync -az --delete \
    --exclude 'CMakeFiles' \
    -e "ssh -o BatchMode=yes" \
    "$1" "${MANIFOLD_SSH_HOST}:${MANIFOLD_REMOTE_ROOT}/$2"
}

mf_rsync_from_device() {
  rsync -az -e "ssh -o BatchMode=yes" "${MANIFOLD_SSH_HOST}:${MANIFOLD_REMOTE_ROOT}/$1" "$2"
}

mf_scp_to_device() {
  # 단일 파일 전송(디렉터리 트리 동기화가 아니다 — mf_rsync_to_device 의 --delete 는
  # DPK 스테이징처럼 다른 파일과 공존하는 디렉터리에 부적합).
  # $1: 로컬 파일 경로, $2: 원격 상대 경로(REMOTE_ROOT 기준, 파일명 포함).
  scp -o BatchMode=yes -o ConnectTimeout=10 "$1" "${MANIFOLD_SSH_HOST}:${MANIFOLD_REMOTE_ROOT}/$2"
}

# --- git 상태 — dirty 배포 차단의 근거 ---
mf_git_sha() { git -C "$MANIFOLD_REPO_ROOT" rev-parse HEAD; }
mf_git_is_dirty() {
  [ -n "$(git -C "$MANIFOLD_REPO_ROOT" status --porcelain 2>/dev/null)" ]
}

mf_utc_now() {
  # Manifold 실기 collect_env_inventory.sh와 동일한 타임스탬프 형식(RAW_LOG_CONVENTIONS §2)
  date -u +%Y%m%dT%H%M%SZ
}
