---
name: native-web-app-design
description: >-
  Comprehensive architecture and UI/UX skill for building native-feel mobile and desktop web applications (PWAs, media players, dashboards, SaaS shells). Combines battle-tested native-shell engineering (locked 100dvh flex viewports, zero-jitter sticky headers, invisible scrollbars, 0ms optimistic click feedback, onPointerDown resource pre-warming, progressive IntersectionObserver + content-visibility windowing, O(1) normalized deduplication, offline CacheStorage/Blob engines) with the popular Frontend Design (anti-generic editorial aesthetics) and Vercel Web Interface Guidelines + Baseline Modern Web APIs. Trigger whenever designing, refactoring, or optimizing a web app UI, mobile web shell, PWA, or interactive list-heavy interface.
---

# Native-Feel Web App Design & Frontend Craft

This skill fuses three pillars into a single operational standard:
1. **Native App-Shell Engineering** (zero-jitter `100dvh` flex viewports, invisible scrollbars, no rubber-band bounce, 0ms optimistic activation, progressive list windowing, and offline-first resilience).
2. **Frontend Design Direction** (inspired by the popular *Anthropic `frontend-design`* skill: distinctive typographic hierarchy, mineral/editorial color systems, tactile dark surfaces, and zero generic AI-slop gradients).
3. **Web Interface Guidelines & Baseline Web APIs** (inspired by *Vercel `web-design-guidelines`* and *`modern-web-guidance`*: sub-50ms INP, `content-visibility: auto`, native `<dialog closedby="any">`, safe-area insets, and hardware media controls).

For complete copy-pasteable CSS and React implementation patterns, read [patterns-and-snippets.md](./references/patterns-and-snippets.md).

---

## 1. Native App-Shell & Viewport Lock (Zero Header Jitter)

Web pages feel like "websites" instead of native apps when scrolling a list tugs the document body, bounces at the edges, or jitters sticky headers on the first scroll frame.

### Mandatory Rules
1. **Disable Document Rubber-Banding**:
   - Apply `overscroll-behavior: none;` (or `overscroll-behavior-y: none;`) on both `html` and `body`.
2. **Lock the App Shell to `100dvh`**:
   - Never rely on `position: sticky` inside a window-scrolling document when building tabbed views (`Explore`, `Library`, `Feed`, `Chat`).
   - Instead, lock `.app-shell` to `height: 100dvh; max-height: 100dvh; display: flex; flex-direction: column; overflow: hidden;`.
   - Give the active tab container `flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden;`.
   - Make the top header / filter bar / search zone a stationary flex child (`flex-shrink: 0`) and make **only the list container** scrollable (`flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain;`).
   - **Why**: Because the header is outside the scroll container, the first touch/wheel scroll moves **0px** of the header—eliminating initial scroll jitter completely.
3. **Invisible Native Scrollbars**:
   - Keep native momentum scrolling active while hiding visual scrollbar tracks across all scrollable areas:
     - Standard: `scrollbar-width: none; -ms-overflow-style: none;`
     - WebKit/Blink fallback: `*::-webkit-scrollbar { width: 0; height: 0; display: none; }`

---

## 2. Instantaneous 0ms Interaction & INP Optimization

Users perceive any delay > 50ms between tapping a row and seeing its active state as "laggy," even if the delay comes from audio/network/cache preparation.

### Mandatory Rules
1. **Decouple Visual Activation from Async Work (`optimisticItem`)**:
   - On the very first line of an item's `onClick` handler, synchronously set an `optimisticSelectedId` / `optimisticTrack` state so the row's `.playing` / `.active` visual style paints on the **next frame (0ms)**.
   - Never `await` network requests, `CacheStorage` lookups, or modal confirmations before applying the visual active state.
2. **Pre-Warm Resources on `onPointerDown`**:
   - `pointerdown` fires 50–120ms *before* `click` completes. Attach an `onPointerDown` handler on interactive rows to warm `CacheStorage` blobs, prefetch route data, or decode audio in the background before `onClick` even fires.
3. **Keep `O(N × M)` Scans Out of Click & Render Paths**:
   - Never run `.find()` or regex string normalizations across large arrays inside `renderRow` or `onClick`.
   - Memoize string normalizations in a module-level `Map` (`dedupKeyMemo`) and build `O(1)` lookup indices (`useMemo` returning `{ byId: Map, byFile: Map, byDedup: Map }`).
   - Defer non-critical background work (such as pre-warming the next 10 items in a queue) inside `setTimeout(..., 80–100)` so it never competes with the click paint frame.

---

