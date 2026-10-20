"""External consumer: cross-check the common analysis result contract.

This module is intentionally dependency-light: it imports only the Python
standard library plus ``httpx``. It never imports KSI packages, test stores,
or fixtures, so it can be copied onto an outside codebase as-is. The ``mcp``
SDK is imported lazily, only inside the MCP fetch path, so ``import`` of this
module works with stdlib + httpx alone.

What it does
------------

An outside codebase reads one Core analysis through BOTH consumption paths
and cross-checks the seven elements of the common result contract, plus the
shared-epoch continuation hint and the coverage byte resource:

* HTTP: ``GET /v2/sites/{site}/analyses`` (paged),
  ``GET /v2/sites/{site}/analyses/{id}``,
  ``GET /v2/sites/{site}/analyses/{id}/evidence`` (paged until exhausted),
  ``GET /v2/sites/{site}/analyses/{id}/coverage`` (Range requests).
* MCP: the official local stdio adapter (``python -m ksi_analysis_mcp.server``)
  over the ``mcp`` SDK, calling ``ksi_get_analysis``,
  ``ksi_get_analysis_result``, ``ksi_get_analysis_evidence`` and
  ``ksi_list_analyses`` for the same site/analysis.

Every HTTP call is a GET. Nothing here writes to Core.

Usage
-----

.. code:: console

   $ python result_contract_crosscheck.py \\
       --core-origin http://127.0.0.1:8000 \\
       --site-id site-a \\
       --analysis-id analysis-v1-... \\
       --out /tmp/crosscheck.json \\
       --token <FIELD_OPERATOR_JWT>
       [--mcp-token-file /abs/path/to/mcp-token]
       [--mcp-core-origin http://127.0.0.1:8000]
       [--timeout-seconds 30] [--max-pages 8]

The bearer token comes from ``--token`` or the ``KSI_CUSTOMER_TOKEN``
environment variable. The MCP path is optional: when ``--mcp-token-file`` is
omitted, MCP-dependent comparisons are reported as SKIPPED (not PASS), and
``--mcp-core-origin`` defaults to ``--core-origin``. The MCP token file must
be an absolute path to an owner-protected file holding the adapter bearer
token; this script never reads or prints that file, it only hands the path to
the adapter subprocess.

Exit codes: 0 when no check FAILs (SKIPPED allowed), 1 when any check FAILs,
2 for configuration/input problems. Configuration problems print exactly one
fixed closed code to stderr (``TOKEN_UNAVAILABLE``, ``INVALID_IDENTIFIER``,
``CORE_UNAVAILABLE``, ``MCP_UNAVAILABLE``, ``INVALID_RESPONSE``,
``PERSIST_FAILED``) and never echo the token or any response body.

What the record proves (and does not prove)
-------------------------------------------

A PASS record proves that two independent projections of the same Core record
(the HTTP API and the MCP adapter) present the same seven contract elements:
numeric metrics, region, input version, calculation settings, valid region,
quality indicators, and limitations -- and that Core's shared-epoch list hint
can be re-derived from the immutable epoch records. It does NOT prove field
accuracy, customer acceptance, or that a numeric result may be used for a
settlement decision.

State rules that keep a coherent state from reading as a broken contract:

* A numeric result Core withheld (not started, blocked, reassessment
  required) makes the result-scoped elements SKIPPED with the reason -- not
  FAIL, and not a silent PASS.
* Across two analyses of one observation epoch, only the observation
  identity has to match. The inspection-report digest and the input digest
  are produced once per analysis and are recorded, never compared.
* A continuation is verified at the level its records reach: at the selector
  level when the other pair has no epoch records yet, from the immutable
  epoch records when it has.

Safety properties
-----------------

* The bearer token is attached to Core API calls only; the adapter
  subprocess receives its own token file path, never this token.
* Nothing in this module prints tokens, token file contents, upload URLs,
  raw response bodies, or coverage bytes. Details carry only safe
  identifiers, digests, numbers, and check outcomes.
* Site/analysis identifiers must match ``[A-Za-z0-9][A-Za-z0-9_.-]*`` before
  any request is formed. Timeouts must be finite and positive; page counts
  are bounded.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

TOOL_NAME = "result_contract_crosscheck"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIPPED = "SKIPPED"

#: The seven elements of the common result contract, in a fixed order.
SEVEN_ELEMENT_IDS = (
    "numeric",
    "region",
    "input-version",
    "calculation-settings",
    "valid-region",
    "quality",
    "limitations",
)

CHECK_IDS = SEVEN_ELEMENT_IDS + (
    "continuation",
    "coverage-resource",
    "http-list",
    "mcp-parity",
)

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)\Z")

#: Float comparison tolerance for area identities; always stated in details.
_AREA_RELATIVE_TOLERANCE = 1e-9
_EVIDENCE_PAGE_LIMIT = 32
_LIST_PAGE_LIMIT = 50
_COVERAGE_RANGE_BYTES = 65_536
_MAX_PAGES = 64


class _Failure(Exception):
    """Closed control-flow failure carrying only a fixed public code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _ClosedParser(argparse.ArgumentParser):
    """Argument parser that never echoes raw values, markers, or tracebacks."""

    def error(self, message: object) -> Any:
        print(f"{TOOL_NAME}: INVALID_IDENTIFIER", file=sys.stderr)
        raise SystemExit(2)


@dataclass(frozen=True)
class CheckRecord:
    """One named cross-check outcome; detail carries only safe values."""

    id: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "status": self.status, "detail": self.detail}


@dataclass
class ComparisonInputs:
    """Plain-JSON comparison inputs; all values are already-fetched dicts."""

    site_id: str
    analysis_id: str
    http_detail: dict[str, Any]
    http_evidence_items: list[dict[str, Any]]
    http_list_items: list[dict[str, Any]]
    named_continuations: list[str]
    siblings: dict[str, dict[str, Any]]
    coverage: dict[str, Any] | None
    mcp_detail: dict[str, Any] | None = None
    mcp_result: dict[str, Any] | None = None
    mcp_evidence_items: list[dict[str, Any]] | None = None
    mcp_list_items: list[dict[str, Any]] | None = None


# -- small pure helpers ----------------------------------------------------


def _short(value: Any, *, limit: int = 200) -> str:
    """Truncated repr for a safe scalar; never a body dump."""
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _by_kind(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict) and item.get("kind") == kind]


