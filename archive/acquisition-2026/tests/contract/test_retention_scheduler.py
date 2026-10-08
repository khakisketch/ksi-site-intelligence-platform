"""보관 정책 주기 실행 진입점 계약 (tools/retention_scheduler.py, ADR-KSI-010 §3).

세 가지를 반증한다:

1. **주기 실행 진입점이 실제로 반복 동작한다** — ``--iterations N`` 이 정확히 N 번
   주기를 돌고, 매 회 journal 을 새로 열어 그 사이의 새 이벤트도 본다(green≠작동
   — 한 번만 열고 캐시된 스냅샷을 계속 재사용하면 두 번째 주기부터 죽은 뷰다).
2. **집행(삭제)을 스스로 하지 않는다** — 소스 텍스트에 ``execute_expiry``·
   ``S3EvidenceStorage``·``.delete(`` 참조가 전혀 없다(ADR-KSI-010 §3 이 금지하는
   자동 집행 경로 자체가 이 파일에 물리적으로 존재하지 않음을 고정한다).
3. **CLI 검증이 fail-closed** — 잘못된 인자는 조용히 통과하지 않는다.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.events import EventStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEDULER_PATH = _REPO_ROOT / "tools" / "retention_scheduler.py"
_SCHEDULER_SOURCE = _SCHEDULER_PATH.read_text(encoding="utf-8")
_SCHEMA_DEFAULTS = _REPO_ROOT / "contracts" / "schemas" / "retention-policy.v1.json"


def _imported_names(source: str) -> set[str]:
    """모듈이 실제로 import 하는 이름 — 산문(docstring)에서 이름을 언급하는 것과
    실제로 그 이름을 끌어와 부르는 것을 구분하기 위해 AST 로만 본다."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.update(alias.name for alias in node.names)
    return names

import sys  # noqa: E402 -- 아래 sys.path 조작 전용, 표준 import 블록과 분리

sys.path.insert(0, str(_REPO_ROOT / "tools"))
import retention_scheduler  # noqa: E402


def _write_policy(path: Path, *, candidate_days: int = 30) -> Path:
    schema = json.loads(_SCHEMA_DEFAULTS.read_text(encoding="utf-8"))
    payload = {
        key: spec["default"] for key, spec in schema["properties"].items() if "default" in spec
    }
    payload["candidateDays"] = candidate_days
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _bundle(event_id: str, *, occurred_at: str) -> dict[str, Any]:
    return {
        "schemaVersion": "1.2",
        "eventId": event_id,
        "siteId": "site-1",
        "missionId": "mission-1",
        "eventType": "PERSON_PRESENT",
        "status": "CANDIDATE",
        "occurredAt": occurred_at,
        "entities": ["ent-trk-001"],
        "spatialContext": {"zone": "A"},
        "reasoning": {},
        "evidence": {},
        "lineage": {
            "edgeVersion": "scheduler-test-edge-1.0",
            "modelVersions": {"detector": "stub"},
            "policyVersion": "scheduler-test-policy-1",
            "calibrationProfileId": "scheduler-test-cal-1",
            "classification": {
                "ent-trk-001": {
                    "entityClass": "Person",
                    "ontologyVersion": "ksi-ontology-v1",
                    "source": {
                        "taxonomy": "COCO-2017",
                        "sourceClassIds": [0],
                        "sourceClassNames": ["person"],
                    },
                    "entityFingerprint": "a" * 64,
                }
            },
        },
    }


def _seed_candidate(store: EventStore, *, event_id: str, received_at: datetime) -> None:
    store.project_bundle(
        _bundle(event_id, occurred_at=received_at.isoformat()),
        edge_device_id="dev-1",
        received_at=received_at,
    )
    store.register_evidence(
        event_key=f"dev-1::{event_id}",
        artifact_id="clip-01",
        content_type="video/mp4",
        registered_by="op-admin",
        now=received_at,
    )


# ── 1. 소스 자체에 자동 집행 경로가 없다 ─────────────────────────────────────


def test_scheduler_never_imports_execute_expiry() -> None:
    """[핵심] ADR-KSI-010 §3 이 금지하는 자동 집행이 이 파일에 물리적으로 없다.

    모듈 docstring 은 산문으로 ``execute_expiry`` 를 **언급**한다(이 스크립트가
    그걸 안 부른다는 설명 그 자체) — 그건 import 가 아니다. 여기서 거부하는
    것은 실제 import 문뿐이다(AST 기반, docstring 문자열과 혼동하지 않는다).
    """
    imported = _imported_names(_SCHEDULER_SOURCE)
    assert "execute_expiry" not in imported
    assert "S3EvidenceStorage" not in imported
    assert not any(name.startswith("ksi_core.evidence_s3") for name in imported)


def test_scheduler_module_exposes_no_execute_expiry_name() -> None:
    """소스 텍스트 검사의 보강 — 실제 로드된 모듈 네임스페이스에도 없다."""
    assert not hasattr(retention_scheduler, "execute_expiry")


# ── 2. CLI 검증 fail-closed ──────────────────────────────────────────────────


