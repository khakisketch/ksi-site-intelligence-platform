# Mobile Prototype Agent Guide

Read [`../../AGENTS.md`](../../AGENTS.md) for shared product authority, task routing, and control
boundaries before applying this prototype's local rules.

> Harness note (2026-10-09, updated 2026-10-14): current sessions run under the OpenCode harness,
> not ChatGPT Work Mode or Codex Desktop. The host-specific preview steps (the paragraph starting
> "In ChatGPT Work Mode…") and the "Product Design plugin get-context" reference below are preserved
> historical host instructions, not current process; for preview/render work, follow the global
> OpenCode policy's design-workspace boundary and the repository's current routing.

## Prototype Instructions

### KSI A-direction product decisions

- This is an isolated design prototype using synthetic data; it must not call KSI Core or imply real device/HIL capability.
- The selected visual source is direction A: strong editorial hierarchy, ink-and-paper neutrals, compact semantic status color, squared cards, and icon-plus-label bottom navigation.
- The information hierarchy is `portfolio home -> site home -> assigned work`. The global home summarizes sites, while survey, media, maps, events, and deployed equipment remain site-scoped.
- `2D·3D World`, source/spatial data, reports, and deployed equipment are always entered from a selected site. They must not appear as global `더보기` destinations.
- Global `더보기` is limited to organization-owned equipment inventory, users/roles, audit history, personal notifications/settings, and operational support.
- The primary global-home persona is a construction-company executive or headquarters portfolio owner. The home should provide calm assurance and surface only business-impacting exceptions, not reproduce a site task queue.
- The AX navigation is `홈`, `현장`, `안건`, `질문`, `더보기`. `안건` is the user-facing projection of evidence-backed site insight cases: what changed, why it matters, what is uncertain, and what human follow-up is available. Ordinary processing and device events remain agent-managed or site-scoped.
- KSI AI summarizes evidence, answers portfolio/site questions, and prepares recommendations. It must not approve re-observation, issue missions, or control flight.
- The mobile home is a calm executive portfolio cover, not a task queue, report, or site directory: show one strong total-site count, one attention count, and at most two business-impacting site changes. Do not repeat the same status as a headline, narrative conclusion, and list heading. The `현장` destination exclusively owns the complete site list.
- The user rejected oversized poster headlines and standalone AI-briefing cards. Keep the global home compact and list-led: one restrained portfolio summary, clearly bound site/state/evidence rows for items needing attention, and a lightweight view of the remaining sites. AI stays in the dedicated `질문` destination.
- Keep AI contextual: home may expose a small `상태 설명` secondary action, while `질문` is the dedicated evidence-based conversation destination. Do not make AI the home hero or turn it into a named "AI briefing" product surface.
- Mobile may review evidence, triage events, and ask questions. Approval, mission issue, device/site state transitions, and flight preparation remain laptop-only.
- Copy should name the site, state, and next action in operator language. Avoid developer-facing IDs, contracts, and adapter terms in the primary UI.
- The first paid-product narrative is progress, spatial change, relative quantity, capture sufficiency, and evidence-grounded re-observation. Safety or obstacle monitoring must not be the default home story or synthetic example.
- The prototype's central synthetic object is a `현장 안건`, not a raw event or metric card. Every case must visibly bind one site, one evidence-backed claim, uncertainty or missing context, and a human follow-up.
- Do not claim schedule impact when schedule/WBS context is absent. Say that the impact cannot yet be determined and offer a context or site-manager follow-up instead.
- Use observed processing nouns (`원본 검증 중`, `비교 결과 준비`, `촬영 근거 부족`) rather than broad automation claims such as `자동 진행 중`.
- Preserve the rejected full-flow prototype at `?legacy=1`. The default route now uses the selected image-led, exception-focused home only; the former portfolio and observation-flow whole-home candidates are removed.
- The A/B/C study control compares only the lower home presentation: A is an observation-dated `다른 현장` list, B is a two-card `최근 업데이트` grid, and C is an executive `다른 현장` summary. Switching it must not change the attention carousel, navigation, palette, or other home content.
- The selected home uses a one-line `전체 4곳 · 확인 필요 2곳` portfolio summary instead of a poster-style two-line headline. Seocho and Gimpo are owned by the attention carousel; only Incheon and Pangyo appear in `다른 현장`, while the complete four-site directory remains owned by the `현장` destination.
- The `다른 현장` variants must not call a site `정상`, `안전`, or `문제없음`. Bind each site to the latest synthetic observation time and observed state, and phrase the summary as the absence of a current priority case rather than a broad site-health claim.
- The B update-card variant uses distinct generated synthetic assets for Incheon and Pangyo; never reuse another site's image or substitute customer/field evidence data. It surfaces only user-meaningful results and observation outcomes such as `상대 체적 비교 결과 준비` or `새 확인 안건 없음`; raw device connection, synchronization, processing-start, and adapter events stay out of the home.
- Every B update card opens a site-bound evidence summary. Copy must preserve limitations: relative results are not absolute quantity, and absence of a new case does not mean the whole site is normal or safe.
- Candidate A is the selected direction. Its attention area is a manual two-item `Carousel`: Seocho capture sufficiency and Gimpo progress context each use a distinct synthetic aerial image, site-bound claim, evidence signal, dot indicator, and explicit `1 / 2` count. Do not autoplay. Mobile swipe and visible previous/next controls must coexist; Incheon and Pangyo remain in the fixed `나머지 현장` list below.

