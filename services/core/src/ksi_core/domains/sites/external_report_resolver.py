"""Composite historical-report resolver dispatching by report-ref family.

``WorkInboxStore`` shares one external report family (RELATIVE_VOLUME) with
teammates through ``report_resolver``.  SV-3b adds a second external-volume
family, SINGLE_VOLUME.  A single-volume report ref always carries
``external-single-volume-report-`` as its identity prefix (see
``ExternalSingleVolumeStore``'s ``_KIND_PREFIX``); every other ref belongs to
the relative-volume family.  This resolver dispatches on that prefix so
``WorkInboxStore`` keeps reading exactly one ``_HistoricalReportResolver``
regardless of how many external-volume families are configured.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

#: Identity prefix minted by ``ExternalSingleVolumeStore`` for every report it
#: retains (``ExternalVolumeLedger._KIND_PREFIX + "-report-" + <hash>``).
SINGLE_VOLUME_REPORT_REF_PREFIX = "external-single-volume-report-"


@runtime_checkable
class HistoricalReportResolver(Protocol):
    def resolve_historical_report_ref(
        self, report_ref: str, *, organization_id: str, now: datetime | None = None
    ) -> Any | None: ...


class ExternalVolumeReportResolver:
    """Dispatches ``resolve_historical_report_ref`` to the family that owns ``report_ref``.

    A ref starting with :data:`SINGLE_VOLUME_REPORT_REF_PREFIX` resolves
    through ``single`` only when ``single`` is configured; every other ref,
    and every ref when ``single`` is ``None``, resolves through ``relative``.
    That last case is exactly today's behavior: a resolver built with no
    ``single`` argument never recognizes a single-volume ref, the same as the
    relative-only resolver it replaces.
    """

    def __init__(
        self,
        *,
        relative: HistoricalReportResolver | None,
        single: HistoricalReportResolver | None = None,
    ) -> None:
        self._relative = relative
        self._single = single

    def uses(self, relative: object, single: object) -> bool:
        """Prove this resolver wraps exactly these two dependencies."""

        return self._relative is relative and self._single is single

    def resolve_historical_report_ref(
        self, report_ref: str, *, organization_id: str, now: datetime | None = None
    ) -> Any | None:
        if report_ref.startswith(SINGLE_VOLUME_REPORT_REF_PREFIX) and self._single is not None:
            return self._single.resolve_historical_report_ref(
                report_ref, organization_id=organization_id, now=now
            )
        if self._relative is None:
            return None
        return self._relative.resolve_historical_report_ref(
            report_ref, organization_id=organization_id, now=now
        )
