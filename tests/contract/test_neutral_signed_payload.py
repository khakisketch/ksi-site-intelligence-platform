"""Neutral payload-digest helpers (Task 1).

Pre-extraction baseline captured from
``ksi_mission_contracts.signing`` (main 15ed73e) before any move; the
neutral module must reproduce these vectors byte-for-byte while every
existing import path keeps returning the SAME function objects.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "services/core/src",
    REPOSITORY_ROOT / "packages/event-contracts/src",
    REPOSITORY_ROOT / "packages/geo-core/src",
    REPOSITORY_ROOT / "packages/domain/src",
    REPOSITORY_ROOT / "packages/mission-contracts/src",
    REPOSITORY_ROOT / "packages/mission-planning/src",
)

WRAPPER_PREFIX = "계약을 정규 JSON 으로 표현할 수 없다: "


def _run_python(script: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(root) for root in SOURCE_ROOTS] + ([existing] if existing else [])
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=60,
    )


def _assert_subprocess_ok(script: str) -> None:
    completed = _run_python(script)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _blocker_prelude(denied: tuple[str, ...]) -> str:
    return dedent(
        """
        import importlib.abc
        import sys

        _DENIED_PREFIXES = %r

        class _DenyPrefixes(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name in _DENIED_PREFIXES or any(
                    name.startswith(prefix + ".") for prefix in _DENIED_PREFIXES
                ):
                    raise ImportError(f"task1 isolation probe denies {name}")
                return None

        sys.meta_path.insert(0, _DenyPrefixes())
        for _module in list(sys.modules):
            assert _module not in _DENIED_PREFIXES and not any(
                _module.startswith(prefix + ".") for prefix in _DENIED_PREFIXES
            ), _module
        """
    ) % (denied,)


_NEUTRAL_DENIED = ("ksi_mission_contracts", "ksi_mission_planning", "ksi_core.acquisition")


# ── Named byte oracle ─────────────────────────────────────────────────


def test_signature_removal_is_top_level_only() -> None:
    from ksi_domain.signed_payload import canonical_payload_bytes

    assert canonical_payload_bytes(
        {"signature": {"keyId": "ignored"}, "text": "현장", "nested": {"signature": "keep"}}
    ) == '{"nested":{"signature":"keep"},"text":"현장"}'.encode("utf-8")  # noqa: UP012


# ── Capture-then-pin vectors ──────────────────────────────────────────


def test_unicode_key_ordering_is_pinned() -> None:
    from ksi_domain.signed_payload import canonical_payload_bytes

    assert canonical_payload_bytes({"b": 1, "가": 2, "a": 3}) == ('{"a":3,"b":1,"가":2}'.encode())


def test_nested_signature_is_retained() -> None:
    from ksi_domain.signed_payload import canonical_payload_bytes

    assert canonical_payload_bytes({"nested": {"signature": "keep"}, "x": 1}) == (
        b'{"nested":{"signature":"keep"},"x":1}'
    )


def test_sha256_digest_format_is_pinned() -> None:
    from ksi_domain.signed_payload import sha256_digest

    assert sha256_digest(b"abc") == "sha256:" + hashlib.sha256(b"abc").hexdigest()
    assert sha256_digest(b"abc") == (
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_input_mapping_is_unchanged() -> None:
    from ksi_domain.signed_payload import canonical_payload_bytes

    original = {"signature": {"keyId": "ignored"}, "text": "현장", "n": 1}
    snapshot = dict(original)
    canonical_payload_bytes(original)
    assert original == snapshot


def test_nan_and_infinity_fail_as_wrapped_valueerror() -> None:
    from ksi_domain.signed_payload import canonical_payload_bytes

    for bad in (float("nan"), float("inf"), float("-inf")):
        try:
            canonical_payload_bytes({"v": bad})
        except ValueError as exc:
            assert str(exc).startswith(WRAPPER_PREFIX)
            assert "Out of range float values are not JSON compliant" in str(exc)
        else:
            raise AssertionError(f"no raise for {bad!r}")


def test_set_failure_keeps_wrapper_message_and_valueerror_type() -> None:
    from ksi_domain.signed_payload import canonical_payload_bytes

    with pytest.raises(ValueError, match="정규 JSON 으로 표현할 수 없다"):
        canonical_payload_bytes({"v": {1, 2}})
    try:
        canonical_payload_bytes({"v": {1, 2}})
    except ValueError as exc:
        assert str(exc).startswith(WRAPPER_PREFIX)
        assert "Object of type set is not JSON serializable" in str(exc)
    else:
        raise AssertionError("no raise for set")


def test_lone_surrogate_fails_as_valueerror() -> None:
    from ksi_domain.signed_payload import canonical_payload_bytes

    with pytest.raises(ValueError, match="정규 JSON 으로 표현할 수 없다"):
        canonical_payload_bytes({"v": "\ud800"})
    try:
        canonical_payload_bytes({"v": "\ud800"})
    except ValueError as exc:
        assert str(exc).startswith(WRAPPER_PREFIX)
        assert isinstance(exc, ValueError)
    else:
        raise AssertionError("no raise for lone surrogate")


# ── Fresh-process isolation ───────────────────────────────────────────


def test_neutral_module_imports_without_mission_or_acquisition() -> None:
    _assert_subprocess_ok(
        _blocker_prelude(_NEUTRAL_DENIED)
        + dedent(
            """
            import sys

            from ksi_domain.signed_payload import (
                canonical_payload_bytes,
                sha256_digest,
            )

            assert canonical_payload_bytes(
                {"signature": {"keyId": "ignored"}, "text": "현장",
                 "nested": {"signature": "keep"}}
            ) == '{"nested":{"signature":"keep"},"text":"현장"}'.encode("utf-8")  # noqa: UP012
            assert sha256_digest(b"abc") == (
                "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
            )
            for _denied in ("ksi_mission_contracts", "ksi_mission_planning",
                            "ksi_core.acquisition"):
                assert _denied not in sys.modules
                assert not any(
                    module == _denied or module.startswith(_denied + ".")
                    for module in sys.modules
                )
            """
        )
    )


# ── Legacy identity (outside the deny hook) ───────────────────────────


def test_legacy_signer_reexports_the_same_function_objects() -> None:
    import ksi_domain.signed_payload as neutral
    import ksi_mission_contracts.signing as signing

    assert signing.canonical_payload_bytes is neutral.canonical_payload_bytes
    assert signing.sha256_digest is neutral.sha256_digest
