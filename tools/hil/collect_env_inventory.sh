#!/usr/bin/env bash
# Manifold 3 환경 인벤토리 수집 (HARDWARE_SESSION_PLAYBOOK.md 1단계 산출물).
#
# 실행 위치: Manifold 3 온보드(타깃 aarch64 하드웨어). 호스트 PC에서 돌려도 스크립트
# 자체는 실패하지 않지만, 그 결과는 세션 증거로 쓸 수 없다(타깃이 아니므로).
#
# 이 스크립트는 값을 하드코딩하지 않는다 — JetPack/L4T, TensorRT/CUDA/cuDNN, RAM/디스크,
# DJI PSDK 버전 등은 전부 실행 시점에 조회한다. 조회할 수 없는 항목은 실패로 스크립트를
# 죽이지 않고 "MISSING: <이유>"로 기록한 채 계속 진행한다 — 부분 인벤토리도 증거다
# (하나가 안 잡힌다고 나머지 항목까지 못 쓰게 되면 세션 진행에 방해가 된다).
#
# DJI PSDK 버전 조회 경로는 이 스크립트 작성 시점에 확정할 수 없다(설치 방식이
# 공식 샘플/SDK 문서에 따라 달라질 수 있음) — 여러 후보 경로를 시도하고, 전부
# 실패하면 MISSING으로 남긴다. 실기 세션에서 실제 설치 경로를 확인하면 §PSDK 섹션에
# 후보 경로를 추가할 것.
set -uo pipefail  # 개별 조회 실패로 스크립트 전체가 죽지 않도록 -e 는 쓰지 않는다

SESSION_ID="${SESSION_ID:?SESSION_ID 환경변수 필수 — docs/hil/RAW_LOG_CONVENTIONS.md 형식(SESS-<UTC>-<기체SN 또는 PENDING-SN>)을 따를 것. 예: SESSION_ID=SESS-20260728T060000Z-PENDING-SN}"
OUT_ROOT="${HIL_RAW_LOG_ROOT:-hil_raw_logs}"
OUT_DIR="${OUT_ROOT}/${SESSION_ID}/01_env_inventory"
mkdir -p "$OUT_DIR"

UTC_TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${OUT_DIR}/${UTC_TS}__env_inventory.json"

# query <label> <command...>
# 명령을 실행해 stdout을 값으로 쓴다. 실패/빈 출력이면 MISSING 사유를 값으로 남긴다.
# 결과는 환경변수 KSI_Q_<label>에 담아 이후 python3 JSON 조립 단계에서 읽는다.
query() {
  local label="$1"
  shift
  local out
  if out="$("$@" 2>/dev/null)" && [[ -n "$out" ]]; then
    printf -v "KSI_Q_${label}" '%s' "$out"
  else
    printf -v "KSI_Q_${label}" 'MISSING: `%s` 실패 또는 빈 출력 (미설치 가능성)' "$*"
  fi
  export "KSI_Q_${label}"
}

# 셸 파이프라인이 필요한 항목은 별도 함수로 처리(query는 단일 커맨드+인자만 받음).
query_pipe() {
  local label="$1"
  local cmd="$2"
  local out
  if out="$(eval "$cmd" 2>/dev/null)" && [[ -n "$out" ]]; then
    printf -v "KSI_Q_${label}" '%s' "$out"
  else
    printf -v "KSI_Q_${label}" 'MISSING: `%s` 실패 또는 빈 출력' "$cmd"
  fi
  export "KSI_Q_${label}"
}

echo "== KSI HIL 환경 인벤토리 수집 시작: ${UTC_TS} =="

# --- 기본 시스템 ---
query HOSTNAME hostname
query_pipe UNAME 'uname -a'
query_pipe OS_RELEASE 'cat /etc/os-release'
query_pipe UPTIME 'uptime -p'

# --- JetPack / L4T (Jetson 계열 기준 — Manifold 3가 다른 SoC면 MISSING으로 남고
#     그 사실 자체가 유의미한 인벤토리 데이터다) ---
query_pipe L4T_RELEASE 'cat /etc/nv_tegra_release'
query_pipe JETPACK_APT 'dpkg -l | grep -i nvidia-jetpack'

