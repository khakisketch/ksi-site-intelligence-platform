"""Generate additive spatial-data schemas, or check them without writing."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Literal

from ksi_event_contracts._spatial_data import SpatialDataModel
from pydantic.json_schema import models_json_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    modules = ["spatial_data", "spatial_data_authority", "spatial_data_worker"]
    failures = []
    for name in modules:
        module = importlib.import_module(f"ksi_event_contracts.{name}")
        models: list[tuple[type[SpatialDataModel], Literal["validation"]]] = [
            (model, "validation")
            for model in vars(module).values()
            if isinstance(model, type)
            and issubclass(model, SpatialDataModel)
            and model.__module__ == module.__name__
            and not model.__name__.startswith("_")
        ]
        _, schema = models_json_schema(models, by_alias=True)
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        path = root / f"contracts/schemas/{name.replace('_', '-')}.v1.json"
        content = json.dumps(schema, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                failures.append(path.name)
        else:
            path.write_text(content, encoding="utf-8")
    if failures:
        print("Out of sync: " + ", ".join(failures))
        return 1
    print("Spatial-data schemas are synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
