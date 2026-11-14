# KSI Operations Console Design System — Phase 1

- Status: Active design guardrail
- Date: 2026-08-24
- Product authority: `docs/design/CONSOLE_CURRENT_SPEC.md`
- Implementation authority: `apps/dashboard/src/app/globals.css` and existing shared components

## Product posture

KSI Operations Console is an evidence-first construction operations workspace. It is neither a
marketing site nor a drone flight controller. A screen helps a person locate a site, understand a
grounded change, review evidence, make a human decision, and continue the next piece of work.

The existing CSS variables, typography, state tokens, and components are the source of truth. This
file records use rules; it must not introduce a parallel colour palette, remote font dependency, or
visual component system.

## Visual rules

- Use the existing neutral surface, ink, line, and semantic status tokens. Do not add an "AI" purple
  theme, consumer gradients, blue/green rebrand, or a dark theme.
- Use compact 1px dividers and restrained rounded surfaces. A card separates a distinct object or a
  decision; it does not decorate every number.
- Keep shadows sparse. Hover may change border/background; it must not lift, scale, parallax, or move
  layout.
- Use the local Korean/system typography already supplied by the application. Do not add Google Font
  imports at runtime.
- Evidence images are allowed only when they are registered artifacts from the same scoped site. Never
  invent site photography, generic aerial placeholders, or a decorative 3D scene.
- The Console is a full operating surface at desktop widths. Do not make a dashboard into a narrow,
  centered landing page or add a hero, newsletter, trial CTA, social proof, or marketing conversion
  pattern.

## Scale and shared primitives (2026-11-14)

- Type uses six named steps from `globals.css`: `text-micro` 11, `text-caption` 12, `text-body` 13,
  `text-lead` 14, `text-title` 17, `text-display` 22. Use these names in place of equal sizes after checking line height.
  Round half-pixel sizes when reviewing the screen.
- Radius: 6px controls (`rounded-md`), 8px panels and stages (`rounded-lg`), 10px cards. Elevation has two
  steps only: `shadow-elev-1` (raised panel) and `shadow-elev-2` (popover, sheet).
- Buttons are `.btn` with `btn-primary`, `btn-danger`, `btn-quiet` (toolbar/row secondary) and `btn-sm`.
  Do not hand-write a bordered rounded link that imitates a button.
- Shared parts in `src/components/ui`: `PageHeader`, `Panel`, `DataRow`, `StepIndicator`, `Stat`,
  `InlineNotice`, with `EmptyState`, `ErrorState`, `StatusBadge`/`StateBadge`. A list row omits a fact that
  has no value; it does not print "미정" or "미배정" to fill the line.
- The spatial stage is a fixed dark measurement surface (`--stage`, `--stage-grid`) whether populated or
  empty. This is a canvas, not a dark theme; chrome around it stays light.

## Vocabulary (2026-11-14)

- One work-record word: **작업**. The global menu item, its list ("전체 작업"), the inbox ("받은 작업"),
  closing/reopening ("작업 종료·다시 열기") and the detail title ("작업 상세")
  all use it. Do not reintroduce 업무, 관측 작업, 현장 작업 or 작업 큐 for the same record.
- Keep 공간 (spatial viewer), 분석 (analysis), 작업구역 (work area) and 관측 자료 등록 (registering observed data):
  they name different things. "업무 구분" in the team roster and "업무 화면" in login copy are generic
  business wording, not the work record.
- Home lists agenda items as a vertical list, never a swipe carousel (ADR-KSI-025 D8).
- A site cover without a prepared image is the registered boundary outline (`SiteFootprint`): a vector shape on `--stage`, labelled as registered boundary and not imagery. No map tiles, coordinates, area or scale are drawn (ADR-KSI-025 D9).

## Information hierarchy

1. Site name and the user question.
2. The exact observation, result, or work state that supports the question.
3. A single permitted next action or an honest unavailable/recovery state.
4. Technical identifiers only in expert recovery context.

Do not put connection receipts, raw IDs, KMZ, internal status names, auto-progress claims, or device
support assertions ahead of the user-facing decision.

## Responsive rules

