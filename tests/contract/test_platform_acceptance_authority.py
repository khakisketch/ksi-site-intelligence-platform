"""The PRD's platform acceptance link must resolve to the criteria it names."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_prd_platform_acceptance_link_resolves_to_open_criteria() -> None:
    prd = ROOT / "docs/product/MASTER_PRD_v3.0.md"
    match = re.search(r"\[플랫폼 P-AC-01\.\.06\]\(([^)]+)\)", prd.read_text(encoding="utf-8"))
    assert match is not None
    target_path, separator, fragment = match.group(1).partition("#")
    target = (prd.parent / target_path).resolve()
    assert target.is_relative_to(ROOT)
    criteria = target.read_text(encoding="utf-8")
    assert separator and fragment
    headings = re.findall(r"^#{1,6} (.+)$", criteria, flags=re.MULTILINE)
    slugs = [
        re.sub(r"[^\w\- ]", "", heading.lower()).strip().replace(" ", "-")
        for heading in headings
    ]
    assert fragment in slugs, "the linked acceptance section does not exist"
    for number in range(1, 7):
        assert re.search(rf"\| P-AC-0{number}\b", criteria), f"P-AC-0{number} missing"
    assert "미검증" in criteria
    assert "고객" in criteria and "수용" in criteria