## 3. Progressive List Rendering & Decoupled State (Spotify Pattern)

Rendering 500+ DOM nodes with thumbnails and SVG actions freezes mobile GPUs, yet slicing the data array directly breaks features like Shuffle, Search, or Select-All.

### Mandatory Rules
1. **Separate Data Queue from Rendered DOM Window**:
   - Keep the full dataset (`fullList`, e.g., 700 items) intact in memory for instant search, filtering, and Fisher–Yates index-array shuffle (`order = [42, 7, 198, ...]`).
   - Slice **only the JSX output**: `fullList.slice(0, visibleCount).map(...)`.
2. **Progressive Window Expansion via `IntersectionObserver`**:
   - Start with a small initial window (`visibleCount = 10` or `15`) so initial mount takes `< 8ms`.
   - Place a 1px sentinel `<div ref={loadMoreRef} />` at the bottom of the list with `root: node.closest('.scroll-list')` and `rootMargin: '280px 0px'` to append `+15` items seamlessly before the user reaches the end.
   - Reset `visibleCount` to `10` whenever the active tab, filter, or search query changes.
3. **CSS `content-visibility: auto` on Deferred Rows**:
   - For rows past the initial fold (`idx >= 10`), apply:
     ```css
     .row-deferred {
       content-visibility: auto;
       contain-intrinsic-size: auto none auto 60px;
     }
     ```
   - This lets the browser skip layout and paint for offscreen rows while preserving scroll height.

---

## 4. Skeleton Shimmers, Compact Status Pills & Context-Aware Feed Filtering

1. **Skeleton Rows Over Text Spinners**:
   - When loading a feed or search results, render 6–8 structural skeleton rows matching the exact height and grid of real rows (`42px` cover block + two staggered text bars `54–82%` / `36–60%` + action circles) with a subtle `background-size: 200% 100%` shimmer animation (`@media (prefers-reduced-motion: no-preference)`).
2. **Two-Line Maximum for Status & Offline Banners**:
   - Never let top status/offline banners wrap into 4–6 lines on narrow mobile screens (`360px–390px`).
   - Structure banners as a flex row (`padding: 7px 11px; gap: 8px`) with a two-line left copy block (`strong` title + `span` subtitle, both `white-space: nowrap; overflow: hidden; text-overflow: ellipsis;`) and compact pill buttons (`padding: 5px 9px; font-size: 0.69rem; white-space: nowrap;`) on the right.
3. **Smart Discovery vs. Explicit Search**:
   - In **recommendation / discovery feeds**, automatically filter out items the user already owns/downloaded (`!isAvailableOffline(item)`) so every recommendation is fresh.
   - In **explicit search (`mode === 'search'`)**, include owned/downloaded items and badge them clearly inline (e.g., an accent icon + `"Descargada"` / `"Saved"` pill tag) so the user immediately sees they already have it.
4. **Hover Discipline on Touch & Hybrid Devices**:
   - Avoid permanent hover overlays or row background flashes on track/item lists when the user wants a clean, distraction-free mobile/native list; reserve visual emphasis for the active/playing row (`.row.playing`).

---

## 5. Aesthetic Direction & Web Interface Guidelines (Combined Popular Skills)

### From `frontend-design` (Anti-Generic Craft)
- **Color & Surface Hierarchy**: Prefer warm mineral dark palettes (`#0b0a09` obsidian base, `#151311` card surface, `#1e1b18` elevated surface, `#f5efe6` warm paper text, `#a69b8d` muted stone) paired with purposeful semantic accents (`#d97745` terracotta/clay primary, `#c8e667` lime success, `#c3b5f5` lavender status) over generic Tailwind indigo/purple gradients.
- **Typography**: Pair an expressive display face (`Syne`, `Cabinet Grotesk`, `Space Grotesk`, or `Instrument Serif`) for section headers with a crisp geometric sans (`Plus Jakarta Sans`, `Inter`, `Geist`) for dense UI rows and `font-variant-numeric: tabular-nums` for durations, counters, and progress timers.

### From `web-design-guidelines` & `modern-web-guidance`
- **Native Modals & Sheets**: Use semantic `<dialog closedby="any">` with `::backdrop` blur and a fallback backdrop click check for older engines.
- **Safe-Area & Dynamic Viewport**: Always pad fixed bottom bars (`player`, `bottom-nav`) with `env(safe-area-inset-bottom, 0px)` and use `100dvh` instead of `100vh`.
- **Accessibility & Motion**: Every icon-only button requires an explicit `aria-label` and `title`. Wrap shimmer and continuous animations in `@media (prefers-reduced-motion: no-preference)`.
