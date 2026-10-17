"""Practical synthetic operator-journey seed (isolated 8096 demo, NOT F03).

Fresh synthetic Site for UX end-to-end (UX task authorized 2026-10-18):
  site 'syn-demo-site-01' ('시연 · 토공 현장')
  work areas '북측 절토구역' (north, primary demo pair)
    + '남측 성토구역' (south, third pair files only)
  two sealed epochs on the north area with real georeferenced DSM+ortho bytes:
    '10월5일 기준 촬영'  (2026-10-05) and '10월12일 비교 촬영' (2026-10-12)

Flow per epoch: work order (EXTERNAL_RECONSTRUCTION) -> register candidate
(client canonical digest) -> upload grants -> PUT bytes -> seal.
Then admits one regular signed validation policy scoped to exactly the two
sealed subjects in this isolated synthetic-data fixture, and reloads the
authority snapshot (existing reload API). The syntheticTestOnly wire flag is
NOT a dataset marker and stays false here because the provider reload path
only admits non-synthetic policies; this is not a production/customer
approval. Synthetic marking lives in producer declarations, subject/site
names and the syn- policy/site/submission ids instead.

SYNTHETIC provenance throughout: producer declarations name this rehearsal,
no customer/vendor branding, no Terra/license/export claim, no accuracy claim.
V2 analysis + review steps run only after the worker loop reports MEASURED;
use --skip-analysis/--skip-review as needed. Third south pair stays files-only
for the browser UI flow (never registered here).

Usage:
  uv run --locked python scripts/rehearse_operator_journey.py \\
    --core-url http://127.0.0.1:8096 --operator-token-file <path> \\
    --provider-dir <isolated-provider-config-dir> \\
    --policy-template-file <isolated-policy-template.json> \\
    --core-data-dir <isolated-core-data-dir> \\
    --out-dir /tmp/opencode/ksi-practical-journey-20261018/receipts
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np

REPO = Path(__file__).resolve().parents[1]
for extra in (
    REPO / "services/core/src",
    REPO / "packages/domain/src",
    REPO / "packages/event-contracts/src",
    REPO / "packages/geo-core/src",
    REPO / "packages/geo-spatial/src",
    REPO / "tests",
    REPO / "tests/contract",
):
    sys.path.insert(0, str(extra))

SITE_ID = "syn-demo-site-01"
SITE_NAME = "시연 · 토공 현장"
AREA_NORTH_NAME = "북측 절토구역"
AREA_SOUTH_NAME = "남측 성토구역"
ORG = "org-a"
CRS = "EPSG:5186"
N = 32
X0, Y0, PIX = 200000.0, 550000.0, 1.0

# This rehearsal speaks to exactly one isolated loopback Core. Anything else
# (remote hosts, other ports such as the F03 8092 or 8061/8062 rigs, https,
# embedded credentials, URL paths) is rejected before any network call so an
# accidental production/F03 target can never receive seed writes.
ALLOWED_CORE_PORT = 8096
ALLOWED_CORE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class AreaAmbiguityError(ValueError):
    """Refusal to guess between same-named areas or reuse a dead receipt."""


def validate_core_url(value: str) -> str:
    """Allow only the isolated loopback rehearsal Core; reject everything else."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise ValueError(f"refusing core-url {value!r}: unparsable") from exc
    if parts.scheme != "http":
        raise ValueError(f"refusing core-url {value!r}: scheme must be http")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"refusing core-url {value!r}: credentials are forbidden")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_CORE_HOSTS:
        raise ValueError(f"refusing core-url {value!r}: host must be loopback")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"refusing core-url {value!r}: bad port") from exc
    if port != ALLOWED_CORE_PORT:
        raise ValueError(
            f"refusing core-url {value!r}: port must be {ALLOWED_CORE_PORT} "
            "(protected rigs such as 8092/8061/8062 are never seed targets)"
        )
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError(f"refusing core-url {value!r}: path/query/fragment forbidden")
    return value


