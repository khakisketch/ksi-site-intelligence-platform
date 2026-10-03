"""External runtime remediation pins stay reproducible and independently reviewable."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DEBIAN_SNAPSHOT = "20261003T000000Z"
_OPENSSL_VERSION = "3.5.7-1~deb13u3"
_CRYPTOGRAPHY_VERSION = "50.0.1"


def _runtime_dockerfile(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


def test_external_runtime_images_pin_the_available_openssl_security_update() -> None:
    """Removing an exact patched package or reverting the immutable snapshot must fail."""
    required_packages = (
        "gzip=1.13-1+deb13u1",
        "libc-bin=2.41-12+deb13u4",
        "libc6=2.41-12+deb13u4",
        "libexpat1=2.8.3-1~deb13u1",
        "libpcre2-8-0=10.46-1~deb13u3",
        "libsqlite3-0=3.46.1-7+deb13u2",
        f"openssl={_OPENSSL_VERSION}",
        f"libssl3t64={_OPENSSL_VERSION}",
        f"openssl-provider-legacy={_OPENSSL_VERSION}",
        "perl-base=5.40.1-6+deb13u1",
    )

    for name in ("Dockerfile.external-inspector", "Dockerfile.external-measurement"):
        dockerfile = _runtime_dockerfile(name)
        assert f"snapshot.debian.org/archive/debian-security/{_DEBIAN_SNAPSHOT}" in dockerfile
        for package in required_packages:
            assert re.search(rf"(?<!\S){re.escape(package)}(?!\S)", dockerfile)


def test_external_runtime_lock_requires_cryptography_security_release() -> None:
    """Downgrading the contained runtime below the patched cryptography release must fail."""
    processing_project = tomllib.loads(
        (_ROOT / "services/processing-controller/pyproject.toml").read_text(encoding="utf-8")
    )
    assert "cryptography>=50,<51" in processing_project["project"]["dependencies"]

    lock = tomllib.loads((_ROOT / "uv.lock").read_text(encoding="utf-8"))
    cryptography = next(package for package in lock["package"] if package["name"] == "cryptography")
    assert cryptography["version"] == _CRYPTOGRAPHY_VERSION


@pytest.mark.parametrize("pin", [
    "gzip=1.13-1+deb13u1", "libc-bin=2.41-12+deb13u4", "libc6=2.41-12+deb13u4",
    "libexpat1=2.8.3-1~deb13u1", "libpcre2-8-0=10.46-1~deb13u3",
    "libsqlite3-0=3.46.1-7+deb13u2", "openssl=3.5.7-1~deb13u3",
    "libssl3t64=3.5.7-1~deb13u3", "openssl-provider-legacy=3.5.7-1~deb13u3",
    "perl-base=5.40.1-6+deb13u1",
])
@pytest.mark.parametrize("name", [
    "Dockerfile.external-inspector", "Dockerfile.external-measurement",
])
@pytest.mark.parametrize("suffix", ["", "-unapproved"])
def test_security_contract_rejects_missing_or_substituted_exact_os_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pin: str, name: str, suffix: str,
) -> None:
    """A regression in any of the ten pins must fail the tracked source contract."""
    for relative in ("Dockerfile.external-inspector", "Dockerfile.external-measurement"):
        text = _runtime_dockerfile(relative)
        if relative == name:
            assert pin in text
            text = text.replace(pin, pin + suffix if suffix else "")
        (tmp_path / relative).write_text(text, encoding="utf-8")
    monkeypatch.setitem(globals(), "_ROOT", tmp_path)
    with pytest.raises(AssertionError):
        test_external_runtime_images_pin_the_available_openssl_security_update()
