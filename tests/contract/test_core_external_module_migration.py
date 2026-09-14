"""Core R1 T3 external-domain relocation contracts.

Fresh interpreters ensure a legacy import cannot pass merely because an earlier
canonical import populated ``sys.modules``.  These tests catch copied wrappers
that would split the authority provider's mutable lifecycle seams.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORE_SOURCE_ROOT = REPOSITORY_ROOT / "services/core/src"

EXTERNAL_MODULES = {
    "ingress": (
        "external_reconstruction",
        "external_evidence",
        "external_validation_policy",
        "external_artifact_inspections",
        "external_display_artifacts",
        "external_evidence_validations",
    ),
    "quantity": (
        "external_use_decisions",
        "external_use_evaluator",
        "external_quantitative_authority",
        "external_relative_volume_authorities",
        "external_relative_volume_launch_material",
        "external_relative_volume_s3_capabilities",
        "external_relative_volume_use_history",
        "external_relative_volumes",
    ),
    "workflow": (
        "external_reobservation_proposals",
        "external_result_projection_models",
        "external_result_review_sources",
        "external_result_reviews",
        "external_result_workflow_api",
    ),
    "authority": (
        "external_authority_operations",
        "external_authority_preflight",
        "external_authority_provider",
        "external_result_workflow_assembly",
        "external_result_workflow_config",
    ),
}
EXTERNAL_ALIASES = tuple(
    (
        f"ksi_core.{module_name}",
        f"ksi_core.domains.external.{subgroup}.{module_name}",
    )
    for subgroup, module_names in EXTERNAL_MODULES.items()
    for module_name in module_names
)


def _canonical_file(module_name: str) -> Path:
    return CORE_SOURCE_ROOT / Path(*module_name.split(".")).with_suffix(".py")


def _run_python(script: str) -> None:
    environment = os.environ.copy()
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(CORE_SOURCE_ROOT), existing_python_path) if part
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("legacy, canonical", EXTERNAL_ALIASES)
@pytest.mark.parametrize("import_order", ("canonical-first", "legacy-first"))
def test_external_legacy_and_canonical_imports_share_one_module_object(
    legacy: str, canonical: str, import_order: str
) -> None:
    """A copied module would split external authority state and is a bug."""
    first, second = (
        (canonical, legacy) if import_order == "canonical-first" else (legacy, canonical)
    )
    expected_path = str(_canonical_file(canonical))
    _run_python(
        dedent(
            f"""
            import importlib
            import sys
            from pathlib import Path

            importlib.import_module({first!r})
            importlib.import_module({second!r})
            legacy = importlib.import_module({legacy!r})
            canonical = importlib.import_module({canonical!r})
            assert legacy is canonical
            assert sys.modules[{legacy!r}] is canonical
            assert sys.modules[{canonical!r}] is canonical
            assert Path(canonical.__file__).resolve() == Path({expected_path!r}).resolve()
            """
        )
    )


def test_provider_alias_keeps_the_loader_monkeypatch_seam_on_the_lifecycle_module() -> None:
    """A relocated loader seam must remain patchable by existing race tests."""
    expected_provider = str(
        _canonical_file("ksi_core.domains.external.authority.external_authority_provider")
    )
    _run_python(
        dedent(
            f"""
            import importlib
            from pathlib import Path

            legacy = importlib.import_module("ksi_core.external_authority_provider")
            canonical = importlib.import_module(
                "ksi_core.domains.external.authority.external_authority_provider"
            )
            assert legacy is canonical
            assert canonical._load.__module__ == canonical.__name__
            assert Path(canonical.__file__).resolve() == Path({expected_provider!r}).resolve()
            """
        )
    )


def test_external_alias_keeps_legacy_pickle_lookup_without_mutating_class_metadata() -> None:
    """Old pickle globals must resolve through the alias, not rewritten metadata."""
    _run_python(
        dedent(
            """
            import importlib
            import pickle

            legacy = importlib.import_module("ksi_core.external_validation_policy")
            canonical = importlib.import_module(
                "ksi_core.domains.external.ingress.external_validation_policy"
            )
            assert legacy is canonical
            assert legacy.PolicyReceipt is canonical.PolicyReceipt

            receipt = canonical.PolicyReceipt(
                policy_id="policy-a",
                version=1,
                policy_digest="sha256:" + "a" * 64,
                status=canonical.PolicyReceiptStatus.ADMITTED,
            )
            original_module = canonical.PolicyReceipt.__module__
            assert original_module == canonical.__name__
            canonical.PolicyReceipt.__module__ = "ksi_core.external_validation_policy"
            try:
                historical_payload = pickle.dumps(receipt)
            finally:
                canonical.PolicyReceipt.__module__ = original_module
            restored = pickle.loads(historical_payload)
            assert type(restored) is canonical.PolicyReceipt
            assert restored == receipt
            """
        )
    )


def test_external_alias_inventory_is_complete() -> None:
    """The approved T3 map has exactly 24 externally relocated public modules."""
    assert len(EXTERNAL_ALIASES) == 24
    assert len({legacy for legacy, _ in EXTERNAL_ALIASES}) == 24
    assert len({canonical for _, canonical in EXTERNAL_ALIASES}) == 24