def decide_area(existing: list, *, receipt_id: str | None, name: str) -> tuple[str, str | None]:
    """Pure work-area choice: ('reuse', id) or ('create', None). Never archives.

    Names are not unique by contract, so a name alone never authorizes cleanup:
    with zero active matches we create, with exactly one we reuse it, and with
    several we raise AreaAmbiguityError instead of guessing or archiving.
    A persisted receipt id wins when it names a live area; a receipt naming an
    archived/missing area is a hard error, not a cue to clean up.
    """
    by_id = {a.get("workAreaId"): a for a in existing if a.get("workAreaId")}
    if receipt_id is not None:
        hit = by_id.get(receipt_id)
        if hit is None:
            raise AreaAmbiguityError(
                f"persisted receipt area {receipt_id!r} is unknown to the Core; "
                "remove the stale receipt or restore the area, refusing to guess"
            )
        if hit.get("status", "ACTIVE") != "ACTIVE":
            raise AreaAmbiguityError(
                f"persisted receipt area {receipt_id!r} is {hit.get('status')}; "
                "refusing to reuse or repair it automatically"
            )
        return "reuse", receipt_id
    live = sorted(
        (a for a in existing if a.get("name") == name and a.get("status", "ACTIVE") == "ACTIVE"),
        key=lambda a: a.get("workAreaId") or "",
    )
    if not live:
        return "create", None
    if len(live) > 1:
        ids = ", ".join(a.get("workAreaId", "?") for a in live)
        raise AreaAmbiguityError(
            f"{len(live)} active areas share name {name!r} ({ids}); "
            "refusing to pick or archive by name alone"
        )
    return "reuse", live[0]["workAreaId"]


def canonical_digest(candidate: dict) -> str:
    body = {k: v for k, v in candidate.items() if k != "submissionDigest"}
    body["artifacts"] = sorted(body["artifacts"], key=lambda a: a["artifactId"])
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )


def south_polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [X0, Y0 - 2 * N * PIX],
                [X0 + N * PIX, Y0 - 2 * N * PIX],
                [X0 + N * PIX, Y0 - N * PIX],
                [X0, Y0 - N * PIX],
                [X0, Y0 - 2 * N * PIX],
            ]
        ],
    }


def south_footprint_bbox() -> tuple[float, float, float, float]:
    """(minx, miny, maxx, maxy) of the south work area in EPSG:5186 metres."""
    return (X0, Y0 - 2 * N * PIX, X0 + N * PIX, Y0 - N * PIX)


def south_pair_readme(area_id: str) -> dict:
    minx, miny, maxx, maxy = south_footprint_bbox()
    return {
        "purpose": "Third material pair for browser UI upload flow (files only, not registered).",
        "workArea": area_id,
        "workAreaName": AREA_SOUTH_NAME,
        "crs": CRS,
        "footprint": {
            "minx": minx,
            "miny": miny,
            "maxx": maxx,
            "maxy": maxy,
        },
        "captureSoftware": "SYNTHETIC demo raster writer (practical journey)",
        "captureWindows": [
            "2026-10-05T09:00:00Z/2026-10-05T09:30:00Z",
            "2026-10-12T09:00:00Z/2026-10-12T09:30:00Z",
        ],
        "files": [
            "syn-south-t0-dsm.tif",
            "syn-south-t0-ortho.tif",
            "syn-south-t1-dsm.tif",
            "syn-south-t1-ortho.tif",
        ],
        "note": "New UI registrations create new subjects; inspection admission is "
        "per-subject admin action (typed INSPECTION_PENDING_POLICY until admitted).",
    }


def geotiffs(y_origin: float = Y0) -> tuple[bytes, bytes, bytes, bytes]:
    from affine import Affine
    from rasterio.crs import CRS as RC
    from rasterio.io import MemoryFile

    transform = Affine(PIX, 0.0, X0, 0.0, -PIX, y_origin)
    base = np.full((N, N), 100.0, dtype=np.float64)
    cut = base.copy()
    cut[8:24, 8:24] -= 0.5
    dsms = []
    for values in (base, cut):
        with MemoryFile() as mem:
            with mem.open(
                driver="GTiff",
                width=N,
                height=N,
                count=1,
                dtype="float64",
                crs=RC.from_user_input("EPSG:5186+5773"),
                transform=transform,
            ) as ds:
                ds.write(values, 1)
            dsms.append(mem.read())
    orthos = []
    for fill in (110, 150):
        rgb = np.stack(
            [
                np.full((N, N), fill, np.uint8),
                np.full((N, N), 120, np.uint8),
                np.full((N, N), 90, np.uint8),
            ]
        )
        with MemoryFile() as mem:
            with mem.open(
                driver="GTiff",
                width=N,
                height=N,
                count=3,
                dtype="uint8",
                crs=RC.from_user_input("EPSG:5186"),
                transform=transform,
                photometric="RGB",
            ) as ds:
                ds.write(rgb)
            orthos.append(mem.read())
    return dsms[0], orthos[0], dsms[1], orthos[1]


