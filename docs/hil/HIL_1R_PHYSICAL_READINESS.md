# HIL-1R — Physical Route-1 readiness closure

## Scope and product boundary

HIL-1R prepares one non-actuating `PSDK_MANIFOLD / EDGE_UPLINK` transport for
a later approved bench session. It does not perform that session and it does
not change CAP-1 through CAP-5 authority.

This route is not the KSI Site Intelligence media ingress. It carries a bounded
EventBundle/EdgeBundle **metadata frame** containing Mission identity, object
reference, claimed digest and idempotency identity. It does not carry live
video, RGB frames, original photos, RTK/POS data, orthomosaics, point clouds or
other source-media bytes.

The canonical product flow remains:

```text
Site / WorkOrder -> Acquisition Mission -> original photos + RTK/POS/metadata
-> SourceMediaBundle upload/import -> Processing -> spatial/change/volume/design
-> current Site state -> acquisition gap -> recommended Mission -> review/issue
```

PSDK Liveview is a local Manifold input for bounded acquisition-quality,
perception and adaptive-observation work. The v1 normal source-media route
remains `SD/storage -> field PC -> KSI web upload`; optional PSDK original-photo
offload is a separate `MEDIA_PULL`/`MEDIA_UPLOAD` capability and physical HIL.
None of those paths is evidence for this `EDGE_UPLINK` route, and HIL-1R PASS
would not establish end-to-end Site Intelligence readiness.

Invariants enforced here:

- INV-011: route state is not a signed Mission Contract.
- INV-012: route loss blocks a new invocation but cannot invalidate an already
  locally valid Mission Contract.
- INV-040/041: captured route facts and physical identity retain exact lineage;
  software or configuration evidence cannot become device verification.
- INV-042: capability evidence, product approval, operational activation and
  runtime route readiness remain separate authority decisions.
- INV-060: credentials are role-separated and fail closed.

## Send handoff versus peer receipt

`DjiMopChannel_SendData` success and `realLen == requestedLen` mean only:

> The sender handed exactly N bytes to the vendor reliable MOP channel.

They do not prove that a peer received, validated, stored or semantically
accepted the frame. No protocol acknowledgement is added by HIL-1R.

A physical bundle-receipt PASS therefore needs an independent peer log with:

- an exact one-frame `acceptedFramesBefore -> acceptedFramesAfter` increment;
- the exact provider operation ID;
- matching bounded metadata and claimed SHA-256 string;
- peer UTC and monotonic receipt timestamps;
- the peer raw-log reference, size and recomputed SHA-256.

The provider handoff log and peer receipt log must be different raw artifacts.
The offline verifier rehashes both before making its deterministic decision.

## DJI PSDK 3.16 topology evidence

Repository-pinned vendor evidence does not establish payload-to-payload PSDK
MOP for the proposed KSI peer:

1. `dji_mop_channel.h` documents a PSDK `Bind`/`Accept` payload as accepting
   clients “such as MSDK or OSDK device” (lines 63-69).
2. The PSDK MOP sample implements the `Bind`/`Accept` server. It does not call
   `DjiMopChannel_Connect`.
3. The only pinned PSDK `Connect` sample is Camera Manager point-cloud receipt;
   it connects to a DJI camera payload address (lines 2678-2687).
4. `E_DjiChannelAddress` exposes payload/extension, RC app and Cloud addresses,
   but no Manifold-onboard address (lines 290-307).

Authoritative local inputs:

- `edge/third_party/psdk/psdk_lib/include/dji_mop_channel.h`
- `edge/third_party/psdk/psdk_lib/include/dji_typedef.h`
- `edge/third_party/psdk/samples/sample_c/module_sample/mop_channel/test_mop_channel.c`
- `edge/third_party/psdk/samples/sample_c/module_sample/camera_manager/test_camera_manager.c`
- `edge/third_party/PSDK_LOCK.yaml` (PSDK 3.16.0,
  `9af08536df3671ed77aee02f1f2e4173b0e0f558`)

Consequently:

```text
PEER_TOPOLOGY_ASSUMPTION = UNVERIFIED
PEER_TOPOLOGY            = UNRESOLVED
HIL_ROUTE_1              = BLOCKED_HARDWARE_TOPOLOGY
```

