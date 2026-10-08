#!/usr/bin/env bash
# USB bulk 채널 확정용 읽기 전용 프로브 (track-a §8 선행).
#
# 왜 있나: edge/psdk-tap/src/platform/usb_bulk_glue.c 의 채널표가 **추정**을 담고
# 있다. 벤더 샘플은 interfaceNum={2,6,3} 을 쓰는데 2026-08-12 실기에는 bulk6 이
# 없었고(bulk2·3·4·5 만 존재), 여분 두 개 중 어느 것이 옛 6번 대응인지 확정하지
# 못한 채 bulk4 로 추정해 뒀다. 추정을 코드에 남긴 채 실기 세션을 또 쓰면 세션
# 하나가 통째로 "둘 중 뭐였지"에 소모된다 — 그 답을 **관측 한 번으로** 끝내려고
# 만든 스크립트다.
#
# 규율: 이 스크립트는 **아무것도 바꾸지 않는다.** 읽기·나열만 한다. 기체/짐벌
# 명령 없음, 설치·기동·삭제 없음. 그래서 비행 전이든 후든 아무 때나 안전하게
# 돌릴 수 있다. 출력은 그대로 hil_raw_logs/<세션>/ 에 넣을 수 있는 형식이다.
#
# 사용:
#   scripts/manifold/probe_usb_bulk.sh                 # 결과를 stdout 으로
#   scripts/manifold/probe_usb_bulk.sh > probe.log     # 파일로 남길 때
#
# 원격 별칭은 manifold.env / ~/.ssh/config 의 것을 그대로 쓴다(manifoldctl 과 동일).

set -uo pipefail

HOST="${MANIFOLD_SSH_ALIAS:-ksi-manifold}"

emit() { printf '%s\n' "$*"; }

emit "probed_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
emit "target_alias=${HOST}"
emit "purpose=USB bulk 채널 확정 + dpk 설치 전제 확인 (읽기 전용)"
emit "DEVICE_MUTATIONS=none"
emit "FLIGHT_OR_GIMBAL_COMMANDS=none"
emit ""

if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" 'true' 2>/dev/null; then
  emit "VERDICT=BLOCKED"
  emit "BLOCKER=SSH 도달 불가 — 매니폴드 전원/네트워크 연결을 먼저 확인할 것"
  emit ""
  emit "=== 로컬 네트워크 상태(참고) ==="
  ip -br addr 2>/dev/null || true
  exit 2
fi

# 한 번의 SSH 로 전부 모은다 — 세션 왕복을 줄이고, 관측 시점을 한 순간으로 묶는다.
ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" 'bash -s' <<'REMOTE'
set -uo pipefail
say() { printf '\n=== %s ===\n' "$*"; }

say "커널/OS"
uname -a
cat /etc/os-release 2>/dev/null | head -3

say "[핵심] /dev/usb-ffs 채널 목록"
# 이 출력이 usb_bulk_glue.c 의 채널표 추정을 확정/반증한다.
ls -la /dev/usb-ffs/ 2>&1

say "[핵심] 각 bulk 채널의 엔드포인트 파일"
# usb_bulk_glue.c 는 ep2=IN, ep1=OUT 으로 연다. ep 파일이 실제로 있는 채널만
# 후보가 된다.
for d in /dev/usb-ffs/*/; do
  [ -d "$d" ] || continue
  printf '%s: ' "$d"
  ls "$d" 2>/dev/null | tr '\n' ' '
  printf '\n'
done

say "USB gadget 구성(채널↔interface 대응의 1차 근거)"
# configfs 에 gadget 이 노출돼 있으면 function 이름에 interface 번호가 드러난다.
ls -la /sys/kernel/config/usb_gadget/ 2>&1 | head -20
for g in /sys/kernel/config/usb_gadget/*/; do
  [ -d "$g" ] || continue
  echo "--- gadget: $g"
  ls "$g/functions" 2>/dev/null
done

say "커널이 본 USB gadget/ffs 로그"
dmesg 2>/dev/null | grep -iE "ffs|gadget|dwc|usb.*bulk" | tail -30 \
  || echo "(dmesg 권한 없음 — root 필요할 수 있음)"

say "DJI 앱 프레임워크 상태(설치 목록)"
# 우리 .dpk 가 이미 올라가 있는지, 프레임워크가 살아있는지.
command -v dji_app_ctl >/dev/null && dji_app_ctl list 2>&1 || echo "(dji_app_ctl 없음/권한)"

say "DJI 상주 데몬"
ps -ef 2>/dev/null | grep -iE "dji_app_mgr|dji_sdk_agent|dji_sec" | grep -v grep

say "[판정 지표] 기체 링크 살아있나 — DUSS 메시지"
# ping 은 유효 지표가 아니다(2026-08-12 정정). Liveview uuid / device_auth 를 본다.
journalctl --since "-3 min" 2>/dev/null \
  | grep -iE "Liveview uuid info|device_auth" | tail -8 \
  || echo "(journalctl 권한 없음 또는 최근 메시지 없음)"

say "펌웨어/SDK 버전 흔적"
ls -la /vendor_app 2>/dev/null | head -10
REMOTE

rc=$?
emit ""
if [ $rc -eq 0 ]; then
  emit "VERDICT=COLLECTED"
  emit "NEXT=위 '/dev/usb-ffs 채널 목록'과 gadget functions 로 usb_bulk_glue.c 의"
  emit "     kKnownManifold3Channels 두 번째 항목(현재 interfaceNum=4 추정)을 확정할 것"
else
  emit "VERDICT=PARTIAL (원격 명령 일부 실패, rc=$rc)"
fi
