"""Focused boundary-gate regression for the masked lane.

Proves the R1 boundary fix keeps the exact production security semantics
without a replaceable validator:

- domain seams never import composition (checked by the R1 checker);
- the DSM capability seam requires the concrete domain-owned wiring with a
  direct ``isinstance`` (no public registration surface to overwrite);
- the mask source-context seam maps a blocked source to the same 409, with
  a single identical ``MaskSourceNotAdmitted`` class shared by the domain
  contract and the composition re-export.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.routing import APIRoute
from ksi_core.composition.masked_quantitative_graph import (
    MaskedQuantitativeWiring as GraphWiring,
)
from ksi_core.composition.masked_quantitative_graph import (
    MaskSourceNotAdmitted as GraphNotAdmitted,
)
from ksi_core.domains.external.ingress.external_mask_input_api import (
    MaskedLaneSourcePort,
    build_external_mask_input_router,
)
from ksi_core.domains.external.ingress.external_mask_input_bytes import (
    ExternalMaskInputByteStore,
)
from ksi_core.domains.external.ingress.external_mask_input_core_adapters import (
    MaskSourceNotAdmitted as DomainNotAdmitted,
)
from ksi_core.domains.external.ingress.external_mask_input_store import (
    ExternalMaskInputStore,
)
from ksi_core.domains.external.quantity import external_masked_input_capabilities as cap
from ksi_core.domains.external.quantity.external_masked_input_capabilities import (
    _require_concrete_wiring,
    build_external_masked_dsm_capability_router,
    resolve_masked_dsm_capabilities,
)
from ksi_core.domains.external.quantity.masked_quantitative_wiring import (
    MaskedQuantitativeWiring as DomainWiring,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind, Role
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_masked_api import MaskSourceContextViewV1


def _sealed_envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=8000000,
        max_streamed_bytes=8000000,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=1000000,
        max_bands=4,
        max_blocks=512,
        max_decompressed_bytes=20000000,
        max_sample_bytes=8000000,
        max_geometry_vertices=64,
        max_cpu_seconds=60.0,
        max_memory_bytes=100000000,
        max_workspace_bytes=100000000,
        max_output_bytes=1000000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=3600.0,
        lease_duration_seconds=600.0,
        max_retry_attempts=2,
    ).sealed()


def _operator() -> Principal:
    return Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")


def test_mask_source_exception_is_single_domain_class() -> None:
    assert DomainNotAdmitted is GraphNotAdmitted
    exc = DomainNotAdmitted("SOURCE_NOT_ADMITTED")
    assert exc.reason == "SOURCE_NOT_ADMITTED"
    assert str(exc) == "SOURCE_NOT_ADMITTED"
    assert isinstance(exc, RuntimeError)


def test_no_public_registration_surface_to_overwrite_gate() -> None:
    assert not hasattr(cap, "register_masked_wiring_checker")
    assert not hasattr(cap, "_MASKED_WIRING_CHECKER")
    with pytest.raises(AttributeError):
        cap.register_masked_wiring_checker(lambda _: True)  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="concrete MaskedQuantitativeWiring"):
        _require_concrete_wiring(object())


def test_concrete_gate_rejects_same_name_fake_and_accepts_real() -> None:
    class MaskedQuantitativeWiring:
        pass

    for bad in (None, object(), "wiring", 123, MaskedQuantitativeWiring()):
        with pytest.raises(ValueError, match="concrete MaskedQuantitativeWiring"):
            _require_concrete_wiring(bad)

    real_like = DomainWiring.__new__(DomainWiring)
    assert isinstance(real_like, DomainWiring)
    assert isinstance(real_like, GraphWiring)
    assert _require_concrete_wiring(real_like) is real_like


def _run_fresh(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    roots = (
        "services/core/src",
        "packages/event-contracts/src",
        "packages/domain/src",
        "packages/geo-core/src",
        "packages/geo-spatial/src",
        "packages/change-detection/src",
    )
    env["PYTHONPATH"] = os.pathsep.join(roots)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def test_real_wiring_accepted_in_both_import_orders() -> None:
    first_capabilities = dedent("""
        from ksi_core.domains.external.quantity import (
            external_masked_input_capabilities as emic,
        )
        from ksi_core.domains.external.quantity import (
            masked_quantitative_wiring as mqw,
        )
        from ksi_core.composition import masked_quantitative_graph as mg
        D = mqw.MaskedQuantitativeWiring
        C = mg.MaskedQuantitativeWiring
        assert D is C
        class MaskedQuantitativeWiring: pass
        try:
            emic._require_concrete_wiring(MaskedQuantitativeWiring())
            raise SystemExit("duck passed")
        except ValueError: pass
        real = D.__new__(D)
        assert emic._require_concrete_wiring(real) is real
        """)
    graph_first = dedent("""
        from ksi_core.composition import masked_quantitative_graph as mg
        from ksi_core.domains.external.quantity import (
            masked_quantitative_wiring as mqw,
        )
        from ksi_core.domains.external.quantity import (
            external_masked_input_capabilities as emic,
        )
        D = mqw.MaskedQuantitativeWiring
        C = mg.MaskedQuantitativeWiring
        assert D is C
        class MaskedQuantitativeWiring: pass
        try:
            emic._require_concrete_wiring(MaskedQuantitativeWiring())
            raise SystemExit("duck passed")
        except ValueError: pass
        real = D.__new__(D)
        assert emic._require_concrete_wiring(real) is real
        """)
    for script in (first_capabilities, graph_first):
        result = _run_fresh(script)
        assert result.returncode == 0, result.stdout + result.stderr


def test_capability_router_and_resolver_reject_fake_wiring() -> None:
    fake = object()
    with pytest.raises(ValueError, match="concrete MaskedQuantitativeWiring"):
        build_external_masked_dsm_capability_router(
            wiring=fake,  # type: ignore[arg-type]
            reconstruction=None,
            storage=None,
            designated_worker=_operator(),
        )
    with pytest.raises(ValueError, match="concrete MaskedQuantitativeWiring"):
        resolve_masked_dsm_capabilities(
            wiring=fake,  # type: ignore[arg-type]
            reconstruction=None,
            storage=None,
            request_id="req-1",
            worker_principal=_operator(),
            attempt=None,  # type: ignore[arg-type]
            now=datetime.now(UTC),
        )


def _minimal_source_router(
    tmp_path: Path, lane_source: MaskedLaneSourcePort
) -> tuple[APIRouter, DurableJournal]:
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    ingress = ExternalMaskInputStore.__new__(ExternalMaskInputStore)
    ingress._coordinator = coordinator  # noqa: SLF001
    byte_store = ExternalMaskInputByteStore.__new__(ExternalMaskInputByteStore)
    byte_store._coordinator = coordinator  # noqa: SLF001
    journal = DurableJournal(tmp_path / "inspection.jsonl")
    try:
        router = build_external_mask_input_router(
            ingress=ingress,
            byte_store=byte_store,
            inspection_journal=journal,
            resource_envelope=_sealed_envelope(),
            designated_worker=Principal(
                "masked-worker-1", PrincipalKind.ANALYSIS_WORKER, None, None, "org-a"
            ),
            lane_source=lane_source,
            clock=lambda: datetime.now(UTC),
        )
    except BaseException:
        journal.close()
        raise
    return router, journal


class _BlockedSource:
    def activation_current(self, *, now: datetime) -> bool:
        return True

    def resolve_source_context(self, **kwargs: Any) -> Any:
        raise DomainNotAdmitted("SOURCE_NOT_ADMITTED")


class _ActivationDownSource:
    def activation_current(self, *, now: datetime) -> bool:
        return True

    def resolve_source_context(self, **kwargs: Any) -> Any:
        raise GraphNotAdmitted("MASKED_ACTIVATION_UNAVAILABLE")


def _call_source_context(router: APIRouter, digest: str) -> MaskSourceContextViewV1:
    route = next(
        r
        for r in router.routes
        if isinstance(r, APIRoute)
        and r.path == "/v3/sites/{site_id}/work-areas/{work_area_id}/mask-source-context"
    )
    return route.endpoint(
        site_id="site-a",
        work_area_id="wa-1",
        source_calculation_identity_digest=digest,
        principal=_operator(),
    )


def test_blocked_source_maps_to_same_409(tmp_path: Path) -> None:
    digest = "sha256:" + "a" * 64
    for stub, detail in (
        (_BlockedSource(), "SOURCE_NOT_ADMITTED"),
        (_ActivationDownSource(), "MASKED_ACTIVATION_UNAVAILABLE"),
    ):
        router, journal = _minimal_source_router(tmp_path, stub)
        try:
            with pytest.raises(HTTPException) as exc_info:
                _call_source_context(router, digest)
        finally:
            journal.close()
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == detail
