"""Histogram 버킷 값 회귀 테스트 (M3 관측성).

``Histogram.observe()`` 는 관측값보다 큰(``value <= bound``) 모든 버킷의
카운트를 증가시킨다 — 즉 ``counts[i]`` 는 이미 Prometheus 의 누적('le')
의미론을 담고 있다. 과거 ``render()`` 가 이 값을 running sum 으로 다시
누적해 버킷 값이 실제 관측 수보다 커지는 버그가 있었다(le="1.0" 이 관측
2건인데 4로 찍힘) — 이 파일은 그 회귀를 막는다.
"""

from __future__ import annotations

from ksi_core.metrics import Histogram


def _bucket_value(lines: list[str], *, le: str) -> int:
    """``render()`` 출력에서 ``le=\"{le}\"`` 버킷 줄 하나의 값을 뽑는다."""
    matches = [line for line in lines if f'le="{le}"' in line]
    assert len(matches) == 1, f"expected exactly one le={le!r} line, got {matches!r}"
    return int(matches[0].rsplit(" ", 1)[-1])


def test_bucket_counts_are_not_double_accumulated() -> None:
    # 회귀 재현 사례 그대로: 버킷 (0.1, 0.5, 1.0), 관측 (0.05, 0.7).
    # 0.05 는 세 버킷 모두(0.1/0.5/1.0)에 들어가고, 0.7 은 0.5 는 못 넘지만
    # 1.0 은 넘긴다(<=) — 그래서 le="1.0" 의 참값은 정확히 2 여야 한다.
    hist = Histogram("test_hist", "테스트용", buckets=(0.1, 0.5, 1.0))
    hist.observe(0.05)
    hist.observe(0.7)

    lines = hist.render()

    assert _bucket_value(lines, le="0.1") == 1
    assert _bucket_value(lines, le="0.5") == 1
    assert _bucket_value(lines, le="1.0") == 2
    assert _bucket_value(lines, le="+Inf") == 2


def test_bucket_counts_are_monotonically_nondecreasing() -> None:
    # Prometheus 히스토그램 불변식: le 오름차순으로 버킷 값이 감소해선 안 된다.
    hist = Histogram("test_hist_mono", "테스트용", buckets=(0.1, 0.5, 1.0, 2.5, 5.0))
    for value in (0.02, 0.2, 0.2, 0.6, 3.0, 9.0):
        hist.observe(value)

    lines = hist.render()
    bucket_values = [_bucket_value(lines, le=str(b)) for b in (0.1, 0.5, 1.0, 2.5, 5.0)]
    inf_value = _bucket_value(lines, le="+Inf")

    assert bucket_values == sorted(bucket_values), "버킷 값이 le 오름차순으로 단조증가해야 한다"
    assert bucket_values[-1] <= inf_value
    assert inf_value == 6  # 9.0 은 어떤 유한 버킷에도 안 들어가지만 +Inf/count 는 잡는다


def test_sum_and_count_unaffected_by_bucket_fix() -> None:
    hist = Histogram("test_hist_sumcount", "테스트용", buckets=(1.0,))
    hist.observe(0.4)
    hist.observe(0.6)

    lines = hist.render()
    sum_line = next(line for line in lines if line.startswith("test_hist_sumcount_sum"))
    count_line = next(line for line in lines if line.startswith("test_hist_sumcount_count"))

    assert sum_line.endswith(" 1.0")
    assert count_line.endswith(" 2")


def test_labeled_series_render_independently() -> None:
    hist = Histogram("test_hist_labels", "테스트용", buckets=(0.1, 1.0))
    hist.observe(0.05, method="GET")
    hist.observe(0.05, method="GET")
    hist.observe(5.0, method="POST")

    lines = hist.render()
    get_lines = [line for line in lines if 'method="GET"' in line]
    post_lines = [line for line in lines if 'method="POST"' in line]

    get_bucket_01 = next(line for line in get_lines if 'le="0.1"' in line)
    post_bucket_01 = next(line for line in post_lines if 'le="0.1"' in line)

    assert get_bucket_01.rsplit(" ", 1)[-1] == "2"
    assert post_bucket_01.rsplit(" ", 1)[-1] == "0"
