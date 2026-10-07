"""Neutral observation-epoch identity (deterministic, journal-free).

Canonical owner of :func:`observation_epoch_id`, moved byte-identically from
``ksi_core.acquisition.analysis_readiness``. The recipe is unchanged:
``obs-epoch-`` plus the first 24 hex characters of the SHA256 over the UTF-8
bytes of ``organization_id + NUL + work_order_id + NUL + cycle_number``.

This module introduces no epoch journal and imports neither mission nor
acquisition code — external ingress and readiness both derive the same
immutable identity from the authoritative WorkOrder snapshot.
"""

from __future__ import annotations

import hashlib

from ksi_event_contracts.observation_work_order import ObservationWorkOrder


def observation_epoch_id(work_order: ObservationWorkOrder) -> str:
    """A deterministic v1 epoch identity; no mutable Epoch journal is introduced."""

    raw = (
        f"{work_order.organization_id}\0{work_order.work_order_id}\0{work_order.cycle_number}"
    ).encode()
    return f"obs-epoch-{hashlib.sha256(raw).hexdigest()[:24]}"


__all__ = ["observation_epoch_id"]