def test_negative_interval_seconds_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy_path = _write_policy(tmp_path / "policy.json")
    with pytest.raises(SystemExit) as excinfo:
        retention_scheduler.main(
            [
                "--data-dir",
                str(tmp_path),
                "--policy",
                str(policy_path),
                "--interval-seconds",
                "-1",
            ]
        )
    assert excinfo.value.code == 2
    assert "--interval-seconds" in capsys.readouterr().err


def test_zero_or_negative_iterations_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy_path = _write_policy(tmp_path / "policy.json")
    with pytest.raises(SystemExit) as excinfo:
        retention_scheduler.main(
            [
                "--data-dir",
                str(tmp_path),
                "--policy",
                str(policy_path),
                "--iterations",
                "0",
            ]
        )
    assert excinfo.value.code == 2
    assert "--iterations" in capsys.readouterr().err


def test_missing_journal_is_skipped_not_crashed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """이벤트 원장이 아직 없는 새 배포에서도 죽지 않고 다음 주기를 기다린다."""
    policy_path = _write_policy(tmp_path / "policy.json")
    code = retention_scheduler.main(
        [
            "--data-dir",
            str(tmp_path),
            "--policy",
            str(policy_path),
            "--iterations",
            "1",
            "--interval-seconds",
            "0",
        ]
    )
    assert code == 0
    assert "이벤트 원장이 없다" in capsys.readouterr().err


# ── 3. 주기 실행이 실제로 반복되고, 매회 새로 읽는다 ────────────────────────


def test_iterations_runs_exactly_n_scans(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy_path = _write_policy(tmp_path / "policy.json")
    journal = DurableJournal(tmp_path / "events.jsonl")
    store = EventStore(journal)
    # DurableJournal 은 append() 전까지 파일을 실제로 만들지 않는다 — 최소
    # 1건을 써야 events.jsonl 이 물리적으로 존재해 스캔 대상이 된다(만료
    # 대상은 아닌 방금 시각으로 심어 "만료 없음" 정상 스캔과 "원장 자체가
    # 없음" 스킵을 구분한다).
    _seed_candidate(store, event_id="evt-fresh", received_at=datetime.now(UTC))

    code = retention_scheduler.main(
        [
            "--data-dir",
            str(tmp_path),
            "--policy",
            str(policy_path),
            "--iterations",
            "3",
            "--interval-seconds",
            "0",
        ]
    )
    assert code == 0
    err = capsys.readouterr().err
    scan_lines = [
        json.loads(line) for line in err.splitlines() if '"retention scan' in line
    ]
    assert len(scan_lines) == 3


def test_rescans_pick_up_events_written_between_iterations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """[핵심] journal 을 매회 새로 여는 설계가 실제로 동작한다 — 첫 주기에서는
    안 보이던(아직 안 쓰인) 만료 대상이 두 번째 주기에서 보인다. 인스턴스를
    재사용해 시작 시점 스냅샷을 계속 돌려썼다면 이 테스트는 실패한다."""
    policy_path = _write_policy(tmp_path / "policy.json", candidate_days=30)
    journal = DurableJournal(tmp_path / "events.jsonl")
    store = EventStore(journal)

    now = datetime.now(UTC)
    old_enough_to_expire = now - timedelta(days=40)
    # 첫 주기가 "원장 없음" 스킵이 아니라 실제 0건 스캔이 되도록 만료 대상이
    # 아닌 이벤트를 미리 심어 파일을 존재하게 만든다.
    _seed_candidate(store, event_id="evt-fresh", received_at=now)

    calls = 0
    real_scan_once = retention_scheduler._scan_once

    def _spy_scan_once(*, data_dir: Path, policy: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            # 두 번째 주기 직전에 새 이벤트를 써 넣는다 — 스케줄러가 journal 을
            # 매회 새로 열어야만 이번 주기 스캔에 반영된다.
            _seed_candidate(store, event_id="evt-late", received_at=old_enough_to_expire)
        real_scan_once(data_dir=data_dir, policy=policy)

    retention_scheduler._scan_once = _spy_scan_once
    try:
        code = retention_scheduler.main(
            [
                "--data-dir",
                str(tmp_path),
                "--policy",
                str(policy_path),
                "--iterations",
                "2",
                "--interval-seconds",
                "0",
            ]
        )
    finally:
        retention_scheduler._scan_once = real_scan_once

    assert code == 0
    err = capsys.readouterr().err
    scan_lines = [
        json.loads(line) for line in err.splitlines() if '"retention scan' in line
    ]
    assert len(scan_lines) == 2
    assert "0건" in scan_lines[0]["message"]
    assert "1건" in scan_lines[1]["message"]


def test_scan_reports_enforced_fields_in_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy_path = _write_policy(tmp_path / "policy.json")
    journal = DurableJournal(tmp_path / "events.jsonl")
    store = EventStore(journal)
    _seed_candidate(store, event_id="evt-fresh", received_at=datetime.now(UTC))

    retention_scheduler.main(
        [
            "--data-dir",
            str(tmp_path),
            "--policy",
            str(policy_path),
            "--iterations",
            "1",
            "--interval-seconds",
            "0",
        ]
    )
    err = capsys.readouterr().err
    scan_line = next(json.loads(line) for line in err.splitlines() if '"retention scan' in line)
    assert "candidateDays" in scan_line["message"]
    assert "confirmedEventDays" in scan_line["message"]