def artifact_row(kind: str, data: bytes, fname: str) -> dict:
    return {
        "artifactId": kind,
        "kind": kind,
        "fileName": fname,
        "format": "GeoTIFF",
        "contentType": "application/octet-stream",
        "declaredSha256": hashlib.sha256(data).hexdigest(),
        "declaredSizeBytes": len(data),
        "declaredCrs": CRS,
        "declaredVerticalReference": None,
        "declaredGsdM": None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--core-url", default="http://127.0.0.1:8096")
    ap.add_argument("--operator-token-file", required=True, type=Path)
    ap.add_argument(
        "--provider-dir",
        required=True,
        type=Path,
        help="Fresh provider bundle dir (signer + snapshot live here)",
    )
    ap.add_argument(
        "--policy-template-file",
        required=True,
        type=Path,
        help="Read-only inspector-fact template (parser/grammar/envelope)",
    )
    ap.add_argument(
        "--core-data-dir",
        required=True,
        type=Path,
        help="Isolated Core data dir holding the owner journals (read for planning)",
    )
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--skip-analysis", action="store_true")
    ap.add_argument("--skip-review", action="store_true")
    args = ap.parse_args()
    try:
        validate_core_url(args.core_url)
    except ValueError as exc:
        print(f"core-url guard: {exc}", file=sys.stderr)
        return 2

    token = args.operator_token_file.read_text().strip()
    if not token:
        print("empty operator token file", file=sys.stderr)
        return 1
    H = {"Authorization": f"Bearer {token}"}
    client = httpx.Client(base_url=args.core_url, timeout=60)
    out: dict = {"site": SITE_ID, "epochs": {}}

    me = client.get("/v1/auth/whoami", headers=H)
    print("whoami", me.status_code, me.text[:160])
    if me.status_code != 200:
        return 1

    site = client.post(
        "/v1/sites",
        headers={**H, "Idempotency-Key": "syn-demo-site-1"},
        json={
            "siteId": SITE_ID,
            "name": SITE_NAME,
            "siteFrame": {
                "crs": CRS,
                "verticalDatum": "EGM96 height",
                "unit": "meter",
                "transformVersion": "fixture-v1",
            },
        },
    )
    print("site", site.status_code, site.text[:200])
    if site.status_code not in (200, 201, 409):
        return 1

    def north_polygon() -> dict:
        x1, y1 = X0, Y0 - N * PIX
        x2, y2 = X0 + N * PIX, Y0
        ring = [[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]]
        return {"type": "Polygon", "coordinates": [ring]}

    area_ids: dict[str, str] = {}
    receipt: dict = {}
    receipt_path = args.out_dir / "syn-seed-summary.json"
    if receipt_path.is_file():
        try:
            receipt = json.loads(receipt_path.read_text()).get("areas", {})
        except (json.JSONDecodeError, AttributeError):
            receipt = {}
    for key, name in (("north", AREA_NORTH_NAME), ("south", AREA_SOUTH_NAME)):
        listed = client.get(f"/v1/sites/{SITE_ID}/work-areas", headers=H).json()["workAreas"]
        try:
            action, resolved = decide_area(listed, receipt_id=receipt.get(key), name=name)
        except AreaAmbiguityError as exc:
            print(f"area-{key}: {exc}", file=sys.stderr)
            return 2
        if action == "reuse":
            assert resolved is not None
            area_ids[key] = resolved
            print(f"area-{key} reuse", area_ids[key])
            continue
        poly = north_polygon() if key == "north" else south_polygon()
        r = client.post(
            f"/v1/sites/{SITE_ID}/work-areas",
            headers={**H, "Idempotency-Key": f"syn-demo-area-{key}"},
            json={"name": name, "polygon": poly, "crs": CRS},
        )
        print(f"area-{key}", r.status_code, r.text[:200])
        if r.status_code != 201:
            # Never adopt by name alone after a failed create: rerunning finds
            # the single created area (or reports ambiguity) via decide_area.
            print(
                f"area-{key}: create failed ({r.status_code}); rerun to reuse "
                "the created area or resolve the conflict",
                file=sys.stderr,
            )
            return 1
        body = r.json()
        area_ids[key] = body.get("workAreaId") or body["workArea"]["workAreaId"]
    out["areas"] = area_ids
    north = area_ids["north"]

    dsm0, ortho0, dsm1, ortho1 = geotiffs()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "syn-north-t0-dsm.tif").write_bytes(dsm0)
    (args.out_dir / "syn-north-t0-ortho.tif").write_bytes(ortho0)
    (args.out_dir / "syn-north-t1-dsm.tif").write_bytes(dsm1)
    (args.out_dir / "syn-north-t1-ortho.tif").write_bytes(ortho1)
    # Third pair: south-area files only (browser UI flow material, never
    # registered here). Translated a full tile south so the footprint matches
    # the south work area instead of repeating the north bytes.
    south = geotiffs(y_origin=Y0 - N * PIX)
    (args.out_dir / "syn-south-t0-dsm.tif").write_bytes(south[0])
    (args.out_dir / "syn-south-t0-ortho.tif").write_bytes(south[1])
    (args.out_dir / "syn-south-t1-dsm.tif").write_bytes(south[2])
    (args.out_dir / "syn-south-t1-ortho.tif").write_bytes(south[3])
    (args.out_dir / "syn-south-pair-readme.json").write_text(
        json.dumps(south_pair_readme(area_ids["south"]), ensure_ascii=False, indent=1)
    )

    specs = [
        ("t0", "2026-10-05T09:00:00Z", "2026-10-05T09:30:00Z", dsm0, ortho0, "10월5일 기준 촬영"),
        ("t1", "2026-10-12T09:00:00Z", "2026-10-12T09:30:00Z", dsm1, ortho1, "10월12일 비교 촬영"),
    ]
    for label, start, end, dsm, ortho, caption in specs:
        listed = client.get(f"/v1/sites/{SITE_ID}/observation-work-orders", headers=H).json()
        rows = listed.get("workOrders") or listed.get("orders") or []
        hit = next(
            (
                w
                for w in rows
                if caption in (w.get("name") or "") and (w.get("workAreaIds") or []) == [north]
            ),
            None,
        )
        if hit is not None:
            wid = hit["workOrderId"]
            print(f"{label} order reuse", wid)
        else:
            order = client.post(
                f"/v1/sites/{SITE_ID}/observation-work-orders",
                headers={**H, "Idempotency-Key": f"syn-demo-order-{label}-{north}"},
                json={
                    "name": f"시연 자료등록 {caption} (SYNTHETIC)",
                    "workAreaIds": [north],
                    "executionMode": "EXTERNAL_RECONSTRUCTION",
                },
            )
            print(f"{label} order", order.status_code, order.text[:160])
            if order.status_code != 201:
                return 1
            wid = order.json()["workOrderId"]
        ctx = client.get(
            f"/v1/observation-work-orders/{wid}/external-reconstruction-context", headers=H
        ).json()
        blobs = {"dsm": dsm, "ortho": ortho}
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        cand = {
            "contractVersion": "external-reconstruction-submission.v1",
            "submissionId": f"syn-demo-{label}-submission",
            "revision": 1,
            "organizationId": ORG,
            "siteId": SITE_ID,
            "observationEpochId": ctx["expectedEpochId"],
            "submittedAt": now,
            "submittedBy": "syn-operator",
            "executionResponsibility": "customer_operator",
            "executionLocus": "customer_workstation",
            "producerDeclaration": {
                "softwareName": "SYNTHETIC practical-journey raster writer",
                "softwareVersion": "0.0.1",
                "buildIdentifier": None,
                "producerRunIdentifier": None,
                "configurationDigest": None,
                "completedAt": None,
            },
            "inputDeclaration": {
                "rawMediaStoredByKsi": False,
                "originalRetentionLocus": "customer_workstation",
                "localInputManifestDigest": None,
                "imageCount": None,
                "captureStartedAt": start,
                "captureEndedAt": end,
            },
            "artifacts": [
                artifact_row("dsm", dsm, f"syn-north-{label}-dsm.tif"),
                artifact_row("ortho", ortho, f"syn-north-{label}-ortho.tif"),
            ],
        }
        cand["submissionDigest"] = canonical_digest(cand)
        reg = client.post(
            f"/v1/observation-work-orders/{wid}/external-reconstruction-submissions",
            headers=H,
            json=cand,
        )
        print(f"{label} register", reg.status_code, reg.text[:200])
        if reg.status_code == 201:
            ref = reg.json()["submissionRef"]
            sealed = False
        elif reg.status_code == 409:
            lst = client.get(
                f"/v1/observation-work-orders/{wid}/external-reconstruction-submissions", headers=H
            ).json()
            mine = next(
                s
                for s in lst["submissions"]
                if s["submission"].get("submissionId") == cand["submissionId"]
            )
            ref, sealed = mine["submissionRef"], mine["state"] == "SEALED"
            print(f"{label} register reuse", ref, mine["state"])
        else:
            return 1
        if not sealed:
            grants = client.post(
                f"/v1/observation-work-orders/{wid}/external-reconstruction-submissions/{ref}"
                "/revisions/1/upload-grants",
                headers=H,
            ).json()["grants"]
            for g in grants:
                put = client.put(
                    g["uploadUrl"], content=blobs[g["artifactId"]], headers=g["requiredHeaders"]
                )
                print(f"{label} put {g['artifactId']}", put.status_code)
                if put.status_code >= 300:
                    return 1
            seal = client.post(
                f"/v1/observation-work-orders/{wid}/external-reconstruction-submissions/{ref}"
                "/revisions/1/seal",
                headers=H,
            )
            print(f"{label} seal", seal.status_code, seal.text[:200])
            if seal.status_code != 200:
                return 1
            state = seal.json().get("state")
        else:
            print(f"{label} seal reuse (already SEALED)")
            state = "SEALED"
        out["epochs"][label] = {
            "workOrderId": wid,
            "submissionRef": ref,
            "caption": caption,
            "seal": state,
        }

    admit_rc = admit_policy(args, client, H, out)
    if admit_rc != 0:
        return admit_rc

    (args.out_dir / "syn-seed-summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1)
    )
    print("SUMMARY", json.dumps(out, ensure_ascii=False))

    if not args.skip_analysis:
        if not wait_measured(client, H, out):
            print("inspection did not reach MEASURED (worker loop must run first)", file=sys.stderr)
            return 2
        rc = post_analyses(client, H, out, args.skip_review)
        if rc != 0:
            return rc
        (args.out_dir / "syn-seed-summary.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1)
        )
        print("SUMMARY", json.dumps(out, ensure_ascii=False))
    return 0


