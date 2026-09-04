# Reusable product packages

Packages contain reusable typed contracts, domain rules, geometry, algorithms, and test vectors. They
do not own product requirement authority or independently claim a deployed capability.

| Path | Human responsibility |
|---|---|
| `domain/` | Stable shared value objects, enums, and capability/Mission gating types |
| `event-contracts/` | Executable Event/Observation/Processing contract models |
| `mission-contracts/` | Signed Mission/dispatch verification and bounded Edge helper CLIs |
| `mission-planning/` | Deterministic coverage, terrain, geometry, and WPML generation |
| `geo-core/` | Lightweight sensor-time, ENU, projection, fusion, and uncertainty logic |
| `geo-spatial/` | CRS, raster, terrain, and vertical-reference operations |
| `equipment-intelligence/` | Kinematic state, CPA/TTC, and RiskField algorithms |
| `perception/` | Recorded/offline evaluation plus reusable perception logic |
| `test-vectors/` | Shared golden/conformance vectors; never runtime authority |

Language-neutral API/JSON/HIL schemas live in `../contracts/`. A `*-contracts` package is executable
language binding/verification code, not a second requirements source.
