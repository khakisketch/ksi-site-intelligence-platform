"""Neutral CLI/config value conversions shared by every Core assembly profile."""

from __future__ import annotations


def cli_optional_positive(value: int, *, name: str) -> int | None:
    """CLI 의 "0 = 없음" 규약을 생성자의 ``None`` 으로 옮긴다.

    생성자들은 0·음수를 거부하고 "없음"은 ``None`` 으로만 표현한다(조용히
    0 으로 뭉개지 않기 위해서다). CLI 쪽에서 0 을 그 뜻으로 받는 규약은 여기
    한 곳에만 둔다 — dev·production 두 조립 지점이 공유한다.

    음수는 argparse/환경변수를 통과하므로 여기서 typed 로 막는다 — 생성자까지
    흘려보내면 실패 메시지가 인자 이름을 잃는다.
    """
    if value < 0:
        raise ValueError(f"{name} 는 0(없음) 이거나 양수여야 한다: {value}")
    return value or None


__all__ = ["cli_optional_positive"]
