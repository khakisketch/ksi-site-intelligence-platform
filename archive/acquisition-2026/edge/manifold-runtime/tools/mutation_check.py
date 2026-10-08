#!/usr/bin/env python3
"""안전 불변식 mutation 저항성 실측 — 변이를 주입하고 ctest 가 잡는지 확인한다.

## 왜 스크립트로 남기는가

Stage C 의 선례는 변이를 **하나씩 명시**했다(.ksi/ledger.jsonl "변이 3종 전부 적발
실증"). 실행만 하고 목록을 남기지 않으면 "불변식 각각을 겨냥했는가"를 사후에 감사할
수단이 사라진다 — 실제로 2026-08-07 reviewer 재검증이 그 구멍을 통해 남아 있던 절
7개를 찾아냈다(고른 16건에 한해서만 "전부 잡힘"이 참이었다).

## 실행

    uv run python edge/manifold-runtime/tools/mutation_check.py [--sanitize]

각 변이마다 원본을 복구하므로 중간에 죽어도 소스가 오염되지 않는다(finally).
``--sanitize`` 는 ASan/UBSan 빌드로 돌린다 — signed overflow 같은 UB 는 일반
빌드에서 랩어라운드로 "정답"을 내 생존한 것처럼 보이므로, UB 를 겨냥한 변이는
이 모드에서만 정확히 판정된다.

## 등가변이

동작이 완전히 같아 **어떤 테스트로도 구분할 수 없는** 변이는 EQUIVALENT 로 표시한다.
그건 테스트 부재가 아니라 그 절이 방어적 중복이라는 뜻이고, 생존을 결함으로 세면
다음 사람이 없는 갭을 쫓게 된다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CMD = ROOT / "src/command.cpp"
SUP = ROOT / "src/supervisor.cpp"

# (id, 파일, 원문, 변이문, 겨냥한 불변식, 등가변이인가)
HDR_SUP = ROOT / "include/ksi/control_plane/supervisor.hpp"
HDR_CMD = ROOT / "include/ksi/control_plane/command.hpp"

MUTANTS: list[tuple[str, Path, str, str, str, bool]] = [
    ("M1", CMD, "if (now_utc_ms - intent.issued_at_utc_ms >= intent.ttl_ms) {",
     "if (now_utc_ms - intent.issued_at_utc_ms > intent.ttl_ms) {",
     "TTL 경계 배타성 — 만료 시점에 관대해진다", False),
    ("M2", CMD, "if (intent.ttl_ms <= 0 || intent.ttl_ms > kMaxTtlMs) {",
     "if (intent.ttl_ms <= 0) {", "TTL 상한 제거 — 무한 수명 명령", False),
    ("M3", CMD, "if (intent.ttl_ms <= 0 || intent.ttl_ms > kMaxTtlMs) {",
     "if (intent.ttl_ms < 0 || intent.ttl_ms > kMaxTtlMs) {",
     "TTL 하한 완화 — ttl=0 명령", False),
    ("M4", CMD, "if (intent.issued_at_utc_ms > now_utc_ms) {",
     "if (intent.issued_at_utc_ms > now_utc_ms + kMaxTtlMs) {",
     "미래 발행 검사 완화", False),
    ("M5", CMD, "if (active_digest.empty() || intent.authorization_digest != active_digest) {",
     "if (intent.authorization_digest != active_digest) {",
     "빈 활성계약 가드 — 위 empty 검사가 선행해 판정이 같다", True),
    ("M6", CMD, "if (intent.authorization_digest.empty()) {", "if (false) {",
     "인가 digest 부재 검사 제거", False),
    ("M7", CMD, "if (intent.kind == ActionIntentKind::kGotoViewpoint && "
     "intent.target_viewpoint_id.empty()) {", "if (false) {",
     "목적지 없는 이동 의도 허용", False),
    ("M8", SUP, "if (elapsed >= fail_closed_after_ms_) {", "if (elapsed > fail_closed_after_ms_) {",
     "fail-closed 경계 완화", False),
    ("M9", SUP, "if (elapsed >= degrade_after_ms_) {", "if (elapsed > degrade_after_ms_) {",
     "degrade 경계 완화", False),
    ("M10", SUP, "if (elapsed < 0) {", "if (false) {", "시계 역행 가드 제거", False),
    ("M11", SUP, "if (!has_heartbeat_) {", "if (false) {",
     "부팅 직후 fail-closed 기본값 제거", False),
    ("M12", SUP, "if (has_heartbeat_ && effective <= last_heartbeat_utc_ms_) {",
     "if (has_heartbeat_ && effective < last_heartbeat_utc_ms_) {",
     "중복 heartbeat 허용 — 같은 시각 재기록", False),
    ("M13", SUP, "if (observed_at_utc_ms > now_utc_ms + kHeartbeatFutureToleranceMs) {",
     "if (false) {", "미래 heartbeat 거부 제거", False),
    ("M14", SUP, "return StateAt(now_utc_ms) == SupervisorState::kNominal;",
     "return StateAt(now_utc_ms) != SupervisorState::kFailClosed;",
     "DEGRADED 에서 신규 행동 개시 허용", False),
    ("M15", SUP, "if (now_utc_ms < 0 || now_utc_ms > kMaxUtcMs) {\n        // 도메인 밖 기준 시각",
     "if (false) {\n        // 도메인 밖 기준 시각", "StateAt 도메인 가드 제거", False),
    ("M16", CMD, "if (now_utc_ms < 0 || now_utc_ms > kMaxUtcMs) {", "if (false) {",
     "VerifyActionIntent now 도메인 선검사 제거", False),
    # ── 2026-08-07 reviewer 재검증이 지적한 사각지대(S1~S7) ──
    ("S1", SUP, "if (observed_at_utc_ms < 0 || observed_at_utc_ms > kMaxUtcMs || now_utc_ms < 0 ||\n"
     "        now_utc_ms > kMaxUtcMs) {",
     "if (observed_at_utc_ms < 0 || observed_at_utc_ms > kMaxUtcMs || now_utc_ms < 0) {",
     "RecordHeartbeat 의 now 상한 가드 — M15 와 같은 클래스(UB 노출)", False),
    ("S2", CMD, "if (intent.issued_at_utc_ms > now_utc_ms) {",
     "if (intent.issued_at_utc_ms >= now_utc_ms) {",
     "issued == now 경계 — 같은 밀리초 발행 명령", False),
    ("S3", SUP, "if (fail_closed_after_ms <= degrade_after_ms) {", "if (false) {",
     "fail_closed > degrade 설정 가드 제거", False),
    ("S4", SUP, "if (observed_at_utc_ms > now_utc_ms + kHeartbeatFutureToleranceMs) {",
     "if (observed_at_utc_ms > now_utc_ms + 10 * kHeartbeatFutureToleranceMs) {",
     "미래 heartbeat 허용창 확대 — far-future 가 NOMINAL 근거가 된다", False),
    ("S5", CMD, "if (intent.issued_at_utc_ms < 0 || intent.issued_at_utc_ms > kMaxUtcMs) {",
     "if (intent.issued_at_utc_ms < 0) {", "issued_at 도메인 상한 가드 제거", False),
    ("S6", SUP, "if (observed_at_utc_ms < 0 || observed_at_utc_ms > kMaxUtcMs || now_utc_ms < 0 ||",
     "if (observed_at_utc_ms < 0 || now_utc_ms < 0 ||", "observed_at 도메인 상한 가드 제거", False),
    # ── 2026-08-07 reviewer 2차 재검증이 예측한 잔여(R1·R2) ──
    ("R1a", SUP, 'case SupervisorState::kDegraded:\n        return "DEGRADED";',
     'case SupervisorState::kDegraded:\n        return "NOMINAL";',
     "ToString(SupervisorState) 오매핑 — 진단 문자열이 상태를 속인다", False),
    ("R1b", SUP, 'case HeartbeatVerdict::kImplausibleFuture:\n        return "IMPLAUSIBLE_FUTURE";',
     'case HeartbeatVerdict::kImplausibleFuture:\n        return "RECORDED";',
     "ToString(HeartbeatVerdict) 오매핑 — 거부가 기록으로 보인다", False),
    ("R1c", CMD, 'case CommandVerdict::kExpired:\n        return "EXPIRED";',
     'case CommandVerdict::kExpired:\n        return "ACCEPTED";',
     "ToString(CommandVerdict) 오매핑 — 만료가 수락으로 보인다", False),
    ("R2a", HDR_SUP, "inline constexpr std::int64_t kHeartbeatFutureToleranceMs = 1'000;",
     "inline constexpr std::int64_t kHeartbeatFutureToleranceMs = 10'000;",
     "허용창 상수 **값** — 테스트가 심볼을 참조하면 값 변경이 안 잡힌다", False),
    ("R2b", HDR_CMD, "inline constexpr UtcMillis kMaxUtcMs = 4'102'444'800'000;",
     "inline constexpr UtcMillis kMaxUtcMs = 4'611'686'018'427'387'904;",
     "시각 도메인 상한 **값** — int64 오버플로 안전성의 유일한 근거", False),
    ("S7", SUP, "if (has_heartbeat_ && effective <= last_heartbeat_utc_ms_) {",
     "if (effective <= last_heartbeat_utc_ms_) {",
     "최초 heartbeat 의 has_heartbeat_ 가드 제거 — observed_at==0 이면 무시된다", False),
]


def _run(build_dir: Path) -> tuple[bool, bool]:
    """(빌드 성공, ctest 통과)."""
    build = subprocess.run(["cmake", "--build", str(build_dir), "-j"], capture_output=True, text=True)
    if build.returncode != 0:
        return False, False
    test = subprocess.run(["ctest", "--test-dir", str(build_dir)], capture_output=True, text=True)
    return True, test.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanitize", action="store_true", help="ASan/UBSan 빌드로 판정")
    args = parser.parse_args()

    build_dir = ROOT / ("build-mut-asan" if args.sanitize else "build-mut")
    configure = ["cmake", "-S", str(ROOT), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Debug"]
    if args.sanitize:
        # CMakeLists 의 KSI_ENABLE_SANITIZERS 를 쓴다 — 플래그를 여기서 따로 적으면
        # -fno-sanitize-recover=all 같은 필수 옵션이 한쪽에만 빠진다(실제로 그랬다).
        configure.append("-DKSI_ENABLE_SANITIZERS=ON")
    if subprocess.run(configure, capture_output=True).returncode != 0:
        print("configure 실패", file=sys.stderr)
        return 2
    built, baseline_green = _run(build_dir)
    if not (built and baseline_green):
        print("기준선이 green 이 아니다 — 변이 실험의 전제가 성립하지 않는다", file=sys.stderr)
        return 2

    survivors: list[tuple[str, str]] = []
    for mid, path, old, new, invariant, equivalent in MUTANTS:
        original = path.read_text()
        if old not in original:
            print(f"{mid:4} SKIP   원문 불일치 — {invariant}")
            survivors.append((mid, f"{invariant} (원문 불일치 — 스크립트가 낡았다)"))
            continue
        path.write_text(original.replace(old, new, 1))
        try:
            built, green = _run(build_dir)
        finally:
            path.write_text(original)
        if not built:
            print(f"{mid:4} BUILD  빌드 실패 — {invariant}")
            survivors.append((mid, f"{invariant} (빌드 실패)"))
        elif green and equivalent:
            print(f"{mid:4} 등가   판정 동일 — {invariant}")
        elif green:
            print(f"{mid:4} ★생존★ ctest 통과 — {invariant}")
            survivors.append((mid, invariant))
        else:
            print(f"{mid:4} 잡힘   ctest 실패 — {invariant}")

    _run(build_dir)  # 원본으로 되돌린 뒤 최종 재빌드
    print()
    print(f"=== 생존(등가변이 제외) {len(survivors)} / {len(MUTANTS)} ===")
    for mid, why in survivors:
        print(f"  {mid}: {why}")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