| Width | Layout | Interaction |
|---|---|---|
| 390 / 768 | one column; cards/list rows for comparison data | reading, event triage, analysis, Copilot and reports only |
| 1024 / 1440 | dense comparison tables and workspace tabs | role-authorized operating actions |

- A data table that needs horizontal scrolling is a desktop component. On compact widths render the
  same facts as cards/list rows instead of clipping or asking the user to pan across columns.
- Coarse pointer targets are at least 44px; fine pointer targets are at least 36px. Use `tap-target`
  and existing button/input primitives.
- Preserve keyboard order and visible focus. Text, not colour alone, carries status.
- Respect reduced motion. No autoplay carousel, background animation, counter animation, or progress
  animation as a substitute for a fact.
- No page-level horizontal overflow; fixed mobile navigation must not hide content.

## Component rules

- Use `EmptyState` for a truthful zero-result state and keep it distinct from a loading or failed
  request.
- Use `ResponsiveActionBoundary` for a compact-width disallowed operational action. Its copy explains
  what to do next without repeating implementation or security internals.
- Use `StateBadge` and `StatusBadge` with their labels. Do not render an unlabelled coloured dot as a
  status.
- Prefer `Link` for URL-state navigation so deep links, browser back, and server rendering remain
  correct.

### Screen consistency

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
### Site list controls and default visual (Human follow-up, 2026-10-19)

Search and sort are one compact toolbar, not two differently labelled forms: a magnifier inside
the search field, a native sort select, consistent control heights and accessible labels. Avoid a
redundant visible search submit button when debounce + Enter provide the action. Do not navigate
mid-IME composition or allow a pending search to override newer criteria/history navigation.
Compact users must be able to reach search without opening an unrelated advanced-filter disclosure.

The Site list may reuse the Home `DefaultSiteVisual` as a small **decorative default**, clearly labelled
`기본 이미지`; it is not site footage or measured geography. Keep names/status/next action primary and
retain the dense desktop comparison table. A genuine preview still requires a supported, scoped
registered-artifact source; do not infer one from the existence of a Site/WorkArea/asset or fetch raw
bytes as a thumbnail workaround. This supersedes the earlier text-only row choice, not media rights
or the ban on fabricated site photography or geographic evidence.

### Phone Site list adaptation (Human-approved, 2026-10-19)

At widths below 640px, optimize for **find → choose a Site**, not a scaled desktop toolbar:

- Keep search full-width and always visible. Use one quiet count row with the `필터·정렬` popover below it.
  expose status and sorting together on demand with an explicit Apply and whole reset.
- Applying phone criteria uses the latest search draft and cancels any scheduled search. Selecting
  controls alone must not apply them; closing discards unapplied choices. Search-only acknowledgements
  must not erase in-progress filter choices. Apply closes the panel and restores focus.
- Omit only the **decorative default** from phone cards so identity/status/next action/open action use
  the available width. Do not reserve an empty image gutter. This is not a ban on useful real imagery.
- At 640px and above, retain the existing tablet/desktop toolbar and default visuals. The Home hero's
  approved D6 hierarchy and geometry are outside this refinement and remain unchanged.

Use the shared native popover for these list controls.
The 640px threshold is a content-fit boundary, not an authorization boundary; existing 1024px operation
gates remain independent.

### Desktop Site presentations (Human-approved, 2026-10-19)

At 1024px and above, offer `카드 | 목록` as two presentations of the same scoped records:

- **Cards (default)**: two columns with broad, intentional typographic covers. A single Site occupies
  one column, never stretches into a full-page hero. Make the real Site name prominent; without a
  supported preview source, mark it `기본 표지` rather than enlarging an ambiguous miniature image.
- **List**: dense aligned comparison rows with no decorative thumbnail. Keep identity/status/progress/
  update/next action and one open action per row; fit the laptop content width where feasible.
- One presentation is visible at a time. Switching is a local display choice, not a data operation;
  it preserves query/filter/sort, pending search, focus and existing authority boundaries.
- Remember only the validated mode in a first-party functional preference, with correct server-side
  initial presentation. Do not store Site IDs, queries, auth data or analytics, or add a Core preference
  endpoint. If persistence is unavailable, the current-tab choice should still work.

