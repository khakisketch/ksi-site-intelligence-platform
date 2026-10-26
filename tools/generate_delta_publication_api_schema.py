"""Regenerate the additive delta API schema from its closed Python contracts."""

from __future__ import annotations

import json
from pathlib import Path

from ksi_event_contracts.external_delta_publication_api import (
    CreateDeltaPublicationV1,
    DeltaOutputObservationWireV1,
    DeltaPublicationBytesV1,
    DeltaPublicationIntentViewV1,
    DeltaPublicationPendingJobsV1,
    DeltaPublicationViewV1,
)
from pydantic import TypeAdapter


def schema() -> dict:
    result = TypeAdapter(
        CreateDeltaPublicationV1
        | DeltaOutputObservationWireV1
        | DeltaPublicationIntentViewV1
        | DeltaPublicationViewV1
        | DeltaPublicationPendingJobsV1
        | DeltaPublicationBytesV1,
    ).json_schema(by_alias=True)
    result["oneOf"] = result.pop("anyOf")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ksi.example/contracts/external-delta-publication-api.v1.json",
        **result,
    }


if __name__ == "__main__":
    destination = (
        Path(__file__).resolve().parents[1]
        / "contracts/schemas/external-delta-publication-api.v1.json"
    )
    destination.write_text(json.dumps(schema(), indent=2) + "\n", encoding="utf-8")