def build_live_template(template_path: Path) -> dict:
    """Inspector facts from the real current parser/grammar (not a stale copy).

    parser_build_digest must match the inspector manifest the worker loop
    executes; grammar/envelope/rule facts mirror the proven rehearsal
    template (read-only data, no results). The template file is an explicit
    caller input (CLI --policy-template-file); there is no fallback path.
    """
    from analysis_api_local_fixture import _envelope
    from ksi_core.external_quantitative_authority import CompatibilityRuleDescriptorV1
    from ksi_processing_controller.external_geotiff_profile import (
        external_geotiff_profile_digest_v1,
    )
    from test_external_inspector_container_entrypoint import _manifest

    envelope = _envelope()
    # Superseded generations keep their QUEUED rows; the depth gate counts
    # every QUEUED row for the org, so leave headroom for rotations.
    envelope = envelope.model_copy(
        update={"max_queue_depth": 64, "resource_envelope_digest": None}
    ).sealed()
    manifest = _manifest(envelope)
    frozen = json.loads(template_path.read_text())
    return {
        "contractVersion": "external-validation-policy.v1",
        "parserBuildDigest": manifest.parser_build_digest,
        "grammarDigest": external_geotiff_profile_digest_v1(),
        "resourceEnvelope": envelope.model_dump(by_alias=True, mode="json"),
        "resourceEnvelopeDigest": envelope.resource_envelope_digest,
        "inspectionRuleIds": frozen["inspectionRuleIds"],
        "evidenceRuleIds": frozen["evidenceRuleIds"],
        "compatibilityMappingDigests": (CompatibilityRuleDescriptorV1().canonical_digest(),),
    }


