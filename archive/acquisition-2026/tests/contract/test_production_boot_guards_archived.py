"""Archived legacy-boot guard (P3 Task 5 relocation record, RB-08).

Relocated verbatim from
``tests/contract/test_external_runtime_deployment_contract.py::
test_production_config_mount_cannot_create_quantitative_authority``: it boots
the legacy managed factory (``ksi_core.production.build_production_app``,
retired to ``archive/acquisition-2026/``) to prove partial authority
configuration fails closed. The platform factory carries the same all-or-none
pair guard, proven actively by
``tests/contract/test_platform_core_production.py`` (expired-activation and
missing-env cases). This file is archive-internal (``archive/`` is not a
pytest testpath, import path, or workspace member) and is NOT executed.
"""


def test_production_config_mount_cannot_create_quantitative_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Partial authority configuration rejects startup before opening journals."""
    from ksi_core.production import build_production_app
    from test_production_assembly import _apply_env, _valid_env

    _apply_env(monkeypatch, _valid_env(tmp_path))
    monkeypatch.setenv(
        "KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG",
        str(tmp_path / "mounted-but-untrusted-workflow.json"),
    )

    monkeypatch.delenv("KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG", raising=False)
    assert not list(tmp_path.rglob("*.jsonl"))
    with pytest.raises(RuntimeError, match="must be configured together"):
        build_production_app()
    assert not list(tmp_path.rglob("*.jsonl"))