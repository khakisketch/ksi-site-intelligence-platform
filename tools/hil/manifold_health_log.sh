#!/usr/bin/env bash
# Manifold 3 온보드 상태 기록기 — "장치가 사라졌다"를 호스트 관측만으로 판정하지 않기 위한 것.
#
# ## 왜 있는가
#
# 2026-08-03·08-04 두 HIL 세션이 "실기가 서브넷에서 완전히 사라졌다"로 멈췄다. 그 판정은
# 전부 호스트 측 스윕만으로 내려진 것이었고, 기기 안에서 무슨 일이 있었는지는 아무도
# 보지 못했다(셸이 없었다). 2026-08-12 세션에서 이 스크립트를 심은 뒤 같은 이탈이
# 재현됐고, 기록을 열어보니 **기기는 그 내내 정상 가동 중이었고 IP 도 그대로였다** —
# 끊긴 것은 관측자–기기 사이 경로였다. 자세한 내용은 docs/hil/HARDWARE_SESSION_PLAYBOOK.md
# 의 3.0단계 "장치가 사라진다 판정이 반증됐다" 절.
#
# ## 설치 (실기에서, sudo 불필요)
#
#   scp tools/hil/manifold_health_log.sh <manifold-host>:~/ksi_health_log.sh
#   ssh <manifold-host> 'chmod +x ~/ksi_health_log.sh && \
#     { crontab -l 2>/dev/null | grep -v ksi_health_log.sh; \
#       echo "*/5 * * * * $HOME/ksi_health_log.sh"; } | crontab -'
#
# `dji` 계정은 sudo 가 없어(2026-08-12 실측) systemd 저널 영속화(/var/log/journal)를
# 켤 수 없다 — 그래서 사용자 crontab 으로 요약만 남긴다. 이 파일은 재부팅해도 지워지지
# 않는다(홈 디렉터리).
#
# ## 용량
#
# 한 줄 요약만 남긴다. 초기 판은 저널 원문을 통째로 붙여 5분에 5MB 를 먹었는데, 실기
# 루트 파티션 여유가 8.6GB 뿐이라 며칠이면 찼다. 지금은 하루 수백 KB 수준이고 30일 뒤
# 자동 삭제한다.

set -uo pipefail

DIR="${KSI_HEALTH_LOG_DIR:-$HOME/ksi_health_log}"
mkdir -p "$DIR"
LOG="$DIR/$(date +%F).log"

{
  # uptime 첫 필드만 — /proc/uptime 은 "가동초 유휴초" 두 값을 준다. 이 값이 이탈
  # 판정의 핵심이다: 이탈 전후로 **연속 증가**하면 기기는 멈춘 적이 없다.
  printf '=== %s uptime=%ss ===\n' "$(date -Iseconds)" "$(cut -d' ' -f1 /proc/uptime)"

  # IP 를 함께 남긴다 — 기록이 이어졌는데 IP 가 바뀌었으면 DHCP 갱신이고,
  # IP 까지 같으면 기기 문제가 아니라 경로 문제다.
  ip -br addr | tr '\n' ' '
  printf '\n'

  # 경고 이상 로그를 **프로세스별 건수로만** 요약한다(원문 아님 — 위 용량 단락).
  journalctl --no-pager -q -p warning --since '-6 minutes' 2>/dev/null \
    | awk '{print $5}' | sort | uniq -c | sort -rn | head -8
} >> "$LOG" 2>&1

find "$DIR" -name '*.log' -mtime +30 -delete 2>/dev/null || true
