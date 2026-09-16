"""Loader for the external-use blocker catalog.

Source: ``contracts/catalogs/external-use-blockers.v1.json``.

The catalog explains every reason and remediation code a pair/single use
decision can carry. Core proves coverage in a contract test; the Dashboard
renders a byte-identical generated copy (``tools/sync_external_use_blockers.py``).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CATALOG_PATH = (
    Path(__file__).resolve().parents[7] / "contracts" / "catalogs" / "external-use-blockers.v1.json"
)

Owner = Literal["OPERATOR", "ADMIN", "CUSTOMER"]
Target = Literal[
    "SUBJECT", "INSPECTION", "DISPLAY", "POLICY", "EVIDENCE", "MAPPING", "ZONE", "HEIGHT", "GENERAL"
]


class BlockerReason(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=500)
    owner: Owner
    target: Target


class BlockerRemediation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step: str = Field(min_length=1, max_length=300)
    owner: Owner
    target: Target


class ExternalUseBlockerCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    contract_version: Literal["external-use-blockers.v1"] = Field(alias="contractVersion")
    reasons: dict[str, BlockerReason]
    remediations: dict[str, BlockerRemediation]


@lru_cache(maxsize=1)
def load_external_use_blocker_catalog() -> ExternalUseBlockerCatalog:
    return ExternalUseBlockerCatalog.model_validate(json.loads(CATALOG_PATH.read_text("utf-8")))


__all__ = [
    "CATALOG_PATH",
    "BlockerReason",
    "BlockerRemediation",
    "ExternalUseBlockerCatalog",
    "load_external_use_blocker_catalog",
]
