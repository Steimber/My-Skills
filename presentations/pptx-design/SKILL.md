---
name: pptx-design
description: "Expert design guide and best practices for creating beautiful, modern, image-free PowerPoint presentations programmatically using python-pptx. Covers typography, card grids, color theory, code snippets, comparison tables, and visual component patterns without relying on raster images."
---

# PPTX Design & Styling Guide (python-pptx)

This skill establishes the design rules and technical standards for generating high-impact, professional, and visually compelling slide decks using `python-pptx` without relying on stock or raster images.

---

## 1. Canvas & Grid Architecture

- **Aspect Ratio:** Always use Widescreen 16:9 (`13.333"` × `7.5"`).
  ```python
  prs.slide_width = Inches(13.333)
  prs.slide_height = Inches(7.5)
  ```
- **Grid Margins:**
  - Slide Margins: Left `0.8"`, Right `0.8"`, Top `0.4"`, Bottom `0.4"`.
  - Content Area: `11.73"` width × `6.7"` height.
- **Card Spacing:** Horizontal gap between cards is `0.2"` to `0.25"`.

---

## 2. Preventing Visual Defects & "Wireframe Look"

1. **Avoid Bloated Rounded Corners:**
   Default `MSO_SHAPE.ROUNDED_RECTANGLE` has an oversized radius that looks like a capsule. **Always set `card.adjustments[0] = 0.02` to `0.025`** for subtle, modern 4px-style rounded corners:
   ```python
   if hasattr(card, 'adjustments') and len(card.adjustments) > 0:
       card.adjustments[0] = 0.025
   ```
2. **Eliminate Dead White Space at the Bottom of Cards:**
   Never leave 30-40% empty white space inside containers. Fill containers symmetrically using:
   - **Hero Metric / KPI Callout Boxes** at the top or bottom of the card (`add_metric_box`).
   - Generous body line spacing (`Pt(8)` to `Pt(12)` after paragraphs).
   - Balanced font sizing (`10.5pt` to `11.5pt` for body text).
3. **Card Header Accent Stripes:**
   Add a 3-4px colored top stripe to cards to create immediate visual hierarchy and semantic categorization (e.g., Red for Critical Risk, Cyan for Architecture, Green for SQA Validation):
   ```python
   stripe = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left + Inches(0.02), top, width - Inches(0.04), Inches(0.06))
   stripe.fill.solid()
   stripe.fill.fore_color.rgb = ACCENT_COLOR
   stripe.line.fill.background()
   ```

---

## 3. Visual Components Without Raster Images

### 1. Dark Terminal / IDE Code Windows
For code comparisons (vulnerable vs. secure), use macOS-style terminal windows:
- Dark slate background (`#0F172A`).
- Top window control dots (`🔴 #EF4444`, `🟡 #F59E0B`, `🟢 #22C55E`).
- Monospace font (`Consolas` or `Fira Code`) with syntax highlighting colors (`#F87171` for vulnerable, `#4ADE80` for secure).

### 2. Status Badges & Pill Chips
Used for severities, tags, and categories:
```python
badge = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
badge.adjustments[0] = 0.5  # Full pill radius
badge.fill.solid()
badge.fill.fore_color.rgb = C_BG_COLOR
badge.line.fill.background()
```

### 3. Hero Metric & KPI Callout Cards
Display critical metrics (`4 KB`, `CVSS 9.8`, `100x`, `Art. 19`) in dedicated mini-cards with 26-28pt bold numbers and clear subtitles.

### 4. High-Contrast Comparison Tables
- Dark header (`#0B0F19`) with bold white text.
- Alternating row backgrounds (`#FFFFFF` and `#F1F5F9`).
- Centered badges for severity columns.

---

## 4. Typography Scale (Segoe UI)

- **Slide Title:** `21` - `24 pt` (Bold, `#0F172A`)
- **Section Tag / Kicker:** `10 pt` (Bold, Uppercase, Primary Accent)
- **Card Title:** `16` - `18 pt` (Bold)
- **Body & Points:** `10.5` - `11.5 pt` (`#475569`)
- **Code / Monospace:** `9.5` - `10 pt` (`Consolas`)
- **Metric Numbers:** `26` - `32 pt` (Bold)
