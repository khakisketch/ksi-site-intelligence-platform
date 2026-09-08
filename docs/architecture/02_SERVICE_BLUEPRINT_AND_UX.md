# Service Blueprint and UI/UX

> **SUPERSEDED.** This is a historical UX seed, not current product or implementation authority.
> Use `ADR-KSI-024/025/026`, `05_OPERATIONS_CONSOLE_PHASE_1_STANDARD.md`, and
> [`../DOCUMENT_STATUS.md`](../DOCUMENT_STATUS.md).

## User-facing concept

The default action is `새 현장 조사`, not separate low-level mapping/patrol switches.

## First site flow

1. Site boundary and CRS
2. Import BIM/plan if available
3. Baseline mapping
4. Processing and quality validation
5. World model publication
6. Patrol-ready activation

## Daily flow

1. Select site/area/asset
2. Select outcomes: safety, 3D refresh, progress, inspection
3. Select intensity
4. Review auto-plan
5. Launch
6. Review events and results

## Navigation

Mobile: Today / Missions / Events / Sites / More

Desktop: Home / Sites / Missions / Events / Assets / 2D-3D World / Reports / Fleet-Edge / Data-AI / Settings

## Runtime dashboard

Shows mission progress, coverage, world-model freshness, current autonomous action, events, static/dynamic risks, edge health and intervention requests. Live view is opt-in.

## UX guardrails

- No daily manual equipment radius drawing
- No raw detection count as primary information
- No hidden unobserved areas
- Simple presets, advanced controls collapsed
