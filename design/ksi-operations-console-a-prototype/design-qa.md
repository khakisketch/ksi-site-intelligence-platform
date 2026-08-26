# KSI A-direction prototype design QA

- source truth: user-selected compact list wireframe; generated poster/AI-briefing images were explicitly rejected
- source pixels: not applicable
- implementation URL: `http://127.0.0.1:3220/`
- intended implementation CSS viewport: `393 x 852`, device scale factor `1`
- implementation screenshot path: unavailable
- state: portfolio home, synthetic data, unresolved event
- density normalization: not performed because no browser-rendered implementation capture was available

## Full-view comparison evidence

Blocked. The Codex in-app browser has no connected browser instance. The rendered implementation could not be captured at the required 1:1 app viewport, so a valid visual comparison was not possible. Playwright did render the implementation and verify the home hierarchy, site binding, navigation, horizontal overflow, and 44px minimum targets.

## Focused region comparison evidence

Blocked for the same reason. The intended focused regions are the compact portfolio overview, attention rows, remaining-site rows, and five-item bottom navigation.

## Findings

- [P1] Browser-rendered visual evidence is missing.
  - Location: entire prototype.
  - Evidence: runtime integrity and production build pass, and both localhost and Tailscale-IP HTTP probes return 200, but no app-viewport screenshot or console inspection could be produced.
  - Impact: typography, clipping, safe-area spacing, and actual interaction rendering cannot be accepted from source code alone.
  - Fix: reconnect the Codex in-app browser, capture `[data-phone-screen]` at `393 x 852`, test the primary interaction path, and compare it with the source image in a combined visual input.

## Required fidelity surfaces

- fonts and typography: specified in code, not visually accepted
- spacing and layout rhythm: specified in code, not visually accepted
- colors and visual tokens: source-derived ink/paper and semantic colors used, not visually accepted
- image quality and asset fidelity: no product imagery is asserted; Radix icons are used, not visually accepted
- copy and content: product-language review completed in code; visual wrapping not accepted

## Primary interactions pending browser verification

- visual hierarchy and text wrapping at the real in-app-browser zoom
- five-item bottom navigation
- site picker and notification bottom sheets
- assigned-work bottom sheet and laptop-only boundary
- event evidence review and local triage state update
- scroll, safe areas, console errors, and touch targets

## Comparison history

- Iteration 1: implementation completed and build-verified; visual comparison blocked before the first screenshot.
- Iteration 2: information architecture was corrected so `2D·3D World`, source/spatial data, reports, and deployed equipment are site-scoped; global `더보기` now contains only organization, personal settings, and support destinations. Runtime integrity, TypeScript, and production build passed again. Browser capture remains unavailable, so visual comparison is still blocked.
- Iteration 3: the product model was shifted to an exception-driven AX experience. The portfolio home now uses a cross-site KSI AI executive brief, the human queue is renamed `확인`, events are site-scoped, and a functional evidence-oriented `KSI AI` conversation was added. Runtime integrity and production build passed. The Codex in-app browser capture binding remains unavailable, so visual comparison and console inspection are still blocked.
- Iteration 4: removed the large named AI briefing, four-cell summary strip, and below-fold portfolio list from the mobile home. The home now has a compact portfolio pulse, at most two site-specific changes, a contextual `이 현황을 설명하기` action, and `현장 4개 보기`; the dedicated conversation navigation is renamed `질문`. Mobile runtime integrity and production build passed after the edit; localhost and Tailnet-IP runtime probes returned HTTP 200. Browser capture remains unavailable, so visual comparison is still blocked.
- Iteration 5: replaced the repeated narrative portfolio summary with one numeric portfolio masthead: total sites, attention count, and the two exception categories. The AI entry is now a small `상태 설명` secondary action, exception rows use a single chevron affordance, and `현장 전체 보기` is the only trailing home action. Mobile runtime integrity and production build passed; localhost and Tailnet-IP probes returned HTTP 200. Browser comparison remains blocked until a capture connection is available.
- Iteration 6: discarded the oversized portfolio masthead and all home-level AI actions. The home is now a compact list-led executive overview with one summary, two site-bound attention rows, and a lightweight remaining-site section. Three dedicated Playwright checks were added; the full suite passed 11/11, including horizontal overflow, 44px targets, site-row navigation, and global navigation. Runtime integrity and production build passed, and both localhost and Tailnet probes returned HTTP 200. In-app-browser screenshot comparison remains blocked because no browser instance is connected.

## Implementation checklist

- Capture the rendered iPhone app viewport at 1:1 scale.
- Compare source and implementation together.
- Fix all P0/P1/P2 differences and repeat the capture.
- Exercise the primary interaction path and inspect the console.

## Follow-up polish

- Test the two-exception limit and freshness copy with a real customer portfolio before taking on further global-home density.

final result: blocked
