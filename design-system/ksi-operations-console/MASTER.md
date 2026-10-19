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
