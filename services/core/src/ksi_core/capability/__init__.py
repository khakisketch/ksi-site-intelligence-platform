"""Capability Registry (P0-5) — 장비 기능 검증 상태의 Core 소유 레지스트리."""

from ksi_core.capability.registry import (
    CapabilityRecord,
    CapabilityRegistry,
    seed_prd_spikes,
)

__all__ = ["CapabilityRecord", "CapabilityRegistry", "seed_prd_spikes"]
