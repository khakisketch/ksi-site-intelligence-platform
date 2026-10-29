"""Regenerate additive task DTOs without changing existing Analysis contracts."""

import json
from pathlib import Path

from ksi_event_contracts.external_spatial_task import (
    CreateSpatialTaskV1,
    RunSpatialTaskV1,
    SelectSpatialTaskV1,
    SpatialTaskOptionsV1,
    SpatialTaskSitesV1,
    SpatialTaskViewV1,
)
from pydantic import TypeAdapter


def schema() -> dict:
    result = TypeAdapter(
        CreateSpatialTaskV1
        | SelectSpatialTaskV1
        | RunSpatialTaskV1
        | SpatialTaskViewV1
        | SpatialTaskOptionsV1
        | SpatialTaskSitesV1
    ).json_schema(by_alias=True)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ksi.example/contracts/external-spatial-task.v1.json",
        **result,
    }


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "contracts/schemas/external-spatial-task.v1.json"
    target.write_text(json.dumps(schema(), indent=2) + "\n", encoding="utf-8")
