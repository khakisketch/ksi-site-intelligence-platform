"""Explicit all-or-none configuration; absence never manufactures authority."""

from pathlib import Path

import pytest
from ksi_core import production

_WORKFLOW = "KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"
_PROVIDER = "KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"


def test_absent_external_configuration_remains_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_WORKFLOW, raising=False)
    monkeypatch.delenv(_PROVIDER, raising=False)
    assert production._external_authority_paths_env() is None


@pytest.mark.parametrize("key", [_WORKFLOW, _PROVIDER])
def test_partial_external_configuration_fails_before_storage(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.delenv(_WORKFLOW, raising=False)
    monkeypatch.delenv(_PROVIDER, raising=False)
    monkeypatch.setenv(key, "/operator/supplied.json")
    with pytest.raises(RuntimeError, match="together"):
        production._external_authority_paths_env()


@pytest.mark.parametrize("value", ["", "relative.json", " /operator/file.json", "/a/../file"])
def test_invalid_explicit_external_path_is_not_treated_as_disabled(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(_WORKFLOW, value)
    monkeypatch.setenv(_PROVIDER, "/operator/provider.json")
    with pytest.raises(RuntimeError):
        production._external_authority_paths_env()


def test_exact_paths_are_retained_without_opening_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_WORKFLOW, "/operator/workflow.json")
    monkeypatch.setenv(_PROVIDER, "/operator/provider.json")
    assert production._external_authority_paths_env() == (
        Path("/operator/workflow.json"), Path("/operator/provider.json")
    )
