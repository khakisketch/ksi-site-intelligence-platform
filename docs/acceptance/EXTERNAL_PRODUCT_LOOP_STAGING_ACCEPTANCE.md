# External product-loop private staging acceptance

- Status: SOFTWARE_PREPARED — ACTIVATION_BLOCKED
- Requirements: REQ-INT-101/102/103/104, REQ-SEC-101, REQ-OPS-101/102, REQ-UX-101; EXT-STAGE-01..07.
- Invariants: INV-017/018/020/024/040/051/053/054/055/060.
- Scope: additive private-candidate deployment assets only.

| Check | Required proof | Current status |
|---|---|---|
| Candidate isolation | `ksi-external-rc` has its own Compose names and volumes; no Phase 2 lifecycle command | SOFTWARE_PREPARED |
| Host identities | fresh preflight plus root-reviewed account/rootless-Docker proof | NOT_APPLIED |
| UDS identity | named-worker ACL, `SO_PEERCRED`, socket mode/owner and cross-UID denial | BLOCKED_ACL_ACTIVATION |
| Runtime provenance | source/image/SBOM/scanner/revocation/manifest binding | BLOCKED_RELEASE_EVIDENCE |
| Quantitative authority | independently retained catalog/policy/evidence-currentness/capability authority injected into production assembly | BLOCKED_AUTHORITY_SOURCE |
| Synthetic product loop | register → inspect → decision → volume → review → successor WorkOrder | NOT_RUN |
| Real DJI Pilot 2 upload | exact user-approved path plus manifest-only preflight | NOT_REQUESTED |
| Customer/HIL/field acceptance | customer workflow and actual devices | NOT_VERIFIED |

The deployment contract test proves source assets and refusal paths only. It
does not prove a systemd host, Docker isolation, Core authority operation,
customer artifacts, external reconstruction compatibility, Tailnet access,
DJI behavior, HIL, or field acceptance.
