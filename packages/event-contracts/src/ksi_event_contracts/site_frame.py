"""Neutral Site spatial frame contract (INV-020).

Canonical owner of :class:`SiteFrame`, moved mechanically from
``ksi_mission_contracts.models`` with identical fields, aliases, config and
validation. Every world coordinate carries CRS, vertical datum, unit and
transform version. This module imports neither mission nor acquisition code.

The camelCase base is deliberately self-contained here instead of reusing the
event-contracts shared base: the legacy model was configured with exactly
``alias_generator=to_camel``, ``populate_by_name=True`` and ``extra="forbid"``
(and no ``allow_inf_nan`` key), and that full config is preserved key for key.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    """camelCase alias·extra forbid 공통 베이스 (SiteFrame 중립 소유자 전용)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class SiteFrame(_CamelModel):
    """INV-020 — 모든 세계좌표는 CRS·수직기준·unit·transformVersion을 갖는다."""

    crs: str
    vertical_datum: str
    unit: Literal["meter"]
    transform_version: str


__all__ = ["SiteFrame"]