The current PSDK `Connect` receiver remains useful as a compile-, lifecycle-
and parser-tested hypothesis. It is not proof that the client can address the
Manifold-hosted `Accept` server.

## Physical endpoint requirement

Physical HIL may start only after DJI documentation or a separately approved
read-only discovery establishes one exact supported topology.

### Preferred documented topology

- Endpoint A: M4D + Manifold 3 running the exact HIL-1S PSDK `Bind`/`Accept`
  DPK and local Gateway companion.
- Endpoint B: a separately provisioned MSDK or OSDK client implementation that
  DJI documents as able to connect to Endpoint A's exact MOP channel.
- Both ends: exact device, firmware, SDK/runtime, channel, port, package and
  build digests recorded before the session.

The repository does not currently contain that MSDK/OSDK peer implementation.
Adding it requires a separate approved implementation scope and its own
non-actuating boundary review.

### Current two-PSDK hypothesis

- Endpoint A role: Manifold-hosted PSDK `Bind`/`Accept` companion plus Gateway.
- Endpoint B role: a different physical PSDK runtime running the KSI
  `Connect`/`RecvData` peer.
- Required channel/address: the same approved channel ID and a vendor-supported
  address that explicitly names Endpoint A.

The pinned SDK provides no address that explicitly names the Manifold-onboard
endpoint. Therefore merely obtaining a second PSDK computer or mounting a
camera payload does not satisfy this hypothesis. No bench session may be
scheduled against an invented address mapping.

## Software and CI gates

The ordinary CI workflow is configured to perform the following gates; the
commands were reproduced locally, but this unpushed worktree has no remote-run
evidence yet:

- host companion and peer CTests;
- Gateway-to-PSDK Unix interoperability;
- ASan+UBSan diagnostics (TSan remains a separate non-PIE/setarch diagnostic);
- pinned PSDK 3.16 fetch, version-header and archive-digest verification;
- canonical arm64 Ubuntu 20.04/gcc 9.4 companion and peer builds;
- mutual-exclusion configuration rejection;
- ARM64 ABI, required MOP symbol and non-actuating source/ELF checks.

The exact `.dpk` packaging target still requires a DJI-issued
`user_app_id`. CI does not invent or embed one, so the ARM64 executable/link
gate can be verified while the final deployable DPK-package gate remains
`PARTIAL`. No generated CI binary is approved for installation.

## Evidence capture

The physical operator will use:

- schema: `contracts/hil/capability-runtime-hil-evidence-v2.schema.json`;
- offline tool: `tools/hil/capability_runtime_hil_v2.py`;
- raw inputs: PSDK companion, peer, Gateway and Core logs; observation journal;
  authority/Mission references; device/firmware/build inventory; operator and
  timing records.

The `capture` command imports and hashes local files. `finalize` revalidates all
mandatory A-J scenario relationships and produces only a deterministic HIL
result. `PASS` requires every scenario to be `OBSERVED`; failed or incomplete
scenarios remain honestly representable without fabricating their successful
events. Existing approval/activation IDs and digests may be recorded from the
authority journal, while `authorityDecisionCreatedByTool=false` and
`routeEvidenceQualification=NOT_QUALIFIED` remain fixed. Neither command
connects to Core/DJI nor creates CAP-2 qualification, CAP-3 approval or CAP-4
activation.

## Exact entry conditions

All conditions are mandatory before physical HIL begins:

1. the peer topology is documented by DJI or approved explicitly as the exact
   hypothesis under test, with physically available endpoint A and B;
2. exact ARM64 build and DPK digest are available; the deployable DPK was built
   with owner-held DJI credentials outside CI;
3. aircraft, RC, Manifold, peer, hardware revisions, firmware and PSDK version
   can be recorded;
4. separate owner-only observation and preflight credentials exist and differ;
5. an isolated approval/activation/Mission envelope and feature-flag procedure
   has separate operator authorization;
6. propellers remain removed and the synthetic bundle is non-actuating metadata
   only;
7. all required raw log/journal destinations exist and the v2 capture tool is
   staged offline;
8. no customer data, production feature flag or production authority is used.

Until condition 1 is resolved, `HIL_ROUTE_1` is
`BLOCKED_HARDWARE_TOPOLOGY`, not `READY_FOR_PHYSICAL_HIL` and never
`VERIFIED_HIL`.
