# packages/geo-core

Coordinate frames, projection, uncertainty and surface intersection.

## Neutral AOI geometry (Task 3)

`ksi_geo_core.aoi` is the canonical neutral owner of the AOI polygon geometry
(`GeoPoint`, `AreaOfInterest` and their helpers/constants), moved mechanically
from `ksi_mission_planning.geometry` without numeric or validation changes.
`ksi_mission_planning.geometry` remains an exact `sys.modules` alias to this
module, so legacy imports share class and helper state with neutral imports.
