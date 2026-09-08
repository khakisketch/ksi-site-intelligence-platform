# TerrainPlanningBenchmarkDecision — 2026-09-08

**Status:** `PARTIAL` / `NOT_READY_FOR_ACCEPTANCE`

**Decision requested:** None. This records the benchmark evidence that is
missing before Human selection of planning objectives or acceptance thresholds.
It chooses no metric threshold, source, camera profile, route heuristic, or
Pilot/device behavior.

## Scope and authority

| Field | Record |
|---|---|
| Requirement IDs | ADR-KSI-035 D2/D5; TAP-02 through TAP-05; INV-020, INV-024, INV-060 |
| Owner | Product Authority accepts a future benchmark decision; implementation owners consume only an accepted record |
| Contracts changed | None. WP-0 remains blocked by WP-R source and benchmark closure |
| Evidence reviewed | Existing isolated terrain software tests, plus the WP-R source-evidence packet |
| HIL/field conclusion | None. No Pilot import, device, flight, capture, or field result was run |
| Rollback | Withhold acceptance; no runtime, schema, test threshold, or product behavior changes |

## Observed local software evidence

At source baseline
`ed447544313a0bbbeebfee706a6b11ccb4f3ca13`, the following focused local
selection passed on 2026-09-08:

```text
uv run --locked pytest tests/contract/test_geo_spatial_terrain.py \
  tests/contract/test_terrain_altitude_planner.py -q
# 21 passed in 0.57s
```

This establishes only isolated software behavior for terrain sampling and
relative-start altitude/envelope/missing-data/rate-failure fixtures. It does
not supply real source data, source version, benchmark baseline, terrain/known
structure integration, camera compatibility, safety, Pilot importability, or
field evidence. Synthetic fixture values are not product thresholds.

## Required benchmark surfaces and current gaps

| Surface | Required reviewable baseline | Current state | Minimum fixture evidence before threshold selection |
|---|---|---|---|
| Coverage gaps | Planned coverage gap distribution and typed gap reasons by AOI/segment | `NOT_RUN` | Flat, sloped, irregular AOI, holes, and missing-terrain cases with versioned source metadata |
| GSD distribution | Planned GSD distribution separated from actual coverage evidence | `NOT_RUN` | Same geometry under distinct explicit camera inputs; no camera default or acceptance value |
| Known-constraint violations | Candidate violations and source/uncertainty lineage | `NOT_RUN` | Known-structure and corridor-gap fixtures; absence/staleness/conflict cases remain gaps |
| Ingress, transit, normal return | Candidate feasibility and reason codes per segment | `NOT_RUN` | Takeoff-to-site, transit, normal-return, and missing-input fixtures; no flight/safety claim |
| Path length and time | Deterministic estimate provenance and version | `NOT_RUN` | Repeated identical snapshots plus partial-mode lineage; no schedule or efficiency objective |
| Pilot edits | Original-plan versus declared/observed final-plan evidence | `NOT_RUN` | Fixture-only unchanged/edited/unknown states. Actual Pilot edits require separately authorized receipts |

No fixture family above has a measured benchmark output in this record. The
rows are a test-data specification, not a conclusion about feasibility or a
requirement to use a particular source.

## Benchmark protocol still required

Before a Human can choose an objective or threshold, a future evidence package
must contain:

1. An accepted source-adoption record and a lawful, reproducible sample.
2. Immutable fixture inputs with CRS, vertical reference, unit, timestamp,
   source/version, uncertainty, AOI and segment lineage.
3. Deterministic planner outputs and replayable metric calculations for every
   surface in the table.
4. Separate planned estimates, declared Pilot edits, device receipts, actual
   trajectories, and capture/coverage evidence. One must not substitute for
   another.
5. Evidence-backed proposed objectives and thresholds, their residual failure
   modes, and explicit Product Authority acceptance or rejection.

The current source record is also `PARTIAL`; therefore no lawful sample decoder
result, terrain benchmark, or threshold is available to attach here.

## Gap matrix and stop conditions

| Gap | Effect | Stop condition |
|---|---|---|
| No source/layer/terms decision | No provenance-complete terrain fixture | Do not select, procure, download, or accept terms on behalf of the owner |
| No lawful sample | No decoded CRS, vertical, no-data, resolution, or coverage baseline | Do not use catalogue claims as benchmark data |
| No benchmark outputs | No numerical or optimization conclusion | Do not set a quality, route, time, coverage, GSD, or safety threshold |
| No Pilot/device receipt | No compatibility, trajectory, or field conclusion | Do not label a draft as importable, executed, or safe |
| No cross-organization test evidence | No implementation isolation result | Preserve INV-060 as a future contract/replay gate |

## Decision questions for the Product Authority

1. After the source record is independently reviewed, which lawful sample path
   may be evaluated?
2. Which non-customer fixture context is authorized for measured baselines?
3. What owner and evidence standard will approve a future objective or
   threshold record?
4. Should WP-R remain blocked if any required metric lacks reproducible source
   and fixture evidence? This record makes no alternative recommendation.

WP-R is **not complete**. WP-0, WP-1, and WP-2 remain blocked on explicit Human
acceptance of future source and benchmark closure records.
