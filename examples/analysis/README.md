# Customer V2 example

The client also exposes public observation options and bounded coverage byte ranges
(`get_coverage_range(..., start=0, end=31)`, at most 64 KiB per request), returning
the server's range and digest metadata without recalculating or approving a result.
Historical review receipts remain readable after policy expiry or later evidence changes;
new reviews must still resolve an exact current result. A replayed receipt is not current approval.

`customer_v2.py` is a reusable, dependency-light (`stdlib + httpx` only)
driver for the customer side of the KSI V2 external analysis flow. It never
imports KSI packages, test stores, or fixtures. Import check:

```console
$ python -c "import sys; sys.path.insert(0, 'examples/analysis'); import customer_v2"
```

## Operator setup (done separately, never by this class)

1. The operator registers the Site and WorkArea and communicates the
   `site_id` / `work_area_id` to the customer out of band.
2. The operator provisions a `FIELD_OPERATOR` OIDC subject whose grants cover
   exactly that Site/WorkArea and issues its signed JWT to the field device.
3. The customer supplies that JWT via the `token` argument or the
   `KSI_CUSTOMER_TOKEN` environment variable. ADMIN or worker credentials must
   never be configured here.

## Consumer example

```python
from customer_v2 import CustomerV2Client

with CustomerV2Client(
    "https://core.example.test",
    site_id="site-a",
    work_area_id="wa-site-a-0001",
    # or export KSI_CUSTOMER_TOKEN=<FIELD_OPERATOR OIDC JWT>
    token="<FIELD_OPERATOR OIDC JWT>",
) as customer:
    order = customer.create_work_order("field-day-1", idempotency_key="day-1")
    work_order_id = order["workOrderId"]
    context = customer.get_registration_context(work_order_id)  # expectedEpochId, ...
    registered = customer.register_submission_v2(work_order_id, submission)  # caller JSON
    submission_ref = registered["submissionRef"]
    for grant in customer.request_upload_grants(work_order_id, submission_ref):
        customer.put_object_bytes(
            grant["uploadUrl"],
            artifact_bytes[grant["artifactId"]],
            content_type="application/octet-stream",
            required_headers=grant["requiredHeaders"],  # forwarded exactly, never auth
            artifact_id=grant["artifactId"],  # structured error context; never the grant URL
        )
    customer.seal_revision(work_order_id, submission_ref)
    customer.get_inspection(work_order_id, submission_ref)
    declared = customer.declare_evidence(
        work_order_id, submission_ref, intent, idempotency_key="ev-1"
    )
    evidence_grant = customer.grant_evidence_upload(
        work_order_id, submission_ref, declared["evidenceRef"], idempotency_key="ev-g-1"
    )
    customer.put_object_bytes(
        evidence_grant["uploadUrl"],
        csv_bytes,
        content_type="text/csv",
        required_headers=evidence_grant["requiredHeaders"],
    )
    customer.seal_evidence(
        work_order_id, submission_ref, declared["evidenceRef"], idempotency_key="ev-s-1"
    )
    analysis = customer.create_analysis(baseline, current, idempotency_key="an-1")
    view = customer.wait_for_analysis(analysis["analysisId"])
    target = customer.get_review_target(analysis["analysisId"])
    customer.post_review(
        analysis["analysisId"], target,
        decision="ACKNOWLEDGED", comment="...", idempotency_key="rev-1",
    )
    customer.list_reviews(analysis["analysisId"], limit=50)
```

JSON declarations (`submission`, `intent`, `baseline`/`current` selectors) are
supplied by the caller with explicit known metadata (capture interval,
producer run, digests measured from the actual bytes). The class never invents
times, producers, or vertical references.

## Safety notes

* The class never prints tokens or grant URLs. Object PUT failures omit the
  URL and response body, including on transport failure (`CustomerHttpError.status == 0`
  means no HTTP response). Optional `artifact_id` is available on the error as
  structured caller context; it is not interpolated into the message. Core errors
  retain the server's detail, so do not log them indiscriminately.
* Unsafe grant forwarding is rejected: object PUTs use a credential-free
  client; only `content-type`, `content-length`, and `x-amz-checksum-sha256`
  are supported. Their values are preserved; case-duplicate names, control characters,
  mismatched byte length, unsupported headers and URL credentials fail before I/O.
  Storage response cookies are not resent and redirects are not followed. A new
  required storage header needs an explicit reviewed allowlist extension, not blind forwarding.
* WorkOrder, evidence, Analysis and review requests use caller-supplied
  `Idempotency-Key` values. Submission registration also retains its immutable
  submission/revision/digest identity.
* `wait_for_analysis` returns actionable blocked/remediation/reassessment views,
  rather than waiting for a number that the server deliberately withholds.
  For pending work it backs off from 0.2 to at most 2 seconds, caps waits to the
  remaining finite positive deadline, and makes no new GET after that deadline.
  An in-flight GET is still bounded by the client's per-request timeout; this is
  not cancellation or a hard wall-clock timeout for that request. No mutations
  are automatically retried.

## Isolated E2E proving this flow

```console
$ umask 077
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/contract/test_v2_customer_http_flow.py
```

Trusted setup lives in `tests/support/v2_customer_http_harness.py`; the
customer side above performs every customer step over real loopback HTTP.

Evidence labels used throughout: all raster/CSV bytes are generated
in-test fixtures (2x2 compound `EPSG:5186+5773` GeoTIFFs with known heights,
4-row checkpoint CSV) — they exercise the real ingress/inspection/measurement
contracts but never prove customer export, field accuracy, or operational
containment. Inspection and checkpoint measurement execute the real byte
entrypoints behind production admission gates with test-generated
Ed25519-signed manifests; execution is software-only (no Docker containment,
systemd, or deployed-service proof).
