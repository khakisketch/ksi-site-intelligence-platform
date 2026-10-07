# packages/event-contracts

Observation, Candidate, Finding, Event Bundle contracts.

## Neutral site frame (Task 3)

`ksi_event_contracts.site_frame.SiteFrame` is the canonical neutral owner of the
Site spatial frame (`crs`, `verticalDatum`, `unit: "meter"`, `transformVersion`;
INV-020). It was moved mechanically from `ksi_mission_contracts.models` with
identical fields, camelCase aliases, full Pydantic config and validation — the
mission package re-exports the same class. The neutral module carries its own
minimal camelCase base (exact legacy config, no `allow_inf_nan` key) instead of
the package shared base. It imports neither mission nor acquisition code.
