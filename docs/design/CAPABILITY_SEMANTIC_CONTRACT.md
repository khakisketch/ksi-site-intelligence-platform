# Capability approval and activation boundary

This contract governs retained acquisition evidence under [ADR-KSI-039](../architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md).

- A declaration, exact runtime observation, qualified evidence, product approval and operational activation are separate facts. Legacy `VERIFIED` has zero authority without the bound records.
- Promotion requires exact equipment, configured route and build, scoped fresh evidence, qualified approver and explicit activation. Vendor material and device self-reports cannot confer field or mission authority.
- Revocation and staleness remove usability. After prerequisite revocation, activation requires new authorization. Replay must preserve scope, evidence and revocation and must not infer validity from old projections.
- New route selection fails closed when prerequisites lapse. Previously issued signed mission contracts follow their separate approved safety policy.
- Raw evidence rights, approver and activator credentials, physical HIL and operator approval must be established before any field use.
