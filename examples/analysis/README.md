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

* Configure an explicit HTTP(S) Core URL without userinfo, query or fragment;
  a deployment path prefix is allowed. URL credentials can otherwise replace
  the supplied Bearer credential. Tokens must be nonempty printable ASCII
  without internal whitespace (surrounding whitespace is stripped).
* Request and polling timeouts must be finite positive numbers, not booleans,
  strings or `None`. The request timeout bounds HTTPX's individual network
  operations, not the total response duration.
* Site/WorkArea and route IDs must match `[A-Za-z0-9][A-Za-z0-9_.-]*`;
  revisions must be positive integers, not booleans or numeric strings.
  Malformed values fail locally with `ValueError` before HTTP, without echoing
  them. The client never escapes or normalizes an ID to make it acceptable.
  Use the returned server `submissionRef`/`evidenceRef`, not raw customer IDs.
  This local path check does not establish existence, permission or suitability;
  Core still validates all bindings and organization/Site/WorkArea scope.
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

## Result contract cross-check (external consumer)

`result_contract_crosscheck.py` is an independent external consumer that
reads one analysis through BOTH consumption paths — Core HTTP and the
Analysis MCP stdio adapter — and cross-checks the seven elements of the
common result contract (numeric, region, input version, calculation
settings, valid region, quality indicators, limitations), plus the
shared-epoch continuation hint, the coverage byte resource, and HTTP/MCP
list agreement. It imports only stdlib + `httpx` (the `mcp` SDK is loaded
lazily for the MCP path only) and performs GET requests exclusively.

```console
$ python result_contract_crosscheck.py \
    --core-origin http://127.0.0.1:8000 \
    --site-id site-a \
    --analysis-id analysis-v1-... \
    --out /tmp/crosscheck.json \
    --token <FIELD_OPERATOR_JWT> \
    [--mcp-token-file /abs/path/to/mcp-token]
```

The token comes from `--token` or `KSI_CUSTOMER_TOKEN` (prefer the environment
variable: a command-line token is visible in the process list). Without
`--mcp-token-file` the MCP comparisons are reported as SKIPPED, not PASS.
Exit 0 means no check FAILED, 1 means a check FAILED, 2 means a
configuration/input problem with a fixed closed code on stderr (never the
token or a response body). The JSON record at `--out` carries only safe
identifiers, digests, numbers, and check outcomes.

Three state rules the live rig fixed, so the consumer never reports a
coherent state as a broken contract:

* **A withheld numeric result is SKIPPED, not FAIL.** When Core shows no
  numeric result (not started, blocked, reassessment required), the
  result-scoped elements — numeric, region, valid region, coverage resource
  — are SKIPPED with the reason. A missing number is never read as a
  violated element and is never silently passed either.
* **Only the observation identity has to match across a shared epoch.** The
  inspection-report digest and the input digest are produced once per
  analysis, so two analyses of the same observation legitimately differ
  there; they are recorded in `perExecutionFieldsEqual`, never required to
  match. The observation itself (`observationEpochId`, `artifactId`,
  `observedSha256`, size, CRS, vertical reference, transform digest) must
  match.
* **A continuation is verified at the level its records reach.** When the
  other pair has not produced epoch records yet, the shared epoch is
  verified at the selector level (`evidenceLevel: "selector"`); when it
  has, the observation identity is re-derived from the immutable records
  (`evidenceLevel: "observation"`). A hint that shares no epoch selector is
  a FAIL.

The list item and the detail are reconciled too: the consumer checks the
list's `resultId`, `metrics`, `limitationCount`, execution/suitability state
and creation time against the detail, so a consumer can compare two
projections of one record without trusting either.

A PASS record proves the two projections present the same contract; it does
NOT prove field accuracy, customer acceptance, or settlement fitness.

```console
$ umask 077
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/contract/test_analysis_result_contract_crosscheck.py
```

## Isolated E2E proving this flow

```console
$ umask 077
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/contract/test_v2_customer_http_flow.py
```

Configuration, path-input, object-upload and polling regressions:

```console
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/contract/test_customer_v2_client.py
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
