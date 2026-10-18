# My-Skills

Curated collection of agent skills organized by domain category for AI coding assistants (Antigravity / Gemini / Claude Code / Codex).

---

## Directory Structure by Category

```text
My-Skills/
├── skills.json                              # Portable manifest registering all category directories
├── frontend/
│   └── native-web-app-design/               # Native-feel PWA & web app architecture + UI/UX craft
│       ├── SKILL.md
│       └── references/
│           └── patterns-and-snippets.md
├── security/
│   └── github-publish-guard/                # Pre-publish GitHub ToS, trademark, binary & secret auditor
│       ├── SKILL.md
│       └── scripts/
│           └── audit-repo.ps1
├── presentations/
│   └── pptx-design/                         # Programmatic 16:9 slide deck design with python-pptx
│       └── SKILL.md
├── architecture/
│   └── graphify/                            # Codebase knowledge graph, community detection & queries
│       ├── SKILL.md
│       └── references/
└── media/
    └── reel-maker/                          # Beat-synced branded 4K vertical reels from raw clips
        ├── SKILL.md
        ├── references/
        │   └── workflow.md
        └── assets/                          # Compositor engine, project config template, helpers
```

---

## Categories & Included Skills

| Category | Skill | Description |
| :--- | :--- | :--- |
| **`frontend/`** | [`native-web-app-design`](./frontend/native-web-app-design/SKILL.md) | Native-feel mobile & desktop web application engineering (`100dvh` locked flex shells, zero-jitter sticky headers, invisible scrollbars, `0ms` optimistic click activation, `onPointerDown` resource pre-warming, progressive `IntersectionObserver` + `content-visibility: auto` windowing, `O(1)` normalized deduplication) combined with editorial frontend design and Baseline Modern Web APIs. |
| **`security/`** | [`github-publish-guard`](./security/github-publish-guard/SKILL.md) | Mandatory pre-publish auditor that scans working files and full git commit history for GitHub Acceptable Use Policy (AUP) compliance, forbidden executables/binaries (`.exe`, `.dll`, `.msi`, `.apk`), third-party company/trademark names in repos or binaries, leaked secrets/tokens, and third-party PII before any push. |
| **`presentations/`** | [`pptx-design`](./presentations/pptx-design/SKILL.md) | Modern, image-free widescreen (`16:9`) PowerPoint presentation engineering using `python-pptx` (card grids, terminal code windows, KPI callouts, comparison tables, and typographic hierarchy). |
| **`architecture/`** | [`graphify`](./architecture/graphify/SKILL.md) | Transforms codebases, documentation, and papers into persistent, queryable knowledge graphs with community detection and audit trails. |
| **`media/`** | [`reel-maker`](./media/reel-maker/SKILL.md) | Energetic, beat-synced, brand-styled 4K vertical reels (Reels/TikTok/Shorts) from raw phone clips: Python/OpenCV compositor (whip pans, zoom punches, flashes, letter-in titles, embers), librosa beat grid and drop detection, Demucs voice isolation with ducking, word-timed subtitles, per-shot color matching with a highlight-safe look, and a preview → 4K verification loop. |

---

## Global Installation (Antigravity)

Because skills are grouped inside category folders (`frontend/`, `security/`, `presentations/`, `architecture/`, `media/`), register each category folder in your global `~/.gemini/config/skills.json` so the one-level skill scanner discovers every skill automatically across all workspaces:

```json
{
  "entries": [
    { "path": "~/path/to/My-Skills/frontend" },
    { "path": "~/path/to/My-Skills/security" },
    { "path": "~/path/to/My-Skills/presentations" },
    { "path": "~/path/to/My-Skills/architecture" },
    { "path": "~/path/to/My-Skills/media" }
  ]
}
```
