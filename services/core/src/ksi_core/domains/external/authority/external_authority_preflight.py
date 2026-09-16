"""Read-only candidate validation for an externally signed authority bundle.

This module intentionally validates only the mounted configuration graph.  It
does not open journals, build an application, contact storage, or create
credentials.  Core startup remains responsible for binding the provider to a
durable receipt journal and attaching it to the assembled application.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from ksi_core.domains.external.authority.external_result_workflow_config import (
    load_external_result_workflow_config,
)
from ksi_core.domains.external.quantity.external_relative_volume_s3_capabilities import (
    ExternalRelativeVolumeS3InputCapabilityIssuer,
)

_OPERATOR_ROOT = Path("/run/ksi-operator")
_WORKFLOW_CONFIG = _OPERATOR_ROOT / "workflow.json"
_PROVIDER_CONFIG = _OPERATOR_ROOT / "provider.json"
_WORKFLOW_ENV = "KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG"
_PROVIDER_ENV = "KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG"
_AUTHORITY_JOURNAL_PATH = Path("/var/lib/ksi/data/external-quantitative-authority.jsonl")
_MAX_WORKFLOW_CONFIG_BYTES = 256 * 1024


class ExternalAuthorityPreflightError(RuntimeError):
    """The mounted authority configuration is not safe to activate."""


def _utc_clock() -> datetime:
    return datetime.now(UTC)


def _require_fixed_path(name: str, expected: Path) -> None:
    if os.environ.get(name) != str(expected):
        raise ExternalAuthorityPreflightError(f"{name} must use the fixed operator mount path")


def _require_fixed_authority_journal_path() -> None:
    """Keep the validation journal inside the disposable Core data mount.

    The workflow loader separately validates the full private configuration and
    journal bundle.  This narrow check prevents that configuration from moving
    preflight's required empty journal nodes into operator input or ``/tmp``.
    """
    try:
        descriptor = os.open(
            _WORKFLOW_CONFIG, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
    except OSError as exc:
        raise ExternalAuthorityPreflightError("workflow configuration is unavailable") from exc
    try:
        node = os.fstat(descriptor)
        if (
            not stat.S_ISREG(node.st_mode)
            or node.st_uid != os.geteuid()
            or node.st_gid != os.getegid()
            or (node.st_mode & 0o777) != 0o600
            or node.st_nlink != 1
            or not 0 < node.st_size <= _MAX_WORKFLOW_CONFIG_BYTES
        ):
            raise ExternalAuthorityPreflightError("workflow configuration is not private")
        raw = os.read(descriptor, _MAX_WORKFLOW_CONFIG_BYTES + 1)
        if len(raw) != node.st_size:
            raise ExternalAuthorityPreflightError(
                "workflow configuration changed during validation"
            )
        workflow = json.loads(raw.decode("utf-8"))
        if not isinstance(workflow, dict) or workflow.get("authorityJournalPath") != str(
            _AUTHORITY_JOURNAL_PATH
        ):
            raise ExternalAuthorityPreflightError(
                "workflow authority journal must use the fixed durable data path"
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalAuthorityPreflightError("workflow configuration is unreadable") from exc
    finally:
        os.close(descriptor)


def _require_readable_material(directory: Path) -> None:
    """Confirm supplied material is readable without reading or creating it."""
    try:
        metadata = directory.lstat()
    except OSError as exc:
        raise ExternalAuthorityPreflightError(
            f"operator material {directory.name} is unavailable"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ExternalAuthorityPreflightError(
            f"operator material {directory.name} must be a directory"
        )

    files = 0
    pending = [directory]
    while pending:
        parent = pending.pop()
        try:
            entries = list(os.scandir(parent))
        except OSError as exc:
            raise ExternalAuthorityPreflightError(
                f"operator material {directory.name} cannot be inspected"
            ) from exc
        for entry in entries:
            try:
                node = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ExternalAuthorityPreflightError(
                    f"operator material {directory.name} changed during validation"
                ) from exc
            if stat.S_ISLNK(node.st_mode):
                raise ExternalAuthorityPreflightError(
                    f"operator material {directory.name} contains a symlink"
                )
            if stat.S_ISDIR(node.st_mode):
                pending.append(Path(entry.path))
            elif stat.S_ISREG(node.st_mode):
                if not os.access(entry.path, os.R_OK):
                    raise ExternalAuthorityPreflightError(
                        f"operator material {directory.name} is not readable by Core"
                    )
                files += 1
            else:
                raise ExternalAuthorityPreflightError(
                    f"operator material {directory.name} contains an unsupported node"
                )
    if files == 0:
        raise ExternalAuthorityPreflightError(f"operator material {directory.name} is empty")


def _load_provider() -> Any:
    try:
        module = cast(
            Any,
            import_module("ksi_core.domains.external.authority.external_authority_provider"),
        )
        loader = module.load_external_authority_provider
    except ImportError as exc:
        raise ExternalAuthorityPreflightError("external authority provider is unavailable") from exc
    if not callable(loader):
        raise ExternalAuthorityPreflightError("external authority provider loader is unavailable")
    return loader(_PROVIDER_CONFIG, clock=_utc_clock)


def preflight_external_authority() -> dict[str, object]:
    """Validate configuration only; this is neither activation nor eligibility."""
    _require_fixed_path(_WORKFLOW_ENV, _WORKFLOW_CONFIG)
    _require_fixed_path(_PROVIDER_ENV, _PROVIDER_CONFIG)
    _require_fixed_authority_journal_path()
    _require_readable_material(_OPERATOR_ROOT / "secrets")
    _require_readable_material(_OPERATOR_ROOT / "signing")

    try:
        provider = _load_provider()
        provider_status = provider.status()
        if (
            not isinstance(provider_status, dict)
            or provider_status.get("status") != "CONFIG_VALIDATED"
            or provider_status.get("organizationId") != provider.organization_id
            or provider_status.get("businessEligible") is not False
        ):
            raise ExternalAuthorityPreflightError(
                "authority provider is not configuration-validated and inactive"
            )
        workflow = load_external_result_workflow_config(
            _WORKFLOW_CONFIG,
            participants=provider.participants,
            build_input_capability_issuer=ExternalRelativeVolumeS3InputCapabilityIssuer,
        )
        if (
            workflow.build_input_capability_issuer
            is not ExternalRelativeVolumeS3InputCapabilityIssuer
        ):
            raise ExternalAuthorityPreflightError("workflow omitted the S3 input-capability issuer")
    except ExternalAuthorityPreflightError:
        raise
    except Exception as exc:
        raise ExternalAuthorityPreflightError(
            "external authority configuration is blocked"
        ) from exc

    return {
        "status": "CONFIG_VALIDATED",
        "organizationId": provider.organization_id,
        "activationStatus": "NOT_ATTACHED",
        "quantitativeEligible": False,
    }


def main() -> int:
    try:
        print(json.dumps(preflight_external_authority(), separators=(",", ":"), sort_keys=True))
    except ExternalAuthorityPreflightError as exc:
        print(f"BLOCKED_EXTERNAL_AUTHORITY_CONFIG: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
