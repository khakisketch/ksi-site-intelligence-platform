# Operations Console Surface Overrides

This page uses `../MASTER.md` and the Phase 1 standard. It is not a landing page.

## Shell

- Desktop: persistent left navigation with the four customer tasks (`홈 · 현장 · 작업 · 확인 항목`)
  followed by lower-frequency operations support.
- Mobile: fixed five-item bottom navigation (`홈 · 현장 · 작업 · 확인 · 더보기`).
- The title bar describes the current product task, not a campaign or product slogan.
- Keep the main content full-width enough to support tables and evidence panels. Narrow centered widths
  are reserved for login and deliberate reading forms only.

## Primary page patterns

| Surface | First information | Primary transition |
|---|---|---|
| Home | portfolio summary and deduplicated sites needing attention | open the right site/evidence context |
| Sites | site comparison on desktop; scannable site rows on mobile | open a site workspace |
| Site workspace | briefing with change, importance, decision, citations, uncertainty | move within one site context |
| Work | decision-required work before progress and history | open the work order with site context |
| Review items | site, observation, time, evidence and human decision | open evidence-first detail |

## Density and copy

- A compact summary strip is sufficient for queue counts. Do not use a tall explanatory hero above the
  actual list.
- `최근 관측` refers only to a capture/observation time; `최근 갱신` refers to generic record updates.
- Use user terms (`확인 항목`, `조사 계획`, `현장 열기`) and avoid leading with `Mission`, `Event`,
  `Gateway`, `Edge`, IDs, KMZ, or adapter terms.
- For a blocked compact action, show the reason and the notebook continuation; do not repeat Core RBAC
  implementation details in every notice.

## Site-specific presentation

- 2D/3D World, reports, changes, quantities, and survey history are site areas. They do not belong in
  the global primary navigation or a generic `World` CTA in the site list.
- A site list shows: site name, current state, current next action, a truthful update/observation time,
  and a link to open the site. The technical site ID is expert information.
- Site images remain evidence context only. Absence of an image is not a visual defect to be filled.
