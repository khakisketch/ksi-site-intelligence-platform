# Legacy root UI audit captures

Status: `ARCHIVED`, non-authoritative, 2026-09-04.

These 26 PNG files were found ignored and unreferenced at the repository root during R0-R2
normalization. Their filenames did not identify a durable acceptance run, viewport matrix, source SHA,
operator, or current product requirement. They are retained byte-for-byte for possible historical
comparison, but they are not evidence that the current Dashboard, deployment, or authenticated flow
passes acceptance.

The canonical hashes, former paths, classification rationale, replacement, and rollback instruction
are recorded in
[`../../../audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json`](../../../audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json).
New acceptance captures must live with their dated acceptance/audit record and must state the tested
source revision and viewport.