(Historical host instruction — see harness note.) In ChatGPT Work Mode, run `sites-preview start "$PWD"`, open `http://terminal.local:4173/` in the cloud browser, and verify the rendered app and its primary interactions. Keep that preview open and tell the user to inspect it in the cloud browser; do not present the local URL as a user-facing chat link. In Codex Desktop, run the local server yourself, open the preview in the in-app browser, and provide the clickable local URL. Do not deploy to Sites unless the user explicitly asks to share, publish, or deploy. Do not give the user server-start instructions when you can run it.

Before planning or implementing any mobile-app change, read this `AGENTS.md` in full. It is the source of truth for the template's runtime and component guidance.

(Historical plugin instruction — see harness note.) Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

## Editing Boundary

- Build app-specific UI in `src/Prototype.tsx` and `src/prototype.css`.
- Treat `src/App.tsx`, `src/main.tsx`, `src/styles.css`, `src/mobile/`, `public/assets/iphone/`, `public/assets/android/`, `public/assets/status/`, `vite.config.ts`, `worker/index.js`, and `scripts/prepare-sites-build.mjs` as protected runtime files. Do not edit, replace, remove, or recreate them unless the user explicitly asks to change the mobile runtime itself. For an explicit runtime change, update the affected lock hashes only after verifying the new runtime behavior.
- Run `npm run check:runtime` before preview or handoff. If it fails, restore the protected runtime instead of weakening or bypassing the check.
- `npm run build` preserves the mobile runtime and prepares the static Cloudflare Worker output required by Sites. Before a Sites handoff, confirm `dist/client/index.html`, `dist/server/index.js`, `dist/.openai/hosting.json`, and source `.openai/hosting.json` exist, then run `npm run test:sites`. Do not replace this project with a Vinext starter.

## Runtime Contract

- Preserve the mobile device runtime unless the user's task explicitly asks otherwise. Do not replace it with a standalone page. Visual fidelity applies to app-owned content inside the device screen, not to template-owned device chrome.
- Keep `App` composed around `PhoneFrame` -> `KeyboardProvider`, with `StatusBar`, app content, `HomeIndicator`, and `KeyboardDock` mounted inside the phone frame. `StatusBar` and the iOS home indicator are overlaid device chrome. When the Android keyboard is closed, the app viewport reserves the protected navigation-bar region instead of painting behind it. When the Android keyboard is open, preserve the current full-screen keyboard layout: its asset includes the IME navigation strip and the separate black navigation bar is hidden. iOS screens continue to paint behind the home-indicator area and own their safe-area content padding.
- Preserve the `iPhone` / `Pixel 10` device picker and both calibrated device presets. The Pixel screen is `427 x 952`; its `32 x 32` camera circle and `public/assets/android/navigation-bar.svg` bottom navigation bar are protected device chrome, not app content.
- Preserve the device picker's intentionally lightweight Codex styling in the top-right corner: its trigger wrapper is borderless and transparent, its trigger sizes to content, and its right-aligned menu uses the compact 3px inset plus the specified hairline and elevation shadow layers. Keep the prototype root and default app screen white.
- Preserve `StatusBar` as live device chrome, including its platform-specific typography, source status-icon assets, and spacing. Pixel 10 uses Roboto, Android indicators, and 32px top, left, and right padding. iPhone uses its iOS indicators, system typography, and calibrated spacing. Do not hardcode screenshot times like `9:41` into the status bar, replace its real-time clock, or move status bar content into app markup unless the user explicitly asks for a fixed/mock device time.
- `PhoneFrame` owns the calibrated device frame, screen portal, device picker, camera cutout, and custom cursor. Keep device assets in `public/assets/iphone/` and `public/assets/android/`; if an asset fails to load, repair the asset path or restore the asset instead of removing the frame, keyboard, or image render.
- Use `MobileScroll` directly for simple single-screen prototypes. Use `FlowStack` for conventional multi-screen flows whose routes can own their fixed header and footer; when using it, define each route as a `FlowScreen`: `{ id, header?, headerHeight?, footer?, footerHeight?, render }`, and use `flow.push(screen)`, `flow.pop()`, and `flow.replace(screen)` from `FlowStack` render callbacks or `useFlow()` instead of introducing another router.
- Use `Carousel` for a carousel, horizontal rail, swipeable cards, image or media strip, horizontally scrollable cards, chip rail, or other horizontal collection.
- For a layered app shell—such as a persistent composer, independently presented sheet, pushed/peek sidebar, or app-wide transition—compose directly in `Prototype.tsx` rather than forcing it through `FlowStack`. Keep app-owned fixed chrome as sibling layers outside `MobileScroll`.
- When using `FlowScreen`, put route-owned fixed headers or footers in `FlowScreen.header` or `FlowScreen.footer`. Set `headerHeight` to the visible app-toolbar height; `FlowStack` adds the device's top safe-area/status-bar inset automatically. Do not include `StatusBar` or its height in the header. Set `footerHeight` to the full app-footer height. `FlowScreen.footer` is an overlay, not reserved layout space; screens using it must add their own bottom content padding such as `padding-bottom: calc(var(--flow-footer-height) + var(--mobile-safe-area-height) + 24px)` so final content can scroll above the footer while still painting behind it.
- Render only scrollable content inside `MobileScroll`; it is for content that should move with scroll and rubber-band overscroll. Keep app-owned headers, nav bars, tabs, composers, and overlays outside it. This keeps scroll physics, safe areas, keyboard insets, scrollbars, and drag click suppression active without letting content paint under fixed chrome.
- Buttons, links, cards, and images inside `MobileScroll` should still allow drag scrolling when the pointer moves beyond tap slop. Use `data-scroll-drag="ignore"` only for rare controls that must own the drag gesture themselves.
- Do not add `var(--keyboard-height)` to ordinary screen/content padding inside `MobileScroll`; the scroll viewport already shrinks above the simulated keyboard. For custom fixed composers, search bars, or toast chrome, use `useKeyboardInsets().bottomInset`. It is relative to the app viewport: Android returns `0` while the closed-keyboard viewport already reserves navigation, then returns the keyboard height while open; iOS continues to clear the home indicator while closed and ride directly above the keyboard while open. Do not pin custom bottom chrome to `bottom: 0` or only `keyboardHeight`.
- Use `KeyboardInput`, `KeyboardTextarea`, or `MobileTextField` for every text-entry control. A raw `input` or `textarea` disconnects focus, keyboard animation, safe-area insets, and attached surfaces.
- Use `BottomSheet` for phone-scoped sheets. Its props are `open`, `onOpenChange`, `title`, optional `description`, optional `snap`, and `children`; it renders through the phone screen portal and dismisses the keyboard before opening.

