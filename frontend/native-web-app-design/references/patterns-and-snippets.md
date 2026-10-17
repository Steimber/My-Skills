# Reference Patterns & Snippets for Native-Feel Web Apps

## 1. Locked `100dvh` App Shell & Stationary Header CSS

```css
html,
body {
  margin: 0;
  padding: 0;
  overscroll-behavior: none;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

* {
  scrollbar-width: none;
  -ms-overflow-style: none;
}

*::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}

/* Lock app shell when a scrollable tab-section is active */
.app-shell:has(.tab-section) {
  height: 100dvh;
  max-height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.app-shell:has(.tab-section) .main-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tab-section {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sticky-top-zone {
  flex-shrink: 0;
  z-index: 25;
  background: var(--bg);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.tab-section .track-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  padding-bottom: calc(158px + env(safe-area-inset-bottom, 0px));
}
```

---

## 2. O(1) Normalized Deduplication & Lookup Index (React)

```javascript
const dedupKeyMemo = new Map();

export function getItemDedupKey(item) {
  if (!item) return '';
  const sig = `${item.title || ''}\0${item.artist || ''}\0${item.id || ''}`;
  const cached = dedupKeyMemo.get(sig);
  if (cached !== undefined) return cached;

  const normTitle = String(item.title || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
  const normSub = String(item.artist || '')
    .split(/[,;&]/)[0]
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();

  const key = !normTitle ? String(item.id || '') : `${normTitle}|${normSub}`;
  if (dedupKeyMemo.size > 5000) dedupKeyMemo.clear();
  dedupKeyMemo.set(sig, key);
  return key;
}

// Inside component: O(1) Map lookup instead of O(N) array.find()
const catalogLookup = useMemo(() => {
  const byId = new Map();
  const byFile = new Map();
  const byDedup = new Map();
  for (const t of catalog) {
    if (!t) continue;
    if (t.id != null) byId.set(String(t.id), t);
    if (t.filename) byFile.set(t.filename, t);
    const dk = getItemDedupKey(t);
    if (dk && !byDedup.has(dk)) byDedup.set(dk, t);
  }
  return { byId, byFile, byDedup };
}, [catalog]);
```

---

## 3. 0ms Optimistic Row Activation + `onPointerDown` Pre-Warming

```jsx
<div
  className={`track-row ${idx >= 10 ? 'track-row-deferred' : ''} ${
    isActualCurrent || isOptimisticCurrent ? 'playing' : ''
  }`}
>
  <div
    className="track-row-main"
    onPointerDown={() => {
      // Fires 50-120ms before onClick: warm blob/cache in RAM
      if (isOfflineReady) warmPlayableSource(track).catch(() => {});
    }}
    onClick={() => {
      // Paint active state in 0ms on the exact click frame
      setOptimisticTrack(track);
      activateTrack(track);
    }}
  >
    {/* Row content */}
  </div>
</div>
```

---

## 4. Progressive Windowing (`IntersectionObserver` + `content-visibility: auto`)

```javascript
const [visibleCount, setVisibleCount] = useState(10);
const loadMoreRef = useRef(null);

useEffect(() => {
  setVisibleCount(10);
}, [activeTab, selectedCategory, searchQuery]);

useEffect(() => {
  const node = loadMoreRef.current;
  if (!node || typeof IntersectionObserver === 'undefined') return;
  const scrollRoot = node.closest('.track-list') || null;
  const observer = new IntersectionObserver(
    entries => {
      if (entries[0]?.isIntersecting) {
        setVisibleCount(prev => prev + 15);
      }
    },
    { root: scrollRoot, rootMargin: '280px 0px' }
  );
  observer.observe(node);
  return () => observer.disconnect();
}, [activeTab, selectedCategory, searchQuery, visibleCount]);
```

---

## 5. Compact Two-Line Mobile Status Banner

```css
.offline-pill-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 11px;
  border-radius: 13px;
  background: var(--lavender);
  color: #19132c;
  margin-bottom: 8px;
  flex-shrink: 0;
}

.offline-pill-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.18;
}

.offline-pill-text strong,
.offline-pill-text span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
```
