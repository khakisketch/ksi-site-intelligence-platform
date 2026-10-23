---
version: 1
slug: "app-sites-siteid-spatial-assets-page-tsx-82819f43"
primary_target: "apps/dashboard/src/app/sites/[siteId]/spatial-assets/page.tsx"
related_targets: []
---

# Materials visual explorer

Scope: Actual Console spatial-assets route and reusable visual viewer. Mode: Operate. Current user approved improving materials visually and prefers DroneDeploy-like left/right observation viewing. This brief is a development aid, subordinate to repository product authority and current user direction, not runtime acceptance.

## Direction contract
THESIS: Recognize a spatial material by seeing it, then inspect evidence on demand; refuse the file-and-validation-page-as-primary composition.
OWN-WORLD: Preserve KSI's dark navigation, light readable chrome, restrained status tokens and existing UI font; frame real ortho/DSM in a neutral spatial canvas. No fake photography, basemap, or unsupported 3D affordance.
STORY: Choose an observation/material, see its allowed pixels, add an explicit B observation for independent left/right viewing, inspect only the selected material's provenance and permitted uses. API/MCP and web refer to the same durable records.
FIRST VIEWPORT: Slim title/actions, compact searchable observation/material rail, dominant single preview or equal A/B visual panes; selected information hidden until requested. File preparation parameters/analysis forms/history fold away. At 1280x720 and1440x900 evaluate actual usable imagery area, not count of rows.
FORM: User-pinned visual explorer with optional left/right comparison; no random concept tournament. Existing assetRef and visualA/B exact selection routes remain compatible. Side-by-side is explicitly independent until display geometry/authority permits synchronization.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

Constraints: Current actual fileGET503 is separate blocked pixel recovery. No Core/runtime/journal/S3/TTL/grant changes, no automatic new PREPARE. Existing receipt/SHA/decode/permissions and partial/NoData/date precision apply. Distinguish missing, failed, denied, unsupported. No new quantitative judgment or invented overlays. No product shipping imagery is sourced from reference screenshots. Any simulated UI test pixels are test-only and labeled in evidence.
