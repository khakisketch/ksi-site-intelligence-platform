"""Static guard for the owner-triggered civil live-processing workflow.

The workflow is intentionally separate from ordinary CI because it consumes
owner-approved image bytes.  This test makes a future YAML edit fail locally if
it turns into an ungated scheduled/push job, drops the immutable NodeODM image,
or loses its explicit skipped-gate behaviour.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

_WORKFLOW = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "civil-live-contracts.yml"
).read_text(encoding="utf-8")

_NODEODM_DIGEST = "sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2"
_MINIO_DIGEST = "sha256:a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e"


def test_civil_live_workflow_is_manual_gated_and_digest_pinned() -> None:
    assert "workflow_dispatch:" in _WORKFLOW
    assert "schedule:" not in _WORKFLOW
    assert "push:" not in _WORKFLOW
    assert "pull_request:" not in _WORKFLOW
    assert "LIVE_CONTRACTS_SKIPPED" in _WORKFLOW
    assert "if: needs.fixture-gate.outputs.ready == 'true'" in _WORKFLOW
    assert "secrets.KSI_CIVIL_LIVE_FIXTURE_URL" in _WORKFLOW
    assert "fixture_archive_url:" not in _WORKFLOW
    assert _NODEODM_DIGEST in _WORKFLOW
    assert _MINIO_DIGEST in _WORKFLOW
    assert (
        "test_completed_reconstruction_artifacts_persist_and_redownload_with_matching_digest"
        in _WORKFLOW
    )


def test_civil_live_workflow_keeps_raw_fixture_bytes_outside_git() -> None:
    assert "fixture_archive_sha256" in _WORKFLOW
    assert "sha256sum" in _WORKFLOW
    assert "UNSAFE_LIVE_FIXTURE_MEMBER_TYPE" in _WORKFLOW
    assert "LIVE_FIXTURE_TOO_MANY_MEMBERS" in _WORKFLOW
    assert "LIVE_FIXTURE_UNCOMPRESSED_SIZE_EXCEEDED" in _WORKFLOW
    assert "UNSAFE_LIVE_FIXTURE_MEMBER_SIZE" in _WORKFLOW
    assert "uv run --locked python" in _WORKFLOW
    assert "normalized in seen" in _WORKFLOW
    assert "member.issym() or member.islnk()" in _WORKFLOW
    assert "source.extractall(target, members=members, filter=\"data\")" in _WORKFLOW
    assert "rm -rf \"$RUNNER_TEMP/ksi-civil-live-fixture\"" in _WORKFLOW


def test_civil_live_workflow_yaml_and_shell_blocks_parse() -> None:
    """Keep an untested manual workflow from becoming invalid YAML or shell."""
    workflow = yaml.safe_load(_WORKFLOW)
    assert isinstance(workflow, dict)
    jobs = workflow["jobs"]
    assert "fixture-gate" in jobs
    assert "live-contracts" in jobs
    for job in jobs.values():
        for step in job.get("steps", []):
            if "run" in step:
                result = subprocess.run(
                    ["bash", "-n"], input=step["run"], text=True, capture_output=True, check=False
                )
                assert result.returncode == 0, (step.get("name"), result.stderr)
