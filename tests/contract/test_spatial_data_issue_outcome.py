"""Atomic issuance outcome for HTTP 201/200, not pre-query race heuristics."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from ksi_event_contracts.spatial_data import (
    SpatialDataJobViewV1,
    SpatialDataPurposeV1,
    SpatialDataRequestV1,
)
from spatial_data_job_fixture import NOW, job_graph, job_store


def test_issue_outcome_marks_exactly_one_concurrent_creator(tmp_path: Path) -> None:
    """A router cannot derive 201/200 reliably from before/after list or timestamp checks."""
    graph = job_graph(tmp_path)
    store = job_store(graph)
    request = SpatialDataRequestV1(
        asset_ref=graph.source.asset_ref,
        requested_bounds=(0, 0, 1, 1),
        observed_crs_digest=graph.source.inspection.measurements.observed_crs_digest,
        resolution_mode="NATIVE",
        purpose=SpatialDataPurposeV1.GENERAL_DATA_USE,
    )
    method = getattr(store, "issue_with_outcome", None)
    assert callable(method), "atomic creator outcome missing from durable issuance"
    barrier = Barrier(2)

    def create() -> tuple[SpatialDataJobViewV1, bool]:
        barrier.wait()
        return method(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            request=request,
            principal=graph.principal,
            idempotency_key="same",
            now=NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert len({view.job_id for view, created in results}) == 1
    assert sorted(created for _, created in results) == [False, True]
    store._journal.close()  # noqa: SLF001 -- true writer shutdown before replay
    restarted = job_store(graph)
    view, created = restarted.issue_with_outcome(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        request=request,
        principal=graph.principal,
        idempotency_key="same",
        now=NOW,
    )
    assert created is False and view.job_id == results[0][0].job_id