# --- CUDA ---
query_pipe CUDA_NVCC 'nvcc --version'
query_pipe CUDA_VERSION_FILE 'cat /usr/local/cuda/version.json 2>/dev/null || cat /usr/local/cuda/version.txt'

# --- cuDNN ---
query_pipe CUDNN_HEADER 'grep -R "CUDNN_MAJOR\|CUDNN_MINOR\|CUDNN_PATCHLEVEL" /usr/include/cudnn_version.h /usr/include/*/cudnn_version.h 2>/dev/null'
query_pipe CUDNN_APT 'dpkg -l | grep -i libcudnn'

# --- TensorRT ---
query_pipe TENSORRT_APT 'dpkg -l | grep -i tensorrt'
query_pipe TENSORRT_PY 'python3 -c "import tensorrt; print(tensorrt.__version__)"'

# --- RAM / 디스크 ---
query_pipe RAM_FREE 'free -h'
query_pipe DISK_ROOT 'df -h /'
query_pipe DISK_ALL 'df -h'

# --- CPU ---
query_pipe CPU_INFO 'lscpu'
query NPROC nproc

# --- 네트워크 인터페이스 (Manifold 이벤트 네트워크 경로 — SPIKE-DJI-07 관련 맥락) ---
query_pipe NET_IFACES 'ip -brief addr'

# --- Python / 관련 패키지 ---
query_pipe PYTHON_VERSION 'python3 --version'
query_pipe PIP_TORCH 'python3 -m pip show torch 2>/dev/null | grep -i version'

# --- Docker (있다면) ---
query_pipe DOCKER_VERSION 'docker --version'

# --- KSI 빌드 식별 ---
query_pipe GIT_COMMIT 'git rev-parse HEAD'
query_pipe GIT_STATUS 'git status --porcelain'

# --- DJI PSDK 버전 (조회 경로 불확실 — 후보 다건 시도) ---
# TODO(실기 세션): 정확한 PSDK 설치 경로/버전 조회 방법은 DJI 공식 샘플 빌드(2단계) 시
# 확인 후 아래 후보 목록에 실제 경로를 추가할 것. 지금은 흔한 후보만 시도한다.
query_pipe PSDK_VERSION_HEADER 'grep -R "PSDK_VERSION\|DJI_SDK_VERSION" /opt/*/include/*.h /usr/local/include/*.h 2>/dev/null | head -5'
query_pipe PSDK_PKG_SEARCH 'find / -maxdepth 6 -iname "*payload-sdk*" -o -iname "*psdk*" 2>/dev/null | head -10'

echo "== 조회 완료, JSON 조립 중 =="

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 없음 — JSON 조립 불가, key=value 텍스트로 대체 기록" >&2
  OUT_FILE="${OUT_DIR}/${UTC_TS}__env_inventory.txt"
  {
    echo "session_id=${SESSION_ID}"
    echo "collected_at_utc=${UTC_TS}"
    for v in $(compgen -v KSI_Q_); do
      echo "${v#KSI_Q_}=${!v}"
    done
  } > "$OUT_FILE"
else
  python3 - "$OUT_FILE" "$SESSION_ID" "$UTC_TS" <<'PYEOF'
import json
import os
import sys

out_file, session_id, utc_ts = sys.argv[1], sys.argv[2], sys.argv[3]

fields = {
    k[len("KSI_Q_"):]: v
    for k, v in os.environ.items()
    if k.startswith("KSI_Q_")
}

payload = {
    "session_id": session_id,
    "collected_at_utc": utc_ts,
    "fields": fields,
}

with open(out_file, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    f.write("\n")

print(f"기록 완료: {out_file}")
PYEOF
fi

echo "== 완료: ${OUT_FILE} =="
echo "이 파일을 SpikeEvidence.raw_log_ref / manifold_image / psdk_version 필드 근거로 쓸 것."
