"""Default platform graph and unchanged service/state boundaries, without live env."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]


class _TemplateLoader(yaml.SafeLoader):
    pass


def _reset_sequence(loader: yaml.SafeLoader, node: yaml.SequenceNode) -> list[Any]:
    return loader.construct_sequence(node, deep=True)


_TemplateLoader.add_constructor("!reset", _reset_sequence)


def _load_template(path: Path) -> dict[str, Any]:
    value = yaml.load(path.read_text(encoding="utf-8"), Loader=_TemplateLoader)
    assert isinstance(value, dict)
    return value


def test_default_and_vm_services_are_platform_only() -> None:
    """A default or overlay reconstruction service would reintroduce acquisition."""
    base = _load_template(_ROOT / "deploy/compose.yaml")
    vm = _load_template(_ROOT / "deploy/compose.vm.yaml")
    assert set(base["services"]) == {"init-volumes", "core", "minio"}
    assert set(vm["services"]) == {"core", "minio", "dashboard", "caddy"}
    assert set(base["services"]) | set(vm["services"]) == {
        "init-volumes", "core", "minio", "dashboard", "caddy"
    }


def test_removed_service_preserves_named_volume_identity() -> None:
    """Removing/renaming historical volumes or remounting ODM data loses isolation."""
    base = _load_template(_ROOT / "deploy/compose.yaml")
    vm = _load_template(_ROOT / "deploy/compose.vm.yaml")
    assert base["name"] == "ksi"
    assert base["volumes"] == {"ksi-data": None, "ksi-objects": None, "ksi-odm": None}
    assert vm["volumes"] == {"caddy-data": None, "caddy-config": None}
    for template in (base, vm):
        for service in template["services"].values():
            assert all(not mount.startswith("ksi-odm:") for mount in service.get("volumes", []))


@pytest.mark.parametrize(
    ("template", "service", "expected"),
    [
        (
            "compose.yaml", "init-volumes",
            "a3b6a71b7be633785a3dd23f17c1fd16ec8c5a6d68e81ffcf18577fffaf26e3a",
        ),
        (
            "compose.yaml", "core",
            "ec0264cd4641d3cf8d4fd5db5a6c8a51d4b2cf4867c6a77ea4841cc55eb89445",
        ),
        (
            "compose.yaml", "minio",
            "c6f7d274c722357dc3347d793feaaf5942268cd6da40f2f4e4cd45e8b96ca4a0",
        ),
        (
            "compose.vm.yaml", "core",
            "3d8f7b2173295b88afb5a746d9db8121867396f3d5d5d3848e454a32d2f9348b",
        ),
        (
            "compose.vm.yaml", "minio",
            "f1f6b7dba79949171a1164bc724e57837ec0c34ac278460c24aee6c29fd30233",
        ),
        (
            "compose.vm.yaml", "dashboard",
            "4580f2b765207ea5fa3e09e811043a955e12a78e6d266e622d57ac3e65162560",
        ),
        (
            "compose.vm.yaml", "caddy",
            "79a28e93f3e96e3a8426083e70fcbcd33d19e0a88e010053a416460bb67d88ec",
        ),
    ],
)
def test_remaining_service_configuration_is_unchanged(
    template: str, service: str, expected: str
) -> None:
    """Unapproved port/auth/mount/health/image changes must not ride with removal."""
    value = _load_template(_ROOT / "deploy" / template)["services"][service]
    normalized = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert hashlib.sha256(normalized.encode("utf-8")).hexdigest() == expected


def test_core_dockerfile_instructions_are_unchanged() -> None:
    """Comment cleanup cannot alter runtime/dependencies/user or the platform CMD."""
    lines = (_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    instructions = "\n".join(
        line for line in lines if line.strip() and not line.lstrip().startswith("#")
    ) + "\n"
    assert hashlib.sha256(instructions.encode("utf-8")).hexdigest() == (
        "5e9bb9b180da181315312ddbbf39fd9f9ce9512d9769f7d4da911bae2d35e33b"
    )
