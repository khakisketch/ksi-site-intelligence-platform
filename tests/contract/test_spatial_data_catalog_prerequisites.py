"""Bounded catalog prerequisites operate on real retained Core journals, not latest aliases."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_core.acquisition import observation_epoch_id
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from support.external_artifact_inspection_fixtures import NOW, sealed_submission


def _orders(path: Path) -> ObservationWorkOrderStore:
    return ObservationWorkOrderStore(
        DurableJournal(path),
        site_exists=lambda site, organization: (
            (site, organization) in {("site-1", "organization-1"), ("site-2", "organization-2")}
        ),
    )


def _create(store: ObservationWorkOrderStore, *, other: bool = False) -> Any:
    return store.create_work_order(
        organization_id="organization-2" if other else "organization-1",
        site_id="site-2" if other else "site-1",
        work_area_ids=["wa-1"],
        name="export",
        schedule_id=None,
        actor="operator-1",
        now=NOW,
    )


def _register(
    store: ExternalReconstructionStore, order: Any, *, revision: int = 1, submission_id: str = "one"
) -> Any:
    submission = (
        sealed_submission()
        .model_copy(
            update={
                "organization_id": order.organization_id,
                "site_id": order.site_id,
                "observation_epoch_id": observation_epoch_id(order),
                "submission_id": submission_id,
                "revision": revision,
                "submission_digest": None,
            }
        )
        .sealed()
    )
    result = store.register(submission, work_order=order, registered_by="operator-1", now=NOW)
    assert result.revision is not None, result
    return result.revision


@pytest.mark.parametrize("limit", [True, False, 0, -1, 1.0, "1", None])
def test_bounded_order_listing_rejects_coercion(tmp_path: Path, limit: object) -> None:
    """Coercion must not disable the source enumeration budget."""
    store = _orders(tmp_path / "orders.jsonl")
    method = getattr(store, "list_for_site_bounded", None)
    assert callable(method), "bounded WorkOrder enumeration missing"
    with pytest.raises(ValueError):
        method("site-1", organization_id="organization-1", max_records=limit)


def test_bounded_order_listing_is_scoped_detached_and_restart_safe(tmp_path: Path) -> None:
    """A global scan/budget, aliased model or absent replay index would break this read."""
    path = tmp_path / "orders.jsonl"
    store = _orders(path)
    first = _create(store)
    _create(store, other=True)
    method = getattr(store, "list_for_site_bounded", None)
    assert callable(method), "bounded WorkOrder enumeration missing"
    records = method("site-1", organization_id="organization-1", max_records=1)
    assert [item.work_order_id for item in records] == [first.work_order_id]
    object.__setattr__(records[0], "name", "forged")
    assert method("site-1", organization_id="organization-1", max_records=1)[0].name == "export"
    with pytest.raises(LookupError):
        method("site-1", organization_id="organization-2", max_records=1)
    store._journal.close()  # noqa: SLF001
    restarted = _orders(path)
    assert restarted.list_for_site_bounded(
        "site-1", organization_id="organization-1", max_records=1
    ) == [first]


def test_bounded_order_listing_refuses_overflow_and_retains_updated_order(tmp_path: Path) -> None:
    """Silently truncating source history or a stale index loses exact asset attribution."""
    store = _orders(tmp_path / "orders.jsonl")
    first = _create(store)
    method = getattr(store, "list_for_site_bounded", None)
    assert callable(method), "bounded WorkOrder enumeration missing"
    approved = store.approve(
        first.work_order_id,
        organization_id=first.organization_id,
        expected_version=first.version,
        actor="operator-1",
        now=NOW + timedelta(seconds=1),
    )
    assert method("site-1", organization_id="organization-1", max_records=1) == [approved]
    _create(store)
    from ksi_core.domains.sites.observation_work_orders import SiteWorkOrderListBudgetExceeded

    with pytest.raises(SiteWorkOrderListBudgetExceeded):
        method("site-1", organization_id="organization-1", max_records=1)


def test_bounded_reconstruction_listing_counts_all_history_and_replays(tmp_path: Path) -> None:
    """The index must retain superseded revisions and every submission, never choose latest."""
    orders = _orders(tmp_path / "orders.jsonl")
    order, other = _create(orders), _create(orders, other=True)
    path = tmp_path / "ingress.jsonl"
    store = ExternalReconstructionStore(DurableJournal(path))
    first = _register(store, order)
    second = _register(store, order, revision=2)
    _register(store, other)
    method = getattr(store, "list_bounded_for_work_order", None)
    assert callable(method), "bounded reconstruction enumeration missing"
    kwargs = dict(
        organization_id=order.organization_id,
        site_id=order.site_id,
        max_submissions=1,
        max_revisions=2,
    )
    records = method(order.work_order_id, **kwargs)
    assert records == (first, second)
    object.__setattr__(records[0].submission, "submission_id", "forged")
    assert method(order.work_order_id, **kwargs)[0].submission.submission_id == "one"
    assert method(order.work_order_id, **{**kwargs, "organization_id": "organization-2"}) == ()
    from ksi_core.domains.external.ingress.external_reconstruction import (
        ExternalReconstructionListBudgetExceeded,
    )

    with pytest.raises(ExternalReconstructionListBudgetExceeded):
        method(order.work_order_id, **{**kwargs, "max_revisions": 1})
    store._journal.close()  # noqa: SLF001
    restarted = ExternalReconstructionStore(DurableJournal(path))
    assert restarted.list_bounded_for_work_order(order.work_order_id, **kwargs) == (first, second)


@pytest.mark.parametrize("field", ["max_submissions", "max_revisions"])
@pytest.mark.parametrize("limit", [True, False, -1, 1.0, "1", None])
def test_bounded_reconstruction_rejects_coerced_limits(
    tmp_path: Path, field: str, limit: object
) -> None:
    """Representationally invalid budgets must never imply unlimited source enumeration."""
    store = ExternalReconstructionStore(DurableJournal(tmp_path / "ingress.jsonl"))
    method = getattr(store, "list_bounded_for_work_order", None)
    assert callable(method), "bounded reconstruction enumeration missing"
    kwargs = dict(
        organization_id="organization-1", site_id="site-1", max_submissions=1, max_revisions=1
    )
    kwargs[field] = limit
    with pytest.raises(ValueError):
        method("unknown", **kwargs)
