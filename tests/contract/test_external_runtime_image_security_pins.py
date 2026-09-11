"""External runtime remediation pins stay reproducible and independently reviewable."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DEBIAN_SNAPSHOT = "20260911T000000Z"
_OPENSSL_VERSION = "3.5.7-1~deb13u2"
_CRYPTOGRAPHY_VERSION = "50.0.1"


def _runtime_dockerfile(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


def test_external_runtime_images_pin_the_available_openssl_security_update() -> None:
    """Removing an exact patched package or reverting the immutable snapshot must fail."""
    required_packages = (
        f"openssl={_OPENSSL_VERSION}",
        f"libssl3t64={_OPENSSL_VERSION}",
        f"openssl-provider-legacy={_OPENSSL_VERSION}",
    )

    for name in ("Dockerfile.external-inspector", "Dockerfile.external-measurement"):
        dockerfile = _runtime_dockerfile(name)
        assert f"snapshot.debian.org/archive/debian-security/{_DEBIAN_SNAPSHOT}" in dockerfile
        for package in required_packages:
            assert re.search(rf"(?<!\\S){re.escape(package)}(?!\\S)", dockerfile)


def test_external_runtime_lock_requires_cryptography_security_release() -> None:
    """Downgrading the contained runtime below the patched cryptography release must fail."""
    processing_project = tomllib.loads(
        (_ROOT / "services/processing-controller/pyproject.toml").read_text(encoding="utf-8")
    )
    assert "cryptography>=50,<51" in processing_project["project"]["dependencies"]

    lock = tomllib.loads((_ROOT / "uv.lock").read_text(encoding="utf-8"))
    cryptography = next(package for package in lock["package"] if package["name"] == "cryptography")
    assert cryptography["version"] == _CRYPTOGRAPHY_VERSION
