# My-Skills

Curated collection of agent skills organized by domain category for AI coding assistants (Antigravity / Gemini / Claude Code).

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
├── presentations/
│   └── pptx-design/                         # Programmatic 16:9 slide deck design with python-pptx
│       └── SKILL.md
└── architecture/
    └── graphify/                            # Codebase knowledge graph, community detection & queries
        ├── SKILL.md
        └── references/
```

---

## Categories & Included Skills

| Category | Skill | Description |
| :--- | :--- | :--- |
| **`frontend/`** | [`native-web-app-design`](./frontend/native-web-app-design/SKILL.md) | Native-feel mobile & desktop web application engineering (`100dvh` locked flex shells, zero-jitter sticky headers, invisible scrollbars, `0ms` optimistic click activation, `onPointerDown` resource pre-warming, progressive `IntersectionObserver` + `content-visibility: auto` windowing, `O(1)` normalized deduplication) combined with editorial frontend design and Baseline Modern Web APIs. |
| **`presentations/`** | [`pptx-design`](./presentations/pptx-design/SKILL.md) | Modern, image-free widescreen (`16:9`) PowerPoint presentation engineering using `python-pptx` (card grids, terminal code windows, KPI callouts, comparison tables, and typographic hierarchy). |
| **`architecture/`** | [`graphify`](./architecture/graphify/SKILL.md) | Transforms codebases, documentation, and papers into persistent, queryable knowledge graphs with community detection and audit trails. |

---

## Global Installation (Antigravity)

Because skills are grouped inside category folders (`frontend/`, `presentations/`, `architecture/`), register each category folder in your global `~/.gemini/config/skills.json` so the one-level skill scanner discovers every skill automatically across all workspaces:

```json
{
  "entries": [
    { "path": "~/path/to/My-Skills/frontend" },
    { "path": "~/path/to/My-Skills/presentations" },
    { "path": "~/path/to/My-Skills/architecture" }
  ]
}
```