Phone/tablet layouts and Home D6 remain as previously verified. This desktop decision supersedes the
earlier small-default-thumb desktop layout, not evidence-image rights or the phone adaptation.

### Desktop paging, card proportions and creation entry (Human-approved, 2026-10-19)

- Paginate actual Site records: cards four per page, dense list ten. Number/previous/next navigation
  preserves applied query criteria and URL history; data-criterion changes and view-mode changes
  return to page one. Do not show page controls for a single page or fake an empty result for a bad index.
- Bound gallery card width and use a cover aspect ratio; never stretch cards indefinitely to fill a wide
  workspace or crop content/actions to force a fixed overall ratio. Additional columns are appropriate
  when content fits on very wide desktops. Explicit page navigation returns attention to the results start.
- Append a distinct `새 현장 추가` utility tile on the last card page, after actual records. It is not a
  Site, never participates in counts/sorting/page math, and must not manufacture an extra data page.
  Stretch alongside a peer; when alone use a modest minimum height instead of a giant empty card.
- The tile and toolbar entry use the exact same allowed/denied/unavailable registration availability.
  A denied tile explains on click; unavailable can retry the lookup; only an allowed tile links to the
  existing registration route. Never infer bootstrap capability from an Admin role or invent a grant flow.

This pagination applies to the desktop presentations. The accepted phone/tablet collection and Home
remain unchanged; viewport layout and creation affordances do not alter authorization or media rights.

### Action feedback (Human-approved, 2026-10-19)

Choose the delivery surface by what the person must do next, not by treating every message as an alert:

| Situation | Surface |
|---|---|
| Short reason an action cannot run (permission or capability) | Click-triggered, non-modal `ActionUnavailable` popover beside the action; no permanently stacked helper line |
| A real additional choice or protected decision | Modal dialog; do not invent an access-request flow where none exists |
| Verified copy/save/share success | Dismissible polite toast through `ToastProvider`; no focus theft or toolbar height change |
| Missing or invalid form input | Beside the relevant field; preserve entered values |
| Failed read, failed long-running task, or uncertain mutation response | Persistent feedback in the affected area with a valid retry/recovery path; never toast-only |
| Destructive/no-undo action, or a consequential workflow stop (archive, close, cancel) | `ConfirmDialog` naming the object and real consequence before the existing mutation; cancel/Escape sends no request |

An explanation trigger is a real keyboard/touch-accessible button, not an inert disabled span or a
hover-only tooltip. Use a short label and lock icon; opening the explanation grants no permission and
sends no mutation. Keep the popover within the viewport and close it with Escape, outside click, or
its close control. Restore focus when dismissed by keyboard.

Distinguish a confirmed permission denial from an unavailable permission lookup. Neither permits
execution; only the latter should offer to retry the lookup. Direct denied routes, unavailable reads,
empty states, ongoing progress, and quantitative evidence limitations still belong in the page.
Compact-width operation restrictions remain `ResponsiveActionBoundary`'s responsibility, not a
permission popover's. Routine explanation popovers must not become blocking dialogs.
Do not call a reversible operation irreversible: work closure stops new submissions but the existing
reopen action remains available under its original permissions.

## Prohibited patterns

- Hero pages, marketing CTA ladders, email capture, social proof, or fake KPIs in the product shell.
- WebGL/Three.js, faux 3D controls, heavy shadows, skeuomorphism, parallax, or decorative maps.
- Generic AI chat as a replacement for the site briefing and citations.
- A `VERIFIED`, `ready`, `automatic`, or `safe` claim without the corresponding Core/HIL evidence.
- Hiding blocked mobile actions silently, or using viewport width as an authorization decision.

## Review checklist

- [ ] Does the screen begin with a real, scoped question rather than an internal system state?
- [ ] Can a user reach the source evidence and the related site without knowing an ID?
- [ ] Is there one primary action, and is it permitted for this viewport and role?
- [ ] Does the page remain readable at 390, 768, 1024, and 1440px without horizontal overflow?
- [ ] Are focus, touch target, reduced motion, empty, loading, error, and partial-failure states covered?
- [ ] Are all images and quantitative claims grounded in real, scoped artifacts?