## Horizontal Carousels

- Use `Carousel` for horizontally draggable cards, images, media, chips, or other horizontal collections. Do not recreate these with `overflow-x`, custom pointer handlers, or a generic div.
- `Carousel` can be nested directly inside `MobileScroll`. It owns horizontal gestures and automatically yields vertical gestures to the parent.
- Never put `data-scroll-drag="ignore"` on or around a `Carousel`; doing so prevents vertical parent scrolling when a gesture begins inside it.
- Do not add CSS scroll snapping to `Carousel`; its runtime owns momentum and release motion.
- Candidate A treats each attention site as one full-width, equal-height page with a visible gutter between pages during drag. The Carousel content has max-content sizing, so size the two-page track explicitly rather than relying on child `width: 100%`. After a manual swipe, settle to the nearest page without CSS snap, and name the active site beside the dots and page count; do not crop a preview of the next card or autoplay it.
- Use `data-scroll-drag="ignore"` only when a control must prevent parent scrolling in every drag direction.

See `src/mobile/COMPONENTS.md` for the full component and gesture contract.

## Keyboard Rule

The simulated keyboard is a separate top-layer component. Before presenting anything that behaves like iOS navigation or modal UI, dismiss it first.

Call `keyboard.hide()` before:

- pushing, popping, or replacing FlowStack routes
- opening bottom sheets, action sheets, dialogs, menus, or navigation sheets
- starting transitions where the destination should not inherit text-input focus

`FlowStack` already hides the keyboard for `push`, `pop`, and `replace`. `BottomSheet` already hides it before opening. If you add new modal/sheet/navigation primitives, follow the same rule.

When a composer, search surface, or other keyboard-attached component closes, call `keyboard.hide()` in the same event before changing that component's open state. Position attached surfaces from `useKeyboardInsets()` rather than a separate timer or visibility flag so both dismiss together.

When any text-entry control loses focus, dismiss the simulated keyboard. If the control is custom or does not use the runtime's keyboard-aware fields, handle its blur event and call `keyboard.hide()` explicitly. Keep the keyboard open only when focus is moving directly to another text-entry control that should share the same keyboard session.

## Interaction Rules

- Do not trigger buttons or inputs after a pointer has become a drag. Preserve the drag suppression behavior in `MobileScroll`.
- Do not allow native browser image/file dragging inside the phone frame. Preserve the phone-level `dragstart` suppression and non-draggable image styles so scroll drags that begin on images still scroll the prototype.
- Use `KeyboardInput`, `KeyboardTextarea`, or `MobileTextField` for text entry so the simulated keyboard and safe-area insets stay connected.
- Fixed phone chrome should not animate with pushed screens. Screen content can animate; the status bar, camera cutout, and preview chrome should stay put.
- Keep the keyboard below the home indicator/safe area layer in z-index, and above ordinary app UI while visible.
- Keep the home indicator as the topmost safe-area layer in the z-index above everything else in the prototype.