def _epoch_records(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for item in _by_kind(items, "EPOCH_IDENTITY"):
        epoch = item.get("epoch")
        if isinstance(epoch, str) and epoch not in records:
            records[epoch] = item
    return records


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _withheld_result_note(inputs: ComparisonInputs) -> str:
    """Why Core shows no numeric result for this analysis (a coherent state)."""
    detail = inputs.http_detail
    blockers = detail.get("blockers")
    codes = (
        [b.get("code") for b in blockers if isinstance(b, dict)]
        if isinstance(blockers, list)
        else []
    )
    return (
        f"Core withheld the numeric result "
        f"(executionState={_short(detail.get('executionState'))}, "
        f"suitabilityState={_short(detail.get('suitabilityState'))}, "
        f"blockers={_short(codes)})"
    )


def _result_or_skip(
    inputs: ComparisonInputs, check_id: str
) -> tuple[dict[str, Any] | None, CheckRecord | None]:
    """Return the numeric result, or a SKIPPED record when Core withheld it.

    A withheld numeric result is a coherent product state (not started,
    blocked, reassessment required), not a broken contract: the consumer
    reports it as SKIPPED with the reason, so a missing number is never read
    as a violated element and is never silently passed either.
    """
    result = inputs.http_detail.get("result")
    if isinstance(result, dict):
        return result, None
    return None, CheckRecord(check_id, STATUS_SKIPPED, _withheld_result_note(inputs))


# -- the seven element checks + continuation/coverage/list/parity ------------


def _check_numeric(inputs: ComparisonInputs) -> CheckRecord:
    result, skipped = _result_or_skip(inputs, "numeric")
    if skipped is not None:
        return skipped
    assert result is not None
    metrics = result.get("metrics")
    problems: list[str] = []
    if not isinstance(metrics, dict):
        problems.append("detail result metrics missing")
        metrics = {}
    numeric_items = _by_kind(inputs.http_evidence_items, "NUMERIC_RESULT")
    if len(numeric_items) != 1:
        problems.append(f"expected exactly one NUMERIC_RESULT item, found {len(numeric_items)}")
    else:
        item = numeric_items[0]
        for field_name in ("resultId", "reportDigest", "numericResultIdentityDigest"):
            if item.get(field_name) != result.get(field_name):
                problems.append(f"NUMERIC_RESULT {field_name} differs from detail result")
    mcp_payloads = (
        ("ksi_get_analysis", inputs.mcp_detail),
        ("ksi_get_analysis_result", inputs.mcp_result),
    )
    for label, payload in mcp_payloads:
        if payload is not None:
            other = payload.get("result")
            other_metrics = other.get("metrics") if isinstance(other, dict) else None
            if other_metrics != metrics:
                problems.append(f"MCP {label} metrics differ from HTTP detail metrics")
    summary = f"resultId={_short(result.get('resultId'))} metrics={_short(metrics)}"
    if problems:
        return CheckRecord("numeric", STATUS_FAIL, "; ".join(problems) + f" [{summary}]")
    return CheckRecord("numeric", STATUS_PASS, f"metrics and result identity agree [{summary}]")


def _check_region(inputs: ComparisonInputs) -> CheckRecord:
    result, skipped = _result_or_skip(inputs, "region")
    if skipped is not None:
        return skipped
    assert result is not None
    coverage = result.get("coverage")
    if not isinstance(coverage, dict):
        return CheckRecord("region", STATUS_FAIL, "HTTP detail carries no coverage summary")
    problems: list[str] = []
    mcp_payloads = (
        ("ksi_get_analysis", inputs.mcp_detail),
        ("ksi_get_analysis_result", inputs.mcp_result),
    )
    for label, payload in mcp_payloads:
        if payload is None:
            continue
        other = payload.get("result")
        other_coverage = other.get("coverage") if isinstance(other, dict) else None
        if not isinstance(other_coverage, dict):
            problems.append(f"MCP {label} carries no coverage summary")
            continue
        for field_name in ("rows", "columns", "bounds", "selectedAreaM2"):
            if other_coverage.get(field_name) != coverage.get(field_name):
                problems.append(f"MCP {label} coverage {field_name} differs")
    summary = (
        f"rows={_short(coverage.get('rows'))} columns={_short(coverage.get('columns'))} "
        f"bounds={_short(coverage.get('bounds'))} "
        f"selectedAreaM2={_short(coverage.get('selectedAreaM2'))}"
    )
    if problems:
        return CheckRecord("region", STATUS_FAIL, "; ".join(problems) + f" [{summary}]")
    return CheckRecord("region", STATUS_PASS, f"coverage region agrees [{summary}]")


def _check_input_version(inputs: ComparisonInputs) -> CheckRecord:
    epochs = _epoch_records(inputs.http_evidence_items)
    problems: list[str] = []
    for epoch in ("BASELINE", "CURRENT"):
        item = epochs.get(epoch)
        if item is None:
            problems.append(f"{epoch} EPOCH_IDENTITY item missing")
            continue
        expected_selector = inputs.http_detail.get(epoch.lower())
        if item.get("selector") != expected_selector:
            problems.append(f"{epoch} EPOCH_IDENTITY selector differs from detail selector")
        for field_name in (
            "observationEpochId",
            "artifactId",
            "observedSha256",
            "observedSizeBytes",
            "inputDigest",
            "inspectionReportDigest",
        ):
            value = item.get(field_name)
            if field_name == "observedSizeBytes":
                if type(value) is not int or value <= 0:
                    problems.append(f"{epoch} {field_name} is not a positive integer")
            elif not _nonempty_string(value):
                problems.append(f"{epoch} {field_name} missing or empty")
    if problems:
        return CheckRecord("input-version", STATUS_FAIL, "; ".join(problems))
    observed = sorted(str(epochs[e].get("observedSha256")) for e in ("BASELINE", "CURRENT"))
    return CheckRecord(
        "input-version",
        STATUS_PASS,
        f"BASELINE/CURRENT selectors and version fields present; observedSha256={_short(observed)}",
    )


def _check_calculation_settings(inputs: ComparisonInputs) -> CheckRecord:
    calc_items = _by_kind(inputs.http_evidence_items, "CALCULATION_IDENTITY")
    if len(calc_items) != 1:
        return CheckRecord(
            "calculation-settings",
            STATUS_FAIL,
            f"expected exactly one CALCULATION_IDENTITY item, found {len(calc_items)}",
        )
    calculation = calc_items[0].get("calculation")
    if not isinstance(calculation, dict):
        return CheckRecord(
            "calculation-settings", STATUS_FAIL, "CALCULATION_IDENTITY carries no calculation"
        )
    refs = [
        item
        for item in _by_kind(inputs.http_evidence_items, "AUTHORITY_REFERENCE")
        if item.get("referenceName") == "calculationIdentityDigest"
    ]
    if len(refs) != 1:
        return CheckRecord(
            "calculation-settings",
            STATUS_FAIL,
            f"expected one calculationIdentityDigest reference, found {len(refs)}",
        )
    source_digest = refs[0].get("sourceDigest")
    if not _nonempty_string(source_digest) or source_digest != refs[0].get("recordId"):
        return CheckRecord(
            "calculation-settings",
            STATUS_FAIL,
            "calculationIdentityDigest AUTHORITY_REFERENCE has no self-consistent sourceDigest",
        )
    runtime = calculation.get("runtime")
    policy = calculation.get("policy")
    present: list[str] = []
    if isinstance(runtime, dict):
        for field_name in (
            "workerExecutableDigest",
            "workerBuildDigest",
            "runtimeImageVersion",
            "runtimeImageOciDigest",
            "dependencyLockDigest",
        ):
            if _nonempty_string(runtime.get(field_name)):
                present.append(f"runtime.{field_name}")
    if isinstance(policy, dict):
        policy_fields = (
            "policyId",
            "profileDigest",
            "algorithmDigest",
            "configDigest",
            "policyDigest",
        )
        for field_name in policy_fields:
            if policy.get(field_name) not in (None, ""):
                present.append(f"policy.{field_name}")
    if not isinstance(runtime, dict) or not [
        name for name in present if name.startswith("runtime.")
    ]:
        return CheckRecord(
            "calculation-settings",
            STATUS_FAIL,
            "calculation identity carries no worker/engine version identity",
        )
    return CheckRecord(
        "calculation-settings",
        STATUS_PASS,
        f"calculationIdentityDigest={_short(source_digest)} "
        f"versionFields={_short(sorted(present))}",
    )


def _check_valid_region(inputs: ComparisonInputs) -> CheckRecord:
    result, skipped = _result_or_skip(inputs, "valid-region")
    if skipped is not None:
        return skipped
    assert result is not None
    coverage = result.get("coverage")
    if not isinstance(coverage, dict):
        return CheckRecord("valid-region", STATUS_FAIL, "HTTP detail carries no coverage summary")
    problems: list[str] = []
    try:
        selected = coverage["selectedCellCount"]
        common = coverage["commonValidCellCount"]
        unavailable = coverage["unavailableCellCount"]
        excluded = coverage["thresholdExcludedCellCount"]
        cell_area = coverage["cellAreaM2"]
        selected_area = coverage["selectedAreaM2"]
        common_area = coverage["commonValidAreaM2"]
        bounds = coverage["bounds"]
    except KeyError as exc:
        return CheckRecord(
            "valid-region", STATUS_FAIL, f"coverage summary misses {_short(exc.args)}"
        )
    counts_int = (
        type(selected) is int
        and type(common) is int
        and type(unavailable) is int
        and type(excluded) is int
    )
    if not counts_int:
        problems.append("cell counts are not integers")
    elif selected != common + unavailable + excluded:
        problems.append("cell counts do not partition selected cells")
    tolerance = _AREA_RELATIVE_TOLERANCE
    for label, _expected, actual in (
        ("selectedAreaM2", cell_area, selected_area),
        ("commonValidAreaM2", cell_area, common_area),
    ):
        count = selected if label == "selectedAreaM2" else common
        if not (
            isinstance(cell_area, (int, float))
            and isinstance(actual, (int, float))
            and isinstance(count, int)
            and math.isfinite(cell_area)
            and math.isfinite(actual)
            and math.isclose(actual, cell_area * count, rel_tol=tolerance, abs_tol=0.0)
        ):
            problems.append(f"{label} is not cellAreaM2 times its cell count")
    if not (isinstance(bounds, list) and len(bounds) == 4):
        problems.append("bounds length is not 4")
    summary = (
        f"cells={_short(selected)}/{_short(common)}/"
        f"{_short(unavailable)}/{_short(excluded)} tol={tolerance}"
    )
    if problems:
        return CheckRecord("valid-region", STATUS_FAIL, "; ".join(problems) + f" [{summary}]")
    return CheckRecord(
        "valid-region", STATUS_PASS, f"partition and area identities hold [{summary}]"
    )


def _check_quality(inputs: ComparisonInputs) -> CheckRecord:
    evaluations = _by_kind(inputs.http_evidence_items, "EVALUATION")
    problems: list[str] = []
    outcomes: dict[str, str] = {}
    for epoch in ("BASELINE", "CURRENT"):
        epoch_items = [item for item in evaluations if item.get("epoch") == epoch]
        if not epoch_items:
            problems.append(f"{epoch} EVALUATION item missing")
            continue
        for item in epoch_items:
            if not _nonempty_string(item.get("outcome")):
                problems.append(f"{epoch} EVALUATION outcome missing")
            reasons = item.get("reasonCodes")
            reasons_ok = (
                isinstance(reasons, list)
                and len(reasons) > 0
                and all(_nonempty_string(r) for r in reasons)
            )
            if not reasons_ok:
                problems.append(f"{epoch} EVALUATION reasonCodes missing or empty")
        outcomes[epoch] = str(epoch_items[0].get("outcome"))
    result = inputs.http_detail.get("result")
    metrics = result.get("metrics") if isinstance(result, dict) else None
    uncertainty = metrics.get("uncertaintyM3") if isinstance(metrics, dict) else None
    limitation_codes = result.get("limitationCodes") if isinstance(result, dict) else None
    summary = (
        f"outcomes={_short(outcomes)} uncertaintyM3={_short(uncertainty)} "
        f"limitationCodes={_short(limitation_codes)}"
    )
    if problems:
        return CheckRecord("quality", STATUS_FAIL, "; ".join(problems) + f" [{summary}]")
    return CheckRecord("quality", STATUS_PASS, f"both epoch evaluations present [{summary}]")


def _check_limitations(inputs: ComparisonInputs) -> CheckRecord:
    items = _by_kind(inputs.http_evidence_items, "LIMITATION")
    problems: list[str] = []
    blocker_codes: list[str] = []
    result_codes: list[str] = []
    for item in items:
        epoch = item.get("epoch")
        if epoch is not None and epoch not in ("BASELINE", "CURRENT"):
            problems.append(f"LIMITATION code {_short(item.get('code'))} has invalid epoch")
        source = item.get("source")
        code = item.get("code")
        if not _nonempty_string(code) or not isinstance(code, str):
            problems.append("LIMITATION item with missing code")
            continue
        if source == "BLOCKER":
            blocker_codes.append(code)
        elif source == "RESULT":
            result_codes.append(code)
        else:
            problems.append(f"LIMITATION code {_short(code)} has unknown source")
    detail = inputs.http_detail
    view_blockers = detail.get("blockers")
    expected_blockers = (
        sorted(str(b.get("code")) for b in view_blockers)
        if isinstance(view_blockers, list)
        else None
    )
    result = detail.get("result")
    if isinstance(result, dict):
        expected_result_codes = sorted(result.get("limitationCodes", []) or [])
    else:
        # Core withheld the numeric result: then no result-scoped limitation
        # code may exist. A RESULT-scoped code without a result is incoherent
        # and stays a FAIL.
        expected_result_codes = []
        if result_codes:
            problems.append("RESULT LIMITATION codes are recorded but Core shows no numeric result")
    if expected_blockers is None or sorted(blocker_codes) != expected_blockers:
        problems.append("BLOCKER LIMITATION codes differ from detail blockers")
    if sorted(result_codes) != expected_result_codes:
        problems.append("RESULT LIMITATION codes differ from detail result limitationCodes")
    summary = (
        f"blockerCodes={_short(sorted(blocker_codes))} "
        f"resultCodes={_short(sorted(result_codes))} "
        f"detailResultCodes={_short(expected_result_codes)}"
    )
    if problems:
        return CheckRecord("limitations", STATUS_FAIL, "; ".join(problems) + f" [{summary}]")
    if not isinstance(result, dict):
        return CheckRecord(
            "limitations",
            STATUS_PASS,
            f"blocker limitations consistent; no result-scoped limitation exists "
            f"[{summary}] {_withheld_result_note(inputs)}",
        )
    return CheckRecord(
        "limitations", STATUS_PASS, f"limitation codes reported and consistent [{summary}]"
    )


# Fields that describe the OBSERVATION itself. The same observation epoch must
# carry the same values in every analysis that uses it, so these have to match
# across two analyses that share an epoch.
_SHARED_OBSERVATION_FIELDS = (
    "observationEpochId",
    "artifactId",
    "observedSha256",
    "observedSizeBytes",
    "observedCrsIdentifier",
    "observedCrsDigest",
    "verticalReferenceIdentifier",
    "verticalReferenceBasis",
    "verticalUnit",
    "transformDigest",
)

# Fields bound to ONE execution of an analysis rather than to the observation.
# Every analysis performs its own inspection and seals its own input digest,
# so these legitimately differ between two analyses that share an epoch. They
# are reported, never required to match.
_PER_EXECUTION_EPOCH_FIELDS = (
    "inputDigest",
    "inspectionReportDigest",
    "inspectionReportRecordId",
)


def _verify_continuation_pair(
    older_epochs: dict[str, dict[str, Any]],
    newer_epochs: dict[str, dict[str, Any]],
) -> tuple[bool, list[str], list[str], dict[str, bool]]:
    """Re-derive one shared-epoch link from the immutable epoch records.

    Only the observation identity has to match. The per-execution digests are
    produced once per analysis and are reported instead of compared.
    """
    older_current = older_epochs.get("CURRENT")
    newer_baseline = newer_epochs.get("BASELINE")
    if older_current is None or newer_baseline is None:
        return False, [], ["missing CURRENT/BASELINE EPOCH_IDENTITY"], {}
    matched: list[str] = []
    mismatched: list[str] = []
    for field_name in _SHARED_OBSERVATION_FIELDS:
        left = older_current.get(field_name)
        right = newer_baseline.get(field_name)
        if field_name == "observedSizeBytes":
            # A byte count, not a string: compare it as a positive integer.
            if type(right) is int and right > 0 and right == left:
                matched.append(field_name)
            else:
                mismatched.append(field_name)
            continue
        if _nonempty_string(right) and right == left:
            matched.append(field_name)
        else:
            mismatched.append(field_name)
    per_execution = {
        field_name: older_current.get(field_name) == newer_baseline.get(field_name)
        for field_name in _PER_EXECUTION_EPOCH_FIELDS
    }
    return not mismatched, matched, mismatched, per_execution


def _check_continuation(inputs: ComparisonInputs) -> tuple[CheckRecord, list[dict[str, Any]]]:
    target_epochs = _epoch_records(inputs.http_evidence_items)
    target_detail = inputs.http_detail
    entries: list[dict[str, Any]] = []
    ok = True
    for sibling_id in sorted(inputs.named_continuations):
        sibling = inputs.siblings.get(sibling_id)
        if sibling is None:
            ok = False
            entries.append(
                {
                    "analysisId": sibling_id,
                    "direction": "unknown",
                    "verified": False,
                    "matchedFields": [],
                    "detail": "sibling record unavailable",
                }
            )
            continue
        sibling_detail = sibling.get("detail")
        sibling_epochs = _epoch_records(sibling.get("evidenceItems", []))
        if not isinstance(sibling_detail, dict):
            ok = False
            entries.append(
                {
                    "analysisId": sibling_id,
                    "direction": "unknown",
                    "verified": False,
                    "matchedFields": [],
                    "detail": "sibling detail unreadable",
                }
            )
            continue
        if sibling_detail.get("baseline") == target_detail.get("current"):
            direction = "newer"
            older_epochs, newer_epochs = target_epochs, sibling_epochs
        elif target_detail.get("baseline") == sibling_detail.get("current"):
            direction = "older"
            older_epochs, newer_epochs = sibling_epochs, target_epochs
        else:
            ok = False
            entries.append(
                {
                    "analysisId": sibling_id,
                    "direction": "unrelated",
                    "verified": False,
                    "evidenceLevel": "none",
                    "matchedFields": [],
                    "detail": "the list names a continuation that shares no epoch selector",
                }
            )
            continue
        older_current = older_epochs.get("CURRENT")
        newer_baseline = newer_epochs.get("BASELINE")
        if older_current is None or newer_baseline is None:
            # The other pair has not produced epoch records yet (not started or
            # not inspected). The shared-epoch claim is still verifiable at the
            # selector level, which is exactly what the list hint asserts, so
            # this is not a failure.
            entries.append(
                {
                    "analysisId": sibling_id,
                    "direction": direction,
                    "verified": True,
                    "evidenceLevel": "selector",
                    "matchedFields": ["selector"],
                    "detail": "shared epoch verified by selector; the other pair has "
                    "no epoch records yet",
                }
            )
            continue
        verified, matched, mismatched, per_execution = _verify_continuation_pair(
            older_epochs, newer_epochs
        )
        if not verified:
            ok = False
        entries.append(
            {
                "analysisId": sibling_id,
                "direction": direction,
                "verified": verified,
                "evidenceLevel": "observation",
                "matchedFields": matched,
                "perExecutionFieldsEqual": per_execution,
                "detail": "re-derived from EPOCH_IDENTITY"
                if verified
                else f"unverifiable: {', '.join(mismatched)}",
            }
        )
    if not entries:
        record = CheckRecord("continuation", STATUS_PASS, "no continuations named by either list")
    elif ok:
        levels = sorted({str(entry.get("evidenceLevel")) for entry in entries})
        record = CheckRecord(
            "continuation",
            STATUS_PASS,
            f"{len(entries)} continuation(s) independently re-derived from the "
            f"immutable records [evidenceLevel={_short(levels)}]",
        )
    else:
        record = CheckRecord(
            "continuation",
            STATUS_FAIL,
            "a list-named continuation cannot be verified from the immutable records",
        )
    return record, entries


def _check_coverage_resource(inputs: ComparisonInputs) -> CheckRecord:
    coverage = inputs.coverage
    if not isinstance(coverage, dict):
        # No coverage resource exists when Core withheld the numeric result:
        # that is a coherent state, not an unreadable resource.
        result = inputs.http_detail.get("result")
        if not isinstance(result, dict):
            return CheckRecord(
                "coverage-resource",
                STATUS_SKIPPED,
                f"no coverage resource for an analysis without a numeric result; "
                f"{_withheld_result_note(inputs)}",
            )
        return CheckRecord("coverage-resource", STATUS_FAIL, "coverage resource unreadable")
    problems: list[str] = []
    for field_name in (
        "totalLengthBytes",
        "rangeStart",
        "rangeEnd",
        "contentLengthBytes",
        "receivedBytes",
    ):
        if type(coverage.get(field_name)) is not int:
            problems.append(f"{field_name} missing")
    digest = coverage.get("digest")
    if not _nonempty_string(digest):
        problems.append("coverage digest metadata missing")
    if not problems:
        start = coverage["rangeStart"]
        end = coverage["rangeEnd"]
        total = coverage["totalLengthBytes"]
        length = coverage["contentLengthBytes"]
        received = coverage["receivedBytes"]
        if length != end - start + 1:
            problems.append("Content-Length differs from range metadata")
        if received != length:
            problems.append("received bytes differ from Content-Length")
        full = coverage.get("fullFetch") is True
        if full and (start != 0 or end != total - 1 or received != total):
            problems.append("whole-resource fetch is incomplete")
    summary = (
        f"total={_short(coverage.get('totalLengthBytes'))} "
        f"range={_short(coverage.get('rangeStart'))}-{_short(coverage.get('rangeEnd'))} "
        f"digest={_short(digest)}"
    )
    if problems:
        return CheckRecord("coverage-resource", STATUS_FAIL, "; ".join(problems) + f" [{summary}]")
    return CheckRecord("coverage-resource", STATUS_PASS, f"range bytes consistent [{summary}]")


def _check_http_list(inputs: ComparisonInputs) -> CheckRecord:
    items = inputs.http_list_items
    if not isinstance(items, list):
        return CheckRecord("http-list", STATUS_FAIL, "HTTP list unreadable")
    target_item = None
    for item in items:
        if isinstance(item, dict) and item.get("analysisId") == inputs.analysis_id:
            target_item = item
            break
    if target_item is None:
        return CheckRecord("http-list", STATUS_FAIL, "target analysis absent from HTTP list")
    # The list item and the detail are two projections of one record: a
    # consumer must be able to reconcile them without trusting either.
    detail = inputs.http_detail
    result = detail.get("result")
    result_metrics = result.get("metrics") if isinstance(result, dict) else None
    result_id = result.get("resultId") if isinstance(result, dict) else None
    result_codes = result.get("limitationCodes") if isinstance(result, dict) else None
    blockers = detail.get("blockers")
    blocker_count = len(blockers) if isinstance(blockers, list) else 0
    expected_limitation_count = blocker_count + (
        len(result_codes) if isinstance(result_codes, list) else 0
    )
    problems: list[str] = []
    for field_name in ("executionState", "suitabilityState", "createdAt"):
        if target_item.get(field_name) != detail.get(field_name):
            problems.append(f"list {field_name} differs from detail {field_name}")
    if target_item.get("resultId") != result_id:
        problems.append("list resultId differs from detail result identity")
    if target_item.get("metrics") != result_metrics:
        problems.append("list metrics differ from detail result metrics")
    if target_item.get("limitationCount") != expected_limitation_count:
        problems.append("list limitationCount is not blockers plus result limitation codes")
    summary = (
        f"{len(items)} list item(s); target present; "
        f"executionState={_short(target_item.get('executionState'))} "
        f"limitationCount={_short(target_item.get('limitationCount'))}"
    )
    if problems:
        return CheckRecord("http-list", STATUS_FAIL, "; ".join(problems) + f" [{summary}]")
    return CheckRecord("http-list", STATUS_PASS, f"list item and detail reconcile [{summary}]")


def _check_mcp_parity(inputs: ComparisonInputs) -> CheckRecord:
    if (
        inputs.mcp_detail is None
        and inputs.mcp_result is None
        and inputs.mcp_evidence_items is None
        and inputs.mcp_list_items is None
    ):
        return CheckRecord(
            "mcp-parity", STATUS_SKIPPED, "MCP path not supplied (--mcp-token-file omitted)"
        )
    problems: list[str] = []
    if inputs.mcp_detail is None or inputs.mcp_detail != inputs.http_detail:
        problems.append("ksi_get_analysis differs from HTTP detail")
    if inputs.mcp_result is None or inputs.mcp_result != inputs.http_detail:
        problems.append("ksi_get_analysis_result differs from HTTP detail")
    if inputs.mcp_evidence_items is None or inputs.mcp_evidence_items != inputs.http_evidence_items:
        problems.append("ksi_get_analysis_evidence differs from HTTP evidence")
    if inputs.mcp_list_items is None or inputs.mcp_list_items != inputs.http_list_items:
        problems.append("ksi_list_analyses differs from HTTP list")
    if problems:
        return CheckRecord("mcp-parity", STATUS_FAIL, "; ".join(problems))
    return CheckRecord(
        "mcp-parity", STATUS_PASS, "MCP projections equal HTTP projections item-for-item"
    )


def evaluate_contract(inputs: ComparisonInputs) -> tuple[list[CheckRecord], list[dict[str, Any]]]:
    """Cross-check every named element; pure over already-fetched plain JSON."""
    checks = [
        _check_numeric(inputs),
        _check_region(inputs),
        _check_input_version(inputs),
        _check_calculation_settings(inputs),
        _check_valid_region(inputs),
        _check_quality(inputs),
        _check_limitations(inputs),
    ]
    continuation, entries = _check_continuation(inputs)
    checks.append(continuation)
    checks.append(_check_coverage_resource(inputs))
    checks.append(_check_http_list(inputs))
    checks.append(_check_mcp_parity(inputs))
    assert [check.id for check in checks] == list(CHECK_IDS)
    return checks, entries


def project_list_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project list items to the compared fields only (safe identifiers/numbers)."""
    projected: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        projected.append(
            {
                "analysisId": item.get("analysisId"),
                "resultId": item.get("resultId"),
                "metrics": item.get("metrics"),
                "limitationCount": item.get("limitationCount"),
                "newerSiblingAnalysisIds": list(item.get("newerSiblingAnalysisIds") or []),
            }
        )
    return projected


# -- HTTP consumption (GET only) --------------------------------------------


def _validate_origin(value: str) -> str:
    if not isinstance(value, str) or any(ord(char) <= 32 for char in value):
        raise ValueError("Core origin must be HTTP(S) without whitespace")
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        raise ValueError("Core origin must be HTTP(S) without credentials") from None
    if (
        url.scheme not in ("http", "https")
        or not url.host
        or url.userinfo
        or url.query
        or url.fragment
    ):
        raise ValueError("Core origin must be HTTP(S) without credentials")
    return value.rstrip("/")


def _validate_identifier(value: str, field: str) -> str:
    # Same path-safe grammar as the repo customer example; stdlib + httpx only.
    if not isinstance(value, str) or _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must be a path-safe identifier")
    return value


def _validate_timeout(value: object) -> float:
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError("timeout must be finite and positive") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("timeout must be finite and positive")
    return seconds


def _validate_max_pages(value: object) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise ValueError("max pages must be a positive integer")
    if not 1 <= value <= _MAX_PAGES:
        raise ValueError("max pages must be a positive integer")
    return value


def _resolve_token(argument: str | None) -> str:
    raw = argument if argument is not None else os.environ.get("KSI_CUSTOMER_TOKEN")
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or any(ord(char) < 33 or ord(char) > 126 for char in raw.strip())
    ):
        raise _Failure("TOKEN_UNAVAILABLE")
    return raw.strip()


class _CoreReader:
    """GET-only Core consumer; failures map to fixed closed codes."""

    def __init__(self, origin: str, token: str, timeout_seconds: float) -> None:
        self._client = httpx.Client(
            base_url=origin,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
            timeout=timeout_seconds,
            trust_env=False,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> httpx.Response:
        try:
            response = self._client.get(path, params=params, headers=extra_headers)
        except httpx.HTTPError:
            raise _Failure("CORE_UNAVAILABLE") from None
        if response.status_code in (401, 403):
            raise _Failure("TOKEN_UNAVAILABLE")
        if response.status_code == 404:
            raise _Failure("INVALID_IDENTIFIER")
        if response.status_code not in expected:
            raise _Failure("CORE_UNAVAILABLE")
        return response

    def _json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            payload = self._get(path, params=params).json()
        except _Failure:
            raise
        except ValueError:
            raise _Failure("INVALID_RESPONSE") from None
        if not isinstance(payload, dict):
            raise _Failure("INVALID_RESPONSE")
        return payload

    def get_detail(self, site_id: str, analysis_id: str) -> dict[str, Any]:
        payload = self._json(f"/v2/sites/{site_id}/analyses/{analysis_id}")
        for key in ("analysisId", "siteId", "baseline", "current", "blockers"):
            if key not in payload:
                raise _Failure("INVALID_RESPONSE")
        if payload.get("analysisId") != analysis_id or payload.get("siteId") != site_id:
            raise _Failure("INVALID_RESPONSE")
        return payload

    def get_evidence_items(
        self, site_id: str, analysis_id: str, *, max_pages: int
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"limit": _EVIDENCE_PAGE_LIMIT}
            if cursor is not None:
                params["cursor"] = cursor
            page = self._json(f"/v2/sites/{site_id}/analyses/{analysis_id}/evidence", params=params)
            chunk = page.get("items")
            if not isinstance(chunk, list) or any(not isinstance(i, dict) for i in chunk):
                raise _Failure("INVALID_RESPONSE")
            items.extend(chunk)
            cursor = page.get("nextCursor")
            if cursor is None:
                return items
            if not isinstance(cursor, str) or not cursor:
                raise _Failure("INVALID_RESPONSE")
        raise _Failure("INVALID_RESPONSE")

    def get_list_items(self, site_id: str, *, max_pages: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"limit": _LIST_PAGE_LIMIT}
            if cursor is not None:
                params["cursor"] = cursor
            page = self._json(f"/v2/sites/{site_id}/analyses", params=params)
            chunk = page.get("items")
            if not isinstance(chunk, list) or any(not isinstance(i, dict) for i in chunk):
                raise _Failure("INVALID_RESPONSE")
            items.extend(chunk)
            cursor = page.get("nextCursor")
            if cursor is None:
                return items
            if not isinstance(cursor, str) or not cursor:
                raise _Failure("INVALID_RESPONSE")
        raise _Failure("INVALID_RESPONSE")

    def get_coverage(self, site_id: str, analysis_id: str) -> dict[str, Any]:
        """Fetch the coverage byte resource with Range requests; bytes never interpreted."""

        def ranged(start: int, end: int) -> httpx.Response:
            try:
                response = self._client.get(
                    f"/v2/sites/{site_id}/analyses/{analysis_id}/coverage",
                    headers={"Range": f"bytes={start}-{end}"},
                )
            except httpx.HTTPError:
                raise _Failure("CORE_UNAVAILABLE") from None
            if response.status_code in (401, 403):
                raise _Failure("TOKEN_UNAVAILABLE")
            if response.status_code == 404:
                raise _Failure("INVALID_IDENTIFIER")
            if response.status_code != 206:
                raise _Failure("INVALID_RESPONSE")
            return response

        def metadata(response: httpx.Response) -> tuple[int, int, int, str]:
            match = _CONTENT_RANGE.fullmatch(response.headers.get("content-range", ""))
            length_text = response.headers.get("content-length", "")
            if match is None or not length_text.isdecimal():
                raise _Failure("INVALID_RESPONSE")
            digest = response.headers.get("x-ksi-coverage-digest", "")
            if not digest:
                raise _Failure("INVALID_RESPONSE")
            return int(match.group(1)), int(match.group(2)), int(match.group(3)), digest

        first = ranged(0, 0)
        start, end, total, digest = metadata(first)
        if (start, end) != (0, 0) or total < 1:
            raise _Failure("INVALID_RESPONSE")
        if total <= _COVERAGE_RANGE_BYTES:
            whole = ranged(0, total - 1)
            start, end, total_check, digest_check = metadata(whole)
            if total_check != total or digest_check != digest:
                raise _Failure("INVALID_RESPONSE")
            return {
                "totalLengthBytes": total,
                "rangeStart": start,
                "rangeEnd": end,
                "contentLengthBytes": int(whole.headers.get("content-length", "-1")),
                "receivedBytes": len(whole.content),
                "digest": digest,
                "fullFetch": True,
            }
        return {
            "totalLengthBytes": total,
            "rangeStart": start,
            "rangeEnd": end,
            "contentLengthBytes": int(first.headers.get("content-length", "-1")),
            "receivedBytes": len(first.content),
            "digest": digest,
            "fullFetch": False,
        }


# -- MCP consumption (official SDK stdio adapter; mcp imported lazily) --------


async def _fetch_mcp(
    *,
    core_origin: str,
    token_file: str,
    site_id: str,
    analysis_id: str,
    timeout_seconds: float,
    max_pages: int,
) -> dict[str, Any]:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    repo_root = Path(__file__).resolve().parents[1]
    adapter_src = repo_root / "services" / "analysis-mcp" / "src"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"}
    }
    env["PYTHONPATH"] = str(adapter_src) + os.pathsep + env.get("PYTHONPATH", "")
    env["KSI_ANALYSIS_MCP_CORE_ORIGIN"] = core_origin
    env["KSI_ANALYSIS_MCP_TOKEN_FILE"] = token_file
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ksi_analysis_mcp.server"],
        env=env,
    )
    budget = min(timeout_seconds * (4 + 2 * max_pages), 900.0)

    async def call(
        session: ClientSession, name: str, arguments: dict[str, Any], remaining: float
    ) -> dict[str, Any]:
        try:
            result = await asyncio.wait_for(session.call_tool(name, arguments), timeout=remaining)
        except TimeoutError:
            raise _Failure("MCP_UNAVAILABLE") from None
        if getattr(result, "is_error", True):
            raise _Failure("MCP_UNAVAILABLE")
        content = getattr(result, "structured_content", None)
        if not isinstance(content, dict):
            raise _Failure("MCP_UNAVAILABLE")
        return content

    try:
        async with asyncio.timeout(budget):
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    loop = asyncio.get_running_loop()
                    deadline = loop.time() + budget

                    def remaining() -> float:
                        return max(deadline - loop.time(), 0.01)

                    await asyncio.wait_for(session.initialize(), timeout=remaining())
                    base = {"siteId": site_id, "analysisId": analysis_id}
                    mcp_detail = await call(session, "ksi_get_analysis", dict(base), remaining())
                    mcp_result = await call(
                        session, "ksi_get_analysis_result", dict(base), remaining()
                    )
                    evidence_items: list[dict[str, Any]] = []
                    cursor: str | None = None
                    for _ in range(max_pages):
                        args: dict[str, Any] = {
                            "siteId": site_id,
                            "analysisId": analysis_id,
                            "limit": _EVIDENCE_PAGE_LIMIT,
                        }
                        if cursor is not None:
                            args["cursor"] = cursor
                        page = await call(session, "ksi_get_analysis_evidence", args, remaining())
                        chunk = page.get("items")
                        if not isinstance(chunk, list):
                            raise _Failure("INVALID_RESPONSE")
                        evidence_items.extend(chunk)
                        cursor = page.get("nextCursor")
                        if cursor is None:
                            break
                    else:
                        raise _Failure("INVALID_RESPONSE")
                    list_items: list[dict[str, Any]] = []
                    cursor = None
                    for _ in range(max_pages):
                        list_args: dict[str, Any] = {"siteId": site_id, "limit": _LIST_PAGE_LIMIT}
                        if cursor is not None:
                            list_args["cursor"] = cursor
                        page = await call(session, "ksi_list_analyses", list_args, remaining())
                        chunk = page.get("items")
                        if not isinstance(chunk, list):
                            raise _Failure("INVALID_RESPONSE")
                        list_items.extend(chunk)
                        cursor = page.get("nextCursor")
                        if cursor is None:
                            break
                    else:
                        raise _Failure("INVALID_RESPONSE")
    except _Failure:
        raise
    except (TimeoutError, Exception):
        raise _Failure("MCP_UNAVAILABLE") from None
    for payload in (mcp_detail, mcp_result):
        if payload.get("siteId") != site_id or payload.get("analysisId") != analysis_id:
            raise _Failure("INVALID_RESPONSE")
    return {
        "detail": mcp_detail,
        "result": mcp_result,
        "evidenceItems": evidence_items,
        "listItems": list_items,
    }


# -- CLI ----------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = _ClosedParser(description=__doc__)
    parser.add_argument("--core-origin", required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--analysis-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--token", default=None)
    parser.add_argument("--mcp-token-file", default=None)
    parser.add_argument("--mcp-core-origin", default=None)
    parser.add_argument("--timeout-seconds", default=30.0)
    parser.add_argument("--max-pages", default=8)
    args = parser.parse_args(argv)
    try:
        args.timeout_seconds = _validate_timeout(args.timeout_seconds)
        args.max_pages = _validate_max_pages(int(args.max_pages))
    except (TypeError, ValueError):
        parser.error("timeout/pages invalid")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)
    try:
        core_origin = _validate_origin(args.core_origin)
        site_id = _validate_identifier(args.site_id, "site_id")
        analysis_id = _validate_identifier(args.analysis_id, "analysis_id")
        token = _resolve_token(args.token)
        if not isinstance(args.out, str) or not args.out.strip():
            raise ValueError("output path is required")
        out_path = Path(args.out)
        mcp_token_file = args.mcp_token_file
        if mcp_token_file is not None and (
            not isinstance(mcp_token_file, str) or not Path(mcp_token_file).is_absolute()
        ):
            raise ValueError("MCP token file path must be absolute")
        mcp_origin = _validate_origin(args.mcp_core_origin or args.core_origin)
        timeout_seconds: float = args.timeout_seconds
        max_pages: int = args.max_pages
    except ValueError:
        print(f"{TOOL_NAME}: INVALID_IDENTIFIER", file=sys.stderr)
        return 2
    except _Failure as exc:
        print(f"{TOOL_NAME}: {exc.code}", file=sys.stderr)
        return 2

    reader = _CoreReader(core_origin, token, timeout_seconds)
    try:
        try:
            http_detail = reader.get_detail(site_id, analysis_id)
            http_evidence_items = reader.get_evidence_items(
                site_id, analysis_id, max_pages=max_pages
            )
            http_list_items = reader.get_list_items(site_id, max_pages=max_pages)
        except _Failure as exc:
            print(f"{TOOL_NAME}: {exc.code}", file=sys.stderr)
            return 2
        named: set[str] = set()
        for item in http_list_items:
            if not isinstance(item, dict):
                continue
            siblings_hint = item.get("newerSiblingAnalysisIds")
            if not isinstance(siblings_hint, list):
                continue
            hinted = [str(v) for v in siblings_hint if isinstance(v, str)]
            if item.get("analysisId") == analysis_id:
                # The target's own list entry names analyses that continue it.
                named.update(hinted)
            elif analysis_id in siblings_hint:
                # An older entry names the target as its continuation.
                item_id = item.get("analysisId")
                if isinstance(item_id, str):
                    named.add(item_id)
        named_continuations = sorted(named)
        siblings: dict[str, dict[str, Any]] = {}
        for sibling_id in named_continuations:
            try:
                sibling_detail = reader.get_detail(site_id, sibling_id)
                sibling_items = reader.get_evidence_items(site_id, sibling_id, max_pages=max_pages)
            except _Failure as exc:
                if exc.code in ("INVALID_IDENTIFIER", "INVALID_RESPONSE"):
                    continue
                print(f"{TOOL_NAME}: {exc.code}", file=sys.stderr)
                return 2
            siblings[sibling_id] = {
                "detail": sibling_detail,
                "evidenceItems": sibling_items,
            }
        coverage: dict[str, Any] | None = None
        result = http_detail.get("result")
        if isinstance(result, dict) and http_detail.get("coverageHref"):
            try:
                coverage = reader.get_coverage(site_id, analysis_id)
            except _Failure as exc:
                print(f"{TOOL_NAME}: {exc.code}", file=sys.stderr)
                return 2
        mcp_bundle: dict[str, Any] | None = None
        if mcp_token_file is not None:
            try:
                mcp_bundle = asyncio.run(
                    _fetch_mcp(
                        core_origin=mcp_origin,
                        token_file=mcp_token_file,
                        site_id=site_id,
                        analysis_id=analysis_id,
                        timeout_seconds=timeout_seconds,
                        max_pages=max_pages,
                    )
                )
            except _Failure as exc:
                print(f"{TOOL_NAME}: {exc.code}", file=sys.stderr)
                return 2
    finally:
        reader.close()

    inputs = ComparisonInputs(
        site_id=site_id,
        analysis_id=analysis_id,
        http_detail=http_detail,
        http_evidence_items=http_evidence_items,
        http_list_items=http_list_items,
        named_continuations=named_continuations,
        siblings=siblings,
        coverage=coverage,
        mcp_detail=mcp_bundle["detail"] if mcp_bundle else None,
        mcp_result=mcp_bundle["result"] if mcp_bundle else None,
        mcp_evidence_items=mcp_bundle["evidenceItems"] if mcp_bundle else None,
        mcp_list_items=mcp_bundle["listItems"] if mcp_bundle else None,
    )
    checks, continuations = evaluate_contract(inputs)
    http_projected = project_list_items(http_list_items)
    mcp_projected = project_list_items(mcp_bundle["listItems"]) if mcp_bundle is not None else None
    record = {
        "tool": TOOL_NAME,
        "coreOrigin": core_origin,
        "siteId": site_id,
        "analysisId": analysis_id,
        "mcpUsed": mcp_bundle is not None,
        "checks": [check.to_dict() for check in checks],
        "continuations": continuations,
        "lists": {
            "http": http_projected,
            "mcp": mcp_projected,
            "agree": (mcp_projected == http_projected) if mcp_projected is not None else None,
        },
        "coverage": coverage,
        "notes": (
            "Two projections of one Core record; PASS proves presentation agreement only, "
            "not field accuracy, customer acceptance, or settlement fitness."
        ),
    }
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        print(f"{TOOL_NAME}: PERSIST_FAILED", file=sys.stderr)
        return 2
    counts = {STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_SKIPPED: 0}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    print(
        f"{TOOL_NAME}: {counts[STATUS_PASS]} PASS, {counts[STATUS_FAIL]} FAIL, "
        f"{counts[STATUS_SKIPPED]} SKIPPED -> {out_path}"
    )
    return 0 if counts[STATUS_FAIL] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
