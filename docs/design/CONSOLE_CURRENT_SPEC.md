# KSI Operations Console — current experience contract

This contract is subordinate to the product constitution, [accepted ADRs](../architecture/ADR-KSI-025-evidence-first-portfolio-home.md), domain invariants, API and data-rights contracts. It specifies the human interface only; it creates no endpoint, data source, permission, storage, queue or measurement authority.

## Navigation and work surfaces

- One responsive Console is used by site staff and analysts. The global navigation provides **Home, Sites, Work, Account and Help**. A site has a bounded workspace for **Workspace, Materials, Site Work, and Results**.
- **Spatial workspace and Materials are viewer-first on desktop.** The real scoped site/WorkArea state leads, and the spatial stage remains the main surface. Global navigation remains user-controlled and discoverable; the site selector preserves the current authorized section.
- The desktop catalog and selected-material inspector start closed. Opening a docked panel reserves a bounded column; it never covers the spatial stage. Panel width is bounded, and the selected inspector appears only for an identified record.
- **Work, results, review and site management remain task-first.** Use the same global/site context and familiar table/form controls. Do not mirror site authority or make `/field` imply a personal assignment; that path is the organization work record.
- Home and Site list use a neutral 16:9 cover only when no supported prepared image is available. Label it as a generic cover. It is not imagery, measured geography or accuracy evidence.

## Required state presentation

- Carry the active Site, WorkArea, observation interval and authorized asset scope visibly through navigation. Empty materials and workspace states retain the selected WorkArea identity and allow changing among currently authorized areas without implying that absent assets are prepared.
- Distinguish `loading`, `empty`, `unavailable`, `unsupported`, `denied`, `expired`, and usable states. Failed or unqueried data is never an empty result, zero count, fallback record, or readiness claim.
- A spatial stage may show only registered/approved data or supported prepared bytes with current access. If pixels are unavailable, explain why and offer only the recovery action permitted by Core; do not synthesize an image, geographic footprint, alignment or result.
- Results show their exact inputs, run state, readiness and reasons independently. A previous result remains labelled as previous; loading a stored result does not issue a new calculation. Comparison navigation preserves exact current authorized references.
- Describe CRS, vertical reference, provenance, declared-versus-observed facts, inspection, suitability and numerical accuracy separately. No RTK status, registration, file inspection or worker success becomes a survey/settlement claim.
- Registration guidance respects the current capability and responsive action boundary. Narrow screens may read, compare and review while write actions that require a laptop are visibly handed off; do not gate ordinary read/navigation routes merely because they share a page.
- Authentication changes or expiry hide prior private material immediately. If session identity cannot be verified, the screen stays private and requires a trusted session re-check; never reveal a previous account's records while recovery is unavailable.

## Responsive and interaction behavior

- Desktop `1440px` and laptop `1280px` use the viewer/tables with reserved columns and no overlapping navigation. At `1024px` and below, preserve one-column reading order and the explicit desktop-only mutation boundary.
- Mobile targets are at least 44px; fine-pointer targets at least 36px. No page-level horizontal overflow; fixed navigation cannot obscure the final content.
- Native controls, links, keyboard order, visible focus, Escape/cancel behavior, reduced-motion preference, and live status announcements remain functional. Every loading, error and unavailable state has a location-appropriate recovery path.
- Interface copy uses business terms and shows the next allowed action before raw identifiers. Status meaning is conveyed by text and existing semantic state tokens, not colour alone.

Current route implementation and tests are the executable source. Real browser rendering at mobile/laptop/desktop widths and API-backed states must be verified separately; this contract is not evidence of deployment, customer acceptance, accessible real-device use or measured analysis.
