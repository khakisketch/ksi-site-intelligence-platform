"""Publish a standalone Analysis worker model bundle, or check without writing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from ksi_event_contracts import external_analysis_worker
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema


def schema_content() -> str:
    models: list[tuple[type[BaseModel], Literal["validation"]]] = [
        (model, "validation")
        for name in external_analysis_worker.__all__
        if isinstance(model := getattr(external_analysis_worker, name), type)
        and issubclass(model, BaseModel)
    ]
    _, bundle = models_json_schema(models, by_alias=True, ref_template="#/$defs/{model}")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ksi.example/contracts/external-analysis-worker.v1.json",
        "title": "External Analysis Worker API V1",
        "type": "object",
        "additionalProperties": False,
        **bundle,
    }
    return json.dumps(schema, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = (
        Path(__file__).resolve().parents[1] / "contracts/schemas/external-analysis-worker.v1.json"
    )
    content = schema_content()
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            print("Analysis worker schema is out of sync")
            return 1
    else:
        path.write_text(content, encoding="utf-8")
    print("Analysis worker schema is synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
