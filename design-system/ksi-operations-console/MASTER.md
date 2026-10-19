# KSI Operations Console Design System — Phase 1

- Status: Active design guardrail
- Date: 2026-08-24
- Product authority: `docs/architecture/05_OPERATIONS_CONSOLE_PHASE_1_STANDARD.md`
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

- Keep search full-width and always visible. Use one quiet count/`필터·정렬` disclosure row below it;
  expose status and sorting together on demand with an explicit Apply and whole reset.
- Applying phone criteria uses the latest search draft and cancels any scheduled search. Selecting
  controls alone must not apply them; closing discards unapplied choices. Search-only acknowledgements
  must not erase in-progress filter choices. Apply closes the panel and restores focus.
- Omit only the **decorative default** from phone cards so identity/status/next action/open action use
  the available width. Do not reserve an empty image gutter. This is not a ban on useful real imagery.
- At 640px and above, retain the existing tablet/desktop toolbar and default visuals. The Home hero's
  approved D6 hierarchy and geometry are outside this refinement and remain unchanged.

Use the existing native disclosure rather than adding a modal/sheet for these low-risk list choices.
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