def read_jsonl_rows(path: Path) -> list[dict]:
    """Owner journal read path (read-only). A missing file means no records."""
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def latest_policy_status(
    journal_rows: list[dict], policy_id: str, version: int
) -> tuple[str, dict | None]:
    """Latest lifecycle event for one policy identity from the owner journal.

    Returns ("admitted"|"revoked"|"superseded"|"absent", admitted_row_or_None).
    Later rows win; unknown kinds are ignored (never treated as admission).
    """
    status, row = "absent", None
    for entry in journal_rows:
        if not isinstance(entry, dict):
            continue
        if entry.get("policyId") != policy_id or entry.get("policyVersion") != version:
            continue
        kind = entry.get("kind")
        if kind == "external-validation-policy-admitted":
            status, row = "admitted", entry
        elif kind == "external-validation-policy-revoked":
            status, row = "revoked", None
        elif kind == "external-validation-policy-superseded":
            status, row = "superseded", None
    return status, row


def _record_subject_digests(record: dict) -> tuple[str, ...] | None:
    """Ordered canonical digests of a record's permitted subjects, or None."""
    from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1

    try:
        return tuple(
            SealedExternalSubjectV1.model_validate(item).canonical_digest()
            for item in record.get("permittedSubjects", [])
        )
    except (KeyError, TypeError, ValueError):
        return None


