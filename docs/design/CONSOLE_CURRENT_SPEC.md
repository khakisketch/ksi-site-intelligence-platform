# KSI Operations Console — current experience contract

This contract is subordinate to the product constitution, [accepted ADRs](../architecture/ADR-KSI-025-evidence-first-portfolio-home.md), domain invariants, API and data-rights contracts. It specifies the human interface only; it creates no endpoint, data source, permission, storage, queue or measurement authority.

## Navigation and work surfaces

- The responsive Console provides **홈·현장·작업·계정·도움말**. Desktop and mobile site navigation show **공간·분석**. **현장 설정** opens beside the site name. Mobile bottom navigation keeps 홈·현장·작업·계정. [ADR-KSI-042](../architecture/ADR-KSI-042-site-navigation-space-analysis.md) owns the route and legacy-link decisions.
- **공간** uses a single viewer with a **자료 / 등록 진행** panel and a separate selected-material inspector. The toolbar provides area selection, single/two-observation viewing, permitted desktop registration and information. Work area management and area data preparation belong here. Panels start closed unless a deep link opens one. The desktop panel reserves a bounded column.
- **분석** uses a task-first shell with **변화 분석 / 외부 비교** tabs. History is the default. Each tab leads to its own registration or request. **분석 결과** starts with the input observations, then state and readiness, values, and evidence and limitations.
- **현장 설정** contains site extent and status plus work area management. **작업** keeps the organization-wide inbox, all work with a site filter, and team management. Work detail links back to the site's registration progress.
- Home and Site list show a prepared image when one is supported. When none is available (loading, none, unknown, denied), the cover is the site's registered boundary drawn as a vector outline on the dark measurement surface, labelled `등록 경계` and `영상 아님`; a site without a boundary shows `경계 미등록`. The outline is neither imagery, measured geography nor accuracy evidence: it prints no coordinates, area or scale and uses no map tiles. Preview state is a text chip on the cover, never colour alone.
- Home reads in one column: summary counts, agenda list, initial setup, other sites as outline cards, recent updates as rows.
- An empty spatial stage keeps the same dark measurement canvas as a populated one. Guidance and the permitted next action sit in one light panel on that canvas; the grid is canvas chrome, not a map, footprint or site image.

## Screen consistency

1. A single centered empty-stage card shows a one-line title, one-sentence reason, `RegistrationPath` and at most one permitted primary action. Navigation stays in the panel and rail.
2. `Disclosure` wraps reference facts only, with the shared arrow, spacing and type. Label it `{대상} 상세`.
3. `ActionMenu` holds overflow actions.
4. State each fact once. Omit headings' kickers.
5. Use one primary button per screen, secondary buttons and inline links. Keep menus in navigation or overflow controls.
6. Use one alignment within each card.
7. Use the viewer frame for 공간 and `PageHeader` plus content for task screens. Card titles identify their own content.
8. Use one `InlineNotice` per issue.
9. Put raw identifiers behind an identification disclosure.
10. Use `text-micro`, `text-caption`, `text-body`, `text-lead`, `text-title` and `text-display`. Check line height when replacing arbitrary sizes and round half-pixel values when touching the screen.

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
- At 1024px and wider with a fine pointer, controls are 38px; the 44px/36px touch rule above still applies below 1024px and to coarse pointers. A recovery notice puts the fact on the left and its action on the right in one row; it does not grow into a stacked box. Forms keep a readable measure (about 48rem), optional groups collapse, and the same fact is not repeated as a title, kicker and caption.
- A work detail shows its progress as an ordered step indicator and one next action; it does not repeat the global work tabs. Steps come from retained records only, and a failed or unknown read shows the order without marking a current step.
- Interface copy uses business terms and shows the next allowed action before raw identifiers. Status meaning is conveyed by text and existing semantic state tokens, not colour alone.

Current route implementation and tests are the executable source. Real browser rendering at mobile/laptop/desktop widths and API-backed states must be verified separately; this contract is not evidence of deployment, customer acceptance, accessible real-device use or measured analysis.
