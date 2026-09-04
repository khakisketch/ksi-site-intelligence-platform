# HIL document routing and product boundary

Status: active HIL index. HIL evidence and device operations remain separately approved work.

## Product path boundary

- PSDK Liveview is a local Manifold acquisition/perception input. It is not a continuous central
  video stream for Core or the Operations Console.
- `EDGE_UPLINK` is a bounded EventBundle/EdgeBundle metadata path. It is not Liveview, RTK/POS
  streaming, or original-media ingress.
- Current normal original media is `SD/storage -> field PC -> KSI web upload`.
- Optional automatic originals require distinct `MEDIA_PULL` and `MEDIA_UPLOAD` capability/HIL
  evidence. A successful `EDGE_UPLINK` check proves neither.

See [ADR-KSI-033](../architecture/ADR-KSI-033-repository-normalization-and-media-boundaries.md) for
the canonical current/target split.

## Active sequence

| Document | Role | Maximum conclusion |
|---|---|---|
| [`HIL_0_CAPABILITY_RUNTIME.md`](HIL_0_CAPABILITY_RUNTIME.md) | Route-family evidence plan and fail-closed schema | software evidence boundary only |
| [`HIL_1S_PSDK_RUNTIME_COMPANION.md`](HIL_1S_PSDK_RUNTIME_COMPANION.md) | PSDK/MOP companion and exact availability facts | companion software exists |
| [`HIL_1P_PSDK_PRODUCTION_ROUTE.md`](HIL_1P_PSDK_PRODUCTION_ROUTE.md) | Gateway/client/producer/publisher software seam | software seam assembled |
| [`HIL_1R_PHYSICAL_READINESS.md`](HIL_1R_PHYSICAL_READINESS.md) | Physical topology evidence and entry conditions | currently `BLOCKED_HARDWARE_TOPOLOGY` |
| [`FIELD_0A_CHECKLIST.md`](FIELD_0A_CHECKLIST.md) | Propeller-off Pilot/KMZ/original-photo evidence | field evidence only after approved session |
| [`HARDWARE_SESSION_PLAYBOOK.md`](HARDWARE_SESSION_PLAYBOOK.md) | Operator-owned hardware procedure | no action without explicit approval |
| [`RAW_LOG_CONVENTIONS.md`](RAW_LOG_CONVENTIONS.md) | Private raw-evidence handling | never commit raw evidence |

Host tests, schemas, imports, or builds do not close physical HIL, device support, authority,
deployment, or field acceptance. R0-R2 modifies and deletes no HIL original.