def plan_policy_admission(
    *,
    policy_id: str,
    version: int,
    body_digest: str,
    subjects: tuple,
    permitted_uses: tuple[str, ...],
    authorized_actor_ids: tuple[str, ...],
    synthetic_test_only: bool,
    journal_rows: list[dict],
    file_records: list[dict],
    file_current: list[str],
    now: datetime,
) -> tuple[str, str]:
    """Pure admission decision from owner journal + file mirror. No IO.

    Returns ("skip", reason) when the exact admitted record already covers the
    desired body/subjects/uses inside its real active window and the file
    mirror agrees; ("admit", reason) when nothing active covers it; and
    ("mismatch", actionable diagnostic) otherwise. Never invents a fresh
    same-version window and never claims a stale mirror is healthy.
    """
    wanted_subjects = tuple(s.canonical_digest() for s in subjects)
    status, row = latest_policy_status(journal_rows, policy_id, version)
    if status != "admitted" or not isinstance(row, dict):
        if status == "absent":
            return "admit", "no active admission recorded for this policy identity"
        return (
            "mismatch",
            f"configuration mismatch: latest journal event for {policy_id} v{version} "
            f"is {status}; refusing to re-admit or overwrite (explicit new version required)",
        )
    authority = row.get("authority")
    if not isinstance(authority, dict):
        return (
            "mismatch",
            "configuration mismatch: admitted journal row lacks authority payload",
        )
    if authority.get("syntheticTestOnly", None) is not synthetic_test_only:
        return (
            "mismatch",
            "configuration mismatch: admitted record syntheticTestOnly differs from desired",
        )
    if authority.get("authorizedPolicyBodyDigest") != body_digest:
        return (
            "mismatch",
            "configuration mismatch: live template body differs from the admitted record; "
            "re-admitting the same version would silently change coverage (bump VERSION "
            "explicitly with a reviewed change if intended), no reload attempted",
        )
    if tuple(authority.get("permittedUses", [])) != tuple(permitted_uses):
        return (
            "mismatch",
            "configuration mismatch: admitted permitted uses differ from desired; "
            "no reload attempted",
        )
    if tuple(authority.get("authorizedActorIds", [])) != tuple(authorized_actor_ids):
        return (
            "mismatch",
            "configuration mismatch: admitted authorized actors differ from desired; "
            "no reload attempted",
        )
    if _record_subject_digests(authority) != wanted_subjects:
        return (
            "mismatch",
            "configuration mismatch: admitted permitted subjects differ from the sealed pair "
            "(exact subject tuple required); no reload attempted",
        )
    try:
        active_from = datetime.fromisoformat(str(authority["activeFrom"]))
        active_until = datetime.fromisoformat(str(authority["activeUntil"]))
    except (KeyError, ValueError):
        return "mismatch", "configuration mismatch: admitted record window is unparsable"
    if not (active_from <= now < active_until):
        window = f"[{authority.get('activeFrom')} .. {authority.get('activeUntil')})"
        return (
            "mismatch",
            f"configuration mismatch: admitted record window {window} does not cover now; "
            "refusing to mint a fresh same-version window (explicit new version required), "
            "no reload attempted",
        )
    record_digest = authority.get("digest")
    mirror_hits = [
        r
        for r in file_records
        if isinstance(r, dict)
        and r.get("policyId") == policy_id
        and r.get("policyVersion") == version
        and r.get("digest") == record_digest
        and r.get("authorizedPolicyBodyDigest") == body_digest
    ]
    if not mirror_hits or record_digest not in (file_current or []):
        return (
            "mismatch",
            "configuration mismatch: file mirror does not carry the journal-admitted record "
            f"(admitted digest {str(record_digest)[:24]}... not current in provider snapshot); "
            "restore the mirror from the authorized journal receipt or admit a new version "
            "explicitly, no reload attempted",
        )
    return (
        "skip",
        f"identical policy body already admitted and current "
        f"(record {str(record_digest)[:24]}...); skipping reload",
    )


def admit_policy(args: argparse.Namespace, client: httpx.Client, H: dict, out: dict) -> int:
    """Admit one regular signed inspection policy for the two sealed synthetic subjects."""
    from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1

    template = build_live_template(args.policy_template_file)

    subjects = []
    for label in ("t0", "t1"):
        e = out["epochs"][label]
        view = client.get(
            f"/v1/observation-work-orders/{e['workOrderId']}"
            f"/external-reconstruction-submissions/{e['submissionRef']}/revisions/1",
            headers=H,
        ).json()
        sub, man = view["submission"], view["manifest"]
        subjects.append(
            SealedExternalSubjectV1(
                organization_id=sub["organizationId"],
                site_id=sub["siteId"],
                work_order_id=sub.get("workOrderId", e["workOrderId"]),
                submission_id=sub["submissionId"],
                revision=1,
                submission_digest=sub["submissionDigest"],
                manifest_digest=man["manifestDigest"],
            )
        )

    template = build_live_template(args.policy_template_file)
    now = datetime.now(UTC).replace(microsecond=0)
    return finish_admit(args, client, H, subjects, template, now)


