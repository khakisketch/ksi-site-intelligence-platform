"""The adopted catalog identity remains metadata-only and scopes real Core records."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_domain.canonical_json import canonical_json_bytes
from test_spatial_data_catalog_prerequisites import _create, _orders, _register


def test_catalog_preserves_identity_preimage_and_metadata_only_contract(tmp_path: Path) -> None:
    """A new asset identity or metadata-to-byte permission upgrade would break external reuse."""
    from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog

    orders = _orders(tmp_path / "orders.jsonl")
    order = _create(orders)
    store = ExternalReconstructionStore(DurableJournal(tmp_path / "ingress.jsonl"))
    first = _register(store, order)
    _register(store, order, revision=2)
    principal = Principal(
        principal_id="operator-1",
        organization_id=order.organization_id,
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
    )
    # Only Site/area reads are minimal here; T2 source tests use full genuine Site/WorkArea stores.
    catalog = SpatialAssetCatalog(
        reconstruction=store,
        work_orders=orders,
        sites=SimpleNamespace(get_scoped=lambda site, organization: object()),
        work_areas=SimpleNamespace(get=lambda area: SimpleNamespace(site_id="site-1")),
        inspections=None,
    )
    items = catalog.items("site-1", "wa-1", principal)
    assert len(items) == 2
    item = next(item for item in items if item.revision == 1)
    identity = {
        "version": "spatial-asset-ref.v1",
        "submissionRef": item.submission_ref,
        "revision": 1,
        "artifactId": "ortho",
    }
    assert item.asset_ref == "ksa-v1-" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    assert item.work_order_id == first.work_order_id
    assert item.lifecycle_state == "SUPERSEDED"
    assert item.data_access == "NOT_AVAILABLE_FROM_CATALOG"
    assert item.supported_actions == ("VIEW_METADATA",)
