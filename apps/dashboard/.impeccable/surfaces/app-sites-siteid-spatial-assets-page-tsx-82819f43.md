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

## Latest user refinement — meaningful visual design

The user explicitly needs a visual example to understand the design, including illustrative data, and then asked for designer-led simple usable composition. The giant native-extent rectangle is not the primary visual solution; supporting extent metadata folds away. Keep the real-data path honest, and provide a separately labelled, user-initiated `/design-preview/materials` context using the SAME shared workbench presentation. Public CC BY 4.0 coastal display crops are independently licensed design assets, never a fallback for failed/revoked current Site bytes or a fake Core inspection/result. Example context has no Site/asset/job authority bindings, an unmistakable persistent design label, attribution and a return path. This supplements actual Console refinement and is not the whole-product deliverable rejected in the historical screen study.

Refinement thesis: one coherent toolbar, short observation/material rail, a large calm visual stage with single/left-right modes, selected details only on demand. Default view should be recognizable spatial data, not validation text or a new series of nested cards. Desktop1280/1440 and mobile390 are evaluated as compositions with real photographic examples as well as real-data failure states. Preserve ordinary product identity/tokens and API/MCP contracts; no new visual-world invention, third-party map call, numerical/registration claim or mandatory chatbot.

## Current user critique — composition, not photo presence

The user rejected the previous composition despite the photographic example: global 232px navigation plus persistent local rail and equal boxed panes still read as an admin layout. The prior visual acceptance is not binding against this feedback. Revise the layout hypothesis rather than spacing-polish: focused spatial shell on only materials/example routes, compact discoverable global navigation, one continuous visual plane, per-pane date and layer controls immediately above their content. Catalog and information are overlay tools, not persistent grid columns; opening either must not move or resize the base photo panes. Retain context, source/partial/date precision, real error states, permissions and exact selections; preserve non-workbench shell/login behavior and auth failure notices. Explicit example/public assets remain separated from registered data. The real check is stable visual reading order and direct operation in 1280/1440/390 renders, not image counts, test counts or a clean detector.