def finish_admit(args, client, H, subjects, template, now) -> int:
    from cryptography.hazmat.primitives import serialization
    from ksi_core.domains.external.ingress.external_validation_policy import (
        PolicyAuthorityRecord,
        authorized_policy_body_digest,
    )
    from ksi_domain.canonical_json import canonical_json_bytes
    from ksi_event_contracts.external_artifact_validation import (
        ExternalValidationPolicyV1,
        PolicyStatus,
    )

    VERSION = 5
    _PLACEHOLDER = "sha256:" + "0" * 64
    draft = ExternalValidationPolicyV1(
        policy_id="syn-practical-geotiff-v1",
        version=VERSION,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=template["parserBuildDigest"],
        grammar_digest=template["grammarDigest"],
        resource_envelope=template["resourceEnvelope"],
        resource_envelope_digest=template.get("resourceEnvelopeDigest"),
        authority_record_digest=_PLACEHOLDER,
        inspection_rule_ids=tuple(template["inspectionRuleIds"]),
        evidence_rule_ids=tuple(template.get("evidenceRuleIds", ())),
        compatibility_mapping_digests=tuple(template.get("compatibilityMappingDigests", ())),
        synthetic_test_only=False,
    )
    # Bind: recompute authorized body digest from the exact sealed body
    # (authority_record_digest/policy_digest are excluded by definition).
    sealed_draft = draft.model_copy(update={"policy_digest": None}, deep=True).sealed()
    correct = authorized_policy_body_digest(sealed_draft)
    record_fixed = PolicyAuthorityRecord(
        policy_id="syn-practical-geotiff-v1",
        policy_version=VERSION,
        authorized_policy_body_digest=correct,
        permitted_subjects=tuple(subjects),
        permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
        authorized_actor_ids=("policy-admin",),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(days=7),
        # NOTE: the signed-snapshot reload path only admits non-synthetic
        # policies (provider _apply_policy_actions rejects synthetic_test_only).
        # Synthetic marking lives in producer declarations, subject/site names
        # and policy_id instead; same constraint as the F03 rehearsal rig.
        synthetic_test_only=False,
    ).sealed()
    policy = draft.model_copy(
        update={"authority_record_digest": record_fixed.digest, "policy_digest": None}, deep=True
    ).sealed()
    # Decide BEFORE any file write: the owner journals (read-only here) are the
    # authority, the provider snapshot file is only a mirror. A skip or a
    # mismatch must not touch any policy/authority/trust/snapshot file.
    data_dir = args.core_data_dir
    journal_rows = read_jsonl_rows(data_dir / "external-validation-policy.jsonl")
    snap = json.loads((args.provider_dir / "authority-snapshot.json").read_text())
    decision, detail = plan_policy_admission(
        policy_id="syn-practical-geotiff-v1",
        version=VERSION,
        body_digest=correct,
        subjects=tuple(subjects),
        permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
        authorized_actor_ids=("policy-admin",),
        synthetic_test_only=False,
        journal_rows=journal_rows,
        file_records=snap["policyAuthorities"]["records"],
        file_current=snap["policyAuthorities"]["currentDigests"],
        now=now,
    )
    if decision == "skip":
        # A matching authority snapshot alone is not enough: a prior broken
        # rerun could have replaced the standalone policy mirror without a
        # reload. Never describe that inconsistent artifact as a healthy reuse.
        try:
            _, admitted_row = latest_policy_status(journal_rows, draft.policy_id, VERSION)
            admitted_policy = ExternalValidationPolicyV1.model_validate(admitted_row["policy"])
            mirrored_policy = ExternalValidationPolicyV1.model_validate_json(
                (args.provider_dir / f"policy-v{VERSION}-syn-practical.json").read_text()
            )
            mirror_matches = (
                mirrored_policy == admitted_policy
                and mirrored_policy.sealed().policy_digest == admitted_policy.policy_digest
            )
        except (OSError, KeyError, TypeError, ValueError):
            mirror_matches = False
        if not mirror_matches:
            print(
                "admission refused: configuration mismatch: standalone policy mirror "
                "does not equal the journal-admitted policy; restore the exact accepted "
                "receipt, no reload attempted",
                file=sys.stderr,
            )
            return 2
        print(detail)
        return 0
    if decision == "mismatch":
        print(f"admission refused: {detail}", file=sys.stderr)
        return 2
    # Admit path only: publish the new policy file, extend the snapshot with a
    # signed ADMIT_POLICY action, and reload. Revocation history is settled
    # (v1-v4 revoked); no revoke action is synthesized here.
    prov = args.provider_dir
    policy_path = prov / f"policy-v{VERSION}-syn-practical.json"
    fd = os.open(policy_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(policy.model_dump_json(by_alias=True))
    head, seq = None, 0
    for line in (data_dir / "external-authority-provider-receipts.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("sequence", 0) > seq:
                seq, head = row["sequence"], row["snapshotDigest"]
    unsigned_snap = {k: v for k, v in snap.items() if k != "signature"}
    # Published history is never edited: keep every prior record, append ours.
    prior_recs = [
        r
        for r in unsigned_snap["policyAuthorities"]["records"]
        if not (r.get("policyId") == record_fixed.policy_id and r.get("policyVersion") == VERSION)
    ]
    recs = prior_recs + [record_fixed.event_payload()]
    cur = [
        d
        for d in unsigned_snap["policyAuthorities"]["currentDigests"]
        if d in {r.get("digest") for r in prior_recs}
    ]
    if record_fixed.digest not in cur:
        cur.append(record_fixed.digest)
    eff = now.isoformat().replace("+00:00", "Z")
    unsigned_snap.update(
        sequence=seq + 1,
        previousSnapshotDigest=head,
        issuedAt=eff,
        validUntil=(now + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
        policyAuthorities={"records": recs, "currentDigests": cur},
        quantitativeAdministration={
            "actions": [
                {
                    "actionId": f"syn-admit-policy-v{VERSION}",
                    "kind": "ADMIT_POLICY",
                    "effectiveAt": eff,
                    "actorId": "policy-admin",
                    "policy": policy.model_dump(by_alias=True, mode="json"),
                }
            ]
        },
    )
    signer = serialization.load_pem_private_key(
        (prov / "authority-signer.private.pem").read_bytes(), password=None
    )
    sig = signer.sign(
        canonical_json_bytes(
            {"domain": "ksi.external-authority-provider-snapshot.v1", "snapshot": unsigned_snap}
        )
    )
    (prov / "authority-snapshot.json").write_text(
        json.dumps(
            {**unsigned_snap, "signature": base64.b64encode(sig).decode()}, separators=(",", ":")
        )
    )
    r = client.post("/v1/operations/external-authority/reload", headers=H, json={}, timeout=30)
    print("reload", r.status_code, r.text[:300])
    return 0 if r.status_code == 200 else 1


def wait_measured(client: httpx.Client, H: dict, out: dict, deadline_s: int = 120) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        ok = True
        for label in ("t0", "t1"):
            e = out["epochs"][label]
            r = client.get(
                f"/v1/observation-work-orders/{e['workOrderId']}"
                f"/external-reconstruction-submissions/{e['submissionRef']}"
                "/revisions/1/inspection",
                headers=H,
            )
            payload = r.json().get("inspection") or {}
            state = payload.get("state") if r.status_code == 200 else None
            print(f"{label} inspection", state)
            if state not in ("MEASURED", "INSPECTION_REPORTED"):
                ok = False
        if ok:
            return True
        time.sleep(5)
    return False


def post_analyses(client: httpx.Client, H: dict, out: dict, skip_review: bool) -> int:
    site, area = out["site"], out["areas"]["north"]
    sel = {
        label: {
            "workOrderId": out["epochs"][label]["workOrderId"],
            "submissionRef": out["epochs"][label]["submissionRef"],
            "revision": 1,
        }
        for label in ("t0", "t1")
    }
    analyses = []
    for i in (1, 2):
        for attempt in range(4):
            r = client.post(
                f"/v2/sites/{site}/work-areas/{area}/analyses",
                headers={**H, "Idempotency-Key": f"syn-demo-pair-{i}"},
                json={"baseline": sel["t0"], "current": sel["t1"]},
            )
            print(f"analysis-{i} try{attempt}", r.status_code, r.text[:200])
            if r.status_code == 202:
                break
            time.sleep(5)
        if r.status_code != 202:
            return 1
        analyses.append(r.json()["analysisId"])
    out["analyses"] = analyses
    # wait COMPLETED (worker loop must be running)
    for aid in analyses:
        for _ in range(60):
            d = client.get(f"/v2/sites/{site}/analyses/{aid}", headers=H).json()
            if d.get("executionState") == "COMPLETED":
                break
            time.sleep(5)
        else:
            print(f"{aid} never COMPLETED", file=sys.stderr)
            return 2
        # V2 includes the result in its detail response; it has no /result route.
        # A completed state without the actual expected synthetic calculation
        # must not be reported as a successful rehearsal with empty metrics.
        metrics = (d.get("result") or {}).get("metrics")
        if not isinstance(metrics, dict) or any(
            metrics.get(key) != expected
            for key, expected in {"cutM3": 128.0, "fillM3": 0.0, "netM3": -128.0}.items()
        ):
            print(f"{aid}: expected synthetic calculation is missing or differs", file=sys.stderr)
            return 2
        print(aid, json.dumps(metrics, ensure_ascii=False))
    if not skip_review:
        target = client.get(f"/v2/sites/{site}/analyses/{analyses[0]}/review-target", headers=H)
        print("review-target", target.status_code, target.text[:200])
        if target.status_code != 200:
            return 1
        rv = client.post(
            f"/v2/sites/{site}/analyses/{analyses[0]}/reviews",
            headers={**H, "Idempotency-Key": "syn-demo-review-1"},
            json={
                "decision": "ACKNOWLEDGED",
                "comment": "시연 검토 확인 (SYNTHETIC)",
                "target": target.json(),
            },
        )
        print("review", rv.status_code, rv.text[:200])
        if rv.status_code != 201:
            return 1
        out["review"] = rv.json()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
