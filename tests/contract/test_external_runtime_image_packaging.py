"""Packaging contract for the two independently released quantitative runtimes.

These checks bind source packaging only.  They do not claim a registry digest,
SBOM, vulnerability approval, deployed socket, or quantitative authority.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PINNED_PYTHON = (
    "python:3.12.14-slim@sha256:"
    "09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217"
)
_PINNED_UV = (
    "ghcr.io/astral-sh/uv:0.11.15@sha256:"
    "e590846f4776907b254ac0f44b5b380347af5d90d668138ca7938d1b0c2f98d3"
)
_RUNTIMES = {
    "Dockerfile.external-inspector": {
        "user": "ksi-inspector-image",
        "uid": "10003",
        "command": "/app/.venv/bin/ksi-external-inspector-entrypoint",
    },
    "Dockerfile.external-measurement": {
        "user": "ksi-measurement-image",
        "uid": "10004",
        "command": "/app/.venv/bin/ksi-external-measurement-entrypoint",
    },
}
_ALLOWED_CONTEXT_ROOTS = {"pyproject.toml", "uv.lock", "packages", "services"}
_RUNTIME_COPY_LINES = {
    "COPY pyproject.toml uv.lock ./",
    "COPY packages packages",
    "COPY services services",
    "COPY --from=runtime-builder /app/.venv /app/.venv",
    "COPY --from=runtime-builder /app/packages/change-detection /app/packages/change-detection",
    "COPY --from=runtime-builder /app/packages/domain /app/packages/domain",
    "COPY --from=runtime-builder /app/packages/event-contracts /app/packages/event-contracts",
    "COPY --from=runtime-builder /app/packages/geo-core /app/packages/geo-core",
    "COPY --from=runtime-builder /app/packages/geo-spatial /app/packages/geo-spatial",
    "COPY --from=runtime-builder /app/packages/perception /app/packages/perception",
    "COPY --from=runtime-builder /app/services/processing-controller "
    "/app/services/processing-controller",
}


def test_independent_external_runtime_images_have_closed_fixed_entrypoints() -> None:
    for relative, expected in _RUNTIMES.items():
        dockerfile = (_ROOT / relative).read_text(encoding="utf-8")

        assert f"FROM {_PINNED_PYTHON}" in dockerfile
        assert f"COPY --from={_PINNED_UV}" in dockerfile
        assert "https://snapshot.debian.org/archive/debian/20260911T000000Z" in dockerfile
        assert (
            "https://snapshot.debian.org/archive/debian-security/20260911T000000Z"
            in dockerfile
        )
        assert "libexpat1=2.8.3-1~deb13u1" in dockerfile
        assert "Acquire::Check-Valid-Until=false" in dockerfile
        assert dockerfile.count("https://snapshot.debian.org/archive/") == 2
        assert "uv sync --locked --package ksi-processing-controller --no-dev" in dockerfile
        assert "COPY . ." not in dockerfile
        assert set(dockerfile.splitlines()) >= _RUNTIME_COPY_LINES
        assert (
            f"useradd --create-home --uid {expected['uid']} {expected['user']}" in dockerfile
        )
        assert f"USER {expected['user']}" in dockerfile
        assert f'CMD ["{expected["command"]}"]' in dockerfile
        assert "ENTRYPOINT" not in dockerfile
        assert "EXPOSE" not in dockerfile


def test_external_runtime_images_do_not_share_an_entrypoint_or_image_identity() -> None:
    rendered = {
        relative: (_ROOT / relative).read_text(encoding="utf-8")
        for relative in _RUNTIMES
    }

    inspector = rendered["Dockerfile.external-inspector"]
    measurement = rendered["Dockerfile.external-measurement"]
    assert "ksi-external-measurement-entrypoint" not in inspector
    assert "ksi-external-inspector-entrypoint" not in measurement
    assert "10004" not in inspector
    assert "10003" not in measurement


def test_external_runtime_build_context_is_allowlisted_and_excludes_private_roots() -> None:
    for dockerfile in _RUNTIMES:
        ignore_file = _ROOT / f"{dockerfile}.dockerignore"
        rules = [
            line.strip()
            for line in ignore_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

        assert rules[0] == "**"
        assert all(rule == "**" or rule.startswith("!") for rule in rules)
        allowed_roots = {rule.removeprefix("!").split("/", 1)[0] for rule in rules[1:]}
        assert allowed_roots == _ALLOWED_CONTEXT_ROOTS
        for private_root in ("download", "deploy", "data", ".dev-data", ".secrets"):
            assert all(not rule.startswith(f"!{private_root}") for rule in rules)
