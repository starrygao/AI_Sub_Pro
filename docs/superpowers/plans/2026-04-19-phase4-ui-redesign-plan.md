# Phase 4 — UI Redesign + Trailer Wizard + E2E Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax. UI tasks will use `frontend-design` subagents where applicable.

**Goal:** Complete the AI_Sub_Pro user-facing layer:
1. UI style redesign — let a design agent produce 2-3 candidate mockups; user picks one
2. Extract inline CSS/JS to `app/static/css/app.css` + `app/static/js/app.js` for maintainability
3. Homepage "预告翻译" entry card + view state
4. Trailer wizard (5-step: search → show → season → videos → kickoff)
5. Settings additions: claude_cli panel (model + login hint + status button), TMDB API key field, full-document toggle, status check
6. Project card stage badges (下载中/识别中/翻译中/烧录中/完成/失败)
7. KB management UI — CRUD forms for characters/places/brands/slang/style_notes
8. E2E smoke across 7 scenarios from spec §13.2

**Architecture:**
- Keep Alpine.js + TailwindCSS CDN (no framework swap)
- Single-file `index.html` stays the entry point
- Extract inline `<style>` → `app/static/css/app.css`
- Extract `x-data="app()"` payload → `app/static/js/app.js`
- New view states: `trailer` (wizard), `kb-editor` (add/edit forms)

**Testing strategy:** Backend API already unit-tested (133 tests). Frontend is manual E2E. No Playwright/Cypress for now — the effort/value ratio is poor for a single-user desktop app.

**Spec reference:** Sections 9 (frontend UI), 9.0 (追加 — UI 风格重设计), 13.2 (E2E scenarios) of `docs/superpowers/specs/2026-04-19-trailer-translation-and-foundations-design.md`.

**Out of scope (future plans):**
- Real-time WebSocket subtitle preview during translation
- Mobile responsive layout
- Browser-automated E2E tests
- Internationalization (stays 中文 UI)
- `learn()` KB auto-extraction UI (the engine stub exists, but AI-assisted term mining is a future plan)

---

## Prerequisites

`kb-redesign-complete` tag exists; 133 tests passing.

---

## Task 0: UI style mockup exploration

**Agent:** `frontend-design`
**Files:** temporary — `docs/superpowers/mockups/{A,B,C}.html` (not committed until user picks one)

### Goal

Dispatch ONE frontend-design agent to produce 2–3 **static HTML mockup pages** (no live JS, no Alpine, no API calls) demonstrating three candidate aesthetics on a shared layout. Each mockup shows the SAME screens rendered in a different style:
- Homepage (drag-drop video zone + 2 feature cards)
- Project list (≥5 project cards with stage badges)
- Settings (translation section with `claude_cli` provider condition)
- Trailer wizard step 4 (video candidates list)

### Candidate styles

- **A. Linear/Raycast** — dark-first, neutral palette (grays + single accent), small type, dense layout, keyboard-forward
- **B. Notion/Obsidian** — light-first, warm, generous whitespace, rounded (12–16px), comfortable reading type
- **C. Refined glass morphism** — keep current Apple look but reduce noise: tighter hierarchy, fewer shadows, better contrast

### Deliverable

Three standalone HTML files in `docs/superpowers/mockups/`:
- `A-linear-raycast.html`
- `B-notion-warm.html`
- `C-glass-refined.html`

Each ≤300 lines, uses TailwindCSS via CDN, no dependency on backend. Includes brief `<header>` banner naming the style and its design rationale.

### Steps

- [ ] **Step 1: Launch frontend-design agent** with the candidate styles + screen list + constraint ≤300 lines/file
- [ ] **Step 2: Review mockups in browser** — open each HTML file locally
- [ ] **Step 3: User chooses A/B/C or hybrid** — record choice in `docs/superpowers/notes/2026-04-19-ui-style-decision.md`
- [ ] **Step 4: Commit only the chosen mockup + decision note**

```bash
git add docs/superpowers/mockups/<chosen>.html docs/superpowers/notes/2026-04-19-ui-style-decision.md
git commit -m "docs(ui): choose <style> as Phase 4 UI direction"
```

Report: 3 mockup paths + user-selected style name.

---

## Task 1: Extract inline CSS/JS + apply chosen style skeleton

**Files:**
- Create: `app/static/css/app.css`
- Create: `app/static/js/app.js`
- Modify: `app/static/index.html` (remove inline `<style>`/`<script>`, add `<link>`/`<script src>`)

### Goal

1. Move everything in `index.html` `<style>...</style>` → `app/static/css/app.css`
2. Move the `app()` Alpine data object + methods → `app/static/js/app.js`
3. Replace the chosen mockup's style tokens (colors, spacing, typography) in the NEW `app.css` so the existing UI adopts the new look without changing any layout yet
4. Keep semantic class names stable (`.glass`, `.btn-primary`, etc.); just update their CSS values

### Steps

- [ ] **Step 1: Read current `index.html`** — count inline style + script lines to confirm scope
- [ ] **Step 2: Create CSS file** with exact current content, then overlay chosen-style tokens (e.g. color variables, font stacks, radii)
- [ ] **Step 3: Create JS file** with the `app()` factory function
- [ ] **Step 4: Update `index.html`** to reference the two files via `<link>` + `<script>`
- [ ] **Step 5: Boot app + open in browser** — verify visual parity for Home / Projects / Settings / Knowledge views
- [ ] **Step 6: Commit**

```bash
git add app/static/css/app.css app/static/js/app.js app/static/index.html
git commit -m "refactor(ui): extract inline CSS + JS to files; apply new style tokens"
```

Report: line counts before/after extraction, verification notes.

---

## Task 2: Homepage trailer entry card + view state

**Files:**
- Modify: `app/static/index.html`, `app/static/js/app.js`, `app/static/css/app.css`

### Goal

Below the existing drag-drop zone, add a 2-column grid with two cards:
- "完整翻译" (icon + copy) — left card, links to existing upload flow
- "预告翻译" (icon + copy) — right card, sets `view = 'trailer'` + `trailerStep = 1`

Add new view container `<div x-show="view==='trailer'">` as a placeholder; filled in Task 3.

### Alpine state additions

```js
trailerStep: 1,
trailerSearchMode: 'title',
trailerSearchQuery: '',
trailerSearchResults: [],
trailerSelectedShow: null,
trailerSeasons: [],
trailerSelectedSeasons: [],
trailerVideos: [],
trailerSelectedVideos: [],
trailerError: null,
```

### Steps

- [ ] **Step 1: Add Alpine state fields** to `app()` in app.js
- [ ] **Step 2: Insert 2-card grid** below drag-drop in index.html (use existing `.glass` class for consistency)
- [ ] **Step 3: Add trailer view placeholder** with step indicator + "🚧 Coming in Task 3" message
- [ ] **Step 4: Manually test** — homepage renders both cards, clicking "预告翻译" switches view
- [ ] **Step 5: Commit**

```bash
git add app/static/index.html app/static/js/app.js app/static/css/app.css
git commit -m "feat(ui): homepage trailer entry card + view state scaffold"
```

---

## Task 3: Trailer wizard — 5 steps

**Files:** Modify `index.html`, `app.js`, `app.css`

### Goal

Replace the Task 2 placeholder with the full 5-step wizard:

- **Step 1:** Search input (radio 按名称/按 TMDB ID + text box + 搜索 button)
- **Step 2:** Candidates list (poster 154px + 中文/原名 + year + overview → click to select)
- **Step 3:** Season picker (only when `media_type='tv'`) — season chip list + "整部剧" button
- **Step 4:** Trailer candidates (thumbnail + name + type badge + published_at + official ✓ + checkbox multi-select)
- **Step 5:** Redirect to Projects view; toast confirms N projects created

### Backend calls

- `POST /api/trailer/search` with `{query, media_type?}` → results
- `GET /api/trailer/videos/{tmdb_id}?type=tv&season=N` → videos
- `POST /api/trailer/start` with `{tmdb_id, tmdb_type, season?, video_keys[], original_language, name}` → pids

### UX rules

- Each step has: back button, progress indicator `(step/5)`, close (→ home) button
- Error panels: TMDB auth error → inline link "去设置" that switches view to settings
- Posters fallback to placeholder if poster_path null
- YouTube thumbnail: `https://img.youtube.com/vi/{key}/default.jpg`

### Steps

- [ ] **Step 1: Dispatch frontend-design agent** with full wizard spec + chosen style tokens from Task 1 — produce the HTML+JS for all 5 steps
- [ ] **Step 2: Integrate into index.html + app.js** — add methods `searchTrailers`, `selectShow`, `fetchVideos`, `startTrailerJobs`
- [ ] **Step 3: Manual test happy path** — 权力的游戏 → 选剧 → 选季 → 选预告 → 跳转 Projects → 看到 N 个新项目
- [ ] **Step 4: Manual test error paths** — missing TMDB key, empty results, no videos
- [ ] **Step 5: Commit**

```bash
git add app/static/index.html app/static/js/app.js app/static/css/app.css
git commit -m "feat(ui): trailer wizard — 5-step search/select/kickoff flow"
```

---

## Task 4: Settings additions — claude_cli + TMDB + full-doc

**Files:** Modify `index.html`, `app.js`

### Goal

In the Settings view, add:

1. **Primary provider dropdown extended** with `claude_cli` option
2. **Conditional panel** when `primary_provider === 'claude_cli'`:
   - Hide api_key input
   - Show model dropdown: `claude-opus-4-7` / `claude-sonnet-4-6` / `claude-haiku-4-5`
   - Amber warning block: "⚠️ 需要本机已安装并登录 Claude Code：运行 `claude` 命令完成登录即可。未登录时翻译会失败。"
   - "检查登录状态" button → `GET /api/settings/claude-cli/status` → color the warning block green on `{installed: true, logged_in: true}`, red on problems
3. **TMDB API key field** in a new "预告片 / TMDB" section:
   - Password input with 👁️ toggle
   - "测试" button (no-op or simple 200-OK check for now)
   - Help link to `themoviedb.org/settings/api`
4. **Full-doc toggle** (show only when `primary_provider === 'claude_cli'`):
   - Checkbox: "一次性全量翻译（利用 Claude 1M 长上下文）"
   - Persists via existing settings save → `translation.full_doc_mode`

### Steps

- [ ] **Step 1: Update Alpine state** — `showKeys: {primary: false, polish: false, tmdb: false}`, `claudeCliStatus: null`
- [ ] **Step 2: Add dropdown + conditional blocks** in settings view
- [ ] **Step 3: Wire `checkClaudeCliStatus()`** method calling the status endpoint
- [ ] **Step 4: Manual test** — switch provider to claude_cli, see panel; click 检查 → status; switch back to openai, panel hidden
- [ ] **Step 5: Commit**

```bash
git add app/static/index.html app/static/js/app.js
git commit -m "feat(ui): settings panels — claude_cli provider + TMDB key + full-doc toggle"
```

---

## Task 5: Project card stage badges

**Files:** Modify `index.html`, `app.js`, `app.css`

### Goal

In the Projects view, each project card shows a stage badge reflecting `pipeline_stage` (for trailer projects) or `status` (for upload projects).

Badge colors + labels:
| stage | color | label |
|------|-------|-------|
| download | orange | 下载中 |
| asr | purple | 识别中 |
| translate | blue | 翻译中 |
| burn | green | 烧录中 |
| completed | success | 已完成 |
| error | red | 失败 |

Progress bar uses `progress` (already global % from scheduler).

### Steps

- [ ] **Step 1: Add `statusPillClass(status, pipeline_stage)` + `statusText(status, pipeline_stage)` helpers** in app.js
- [ ] **Step 2: Update project card template** to render badge + progress bar
- [ ] **Step 3: Add CSS variants** for each color in app.css
- [ ] **Step 4: Manual test** — create a trailer project (via wizard), see "下载中" → "识别中" → etc. transitions via WebSocket
- [ ] **Step 5: Commit**

```bash
git add app/static/index.html app/static/js/app.js app/static/css/app.css
git commit -m "feat(ui): project card stage badges + colored progress per pipeline stage"
```

---

## Task 6: KB management UI

**Files:** Modify `index.html`, `app.js`, `app.css`

### Goal

In the Knowledge view, replace the read-only viewer with editable per-project cards.

For each project:
- Header: show_title + tmdb_id + buttons (保存 / 删除)
- 4 collapsible sections (characters / places / brands / slang)
- Each section has:
  - Table with columns `Source | Target | Notes | ✕`
  - "+ 添加" row at bottom
- Bottom section: Style Notes (tone / perspective / rules multi-line)

Also: top-level "+ 新建项目 KB" button → prompts for `key` + initial show_title → saves empty ProjectKb.

### Backend calls

- `GET /api/knowledge/projects` (list) and `GET /api/knowledge/projects/{key}` (full)
- `PUT /api/knowledge/projects/{key}` (save)
- `DELETE /api/knowledge/projects/{key}` (delete)

### Steps

- [ ] **Step 1: Dispatch frontend-design agent** with the KB editor spec + chosen style tokens — produce HTML+JS for the editor
- [ ] **Step 2: Integrate** — add methods `loadKbProjects`, `loadKbProject`, `saveKbProject`, `deleteKbProject`, `addKbEntry`, `removeKbEntry`
- [ ] **Step 3: Manual test CRUD** — create new, add 2 character entries, add style rules, save; reload app, entries persist; delete entries, save; delete project
- [ ] **Step 4: Commit**

```bash
git add app/static/index.html app/static/js/app.js app/static/css/app.css
git commit -m "feat(ui): KB management — per-project editor with typed categories + style notes"
```

---

## Task 7: E2E smoke (7 scenarios from spec §13.2)

**Files:** `docs/superpowers/notes/2026-04-19-phase4-e2e-report.md` (new)

### Goal

Run through the 7 E2E scenarios manually + capture pass/fail + notes:

1. **Legacy upload regression** — upload a short video, run ASR→translate→burn; verify output mp4 renders subtitles
2. **Trailer name search → full pipeline** — search "权力的游戏" → pick season 1 → select 2 trailers → wait ~10 min → both output mp4s show bilingual subtitles
3. **Trailer TMDB ID direct** — input a known movie tmdb_id → pick a trailer → complete
4. **Config first-run** — delete `~/AI_Sub_Pro_Data/data/config.json` → restart → Settings page shows defaults, no crash
5. **Concurrency** — start 5 upload jobs + 2 trailer jobs simultaneously; all complete; semaphore logs visible
6. **Claude CLI not logged in** — in Settings switch primary to claude_cli → start translation → UI shows clear error "未登录"
7. **All-music trailer** — pick a trailer that has only music (no dialog) → pipeline completes with empty SRT + music-only mp4 (no crash)

For each: capture exit status + any UI glitches + log any regressions.

### Steps

- [ ] **Step 1: Write the notes template**
- [ ] **Step 2: Run through each scenario** — fill in pass/fail + observations
- [ ] **Step 3: File any regressions** as follow-up tasks; fix blockers before declaring Phase 4 done
- [ ] **Step 4: Commit report**

```bash
git add docs/superpowers/notes/2026-04-19-phase4-e2e-report.md
git commit -m "docs(e2e): Phase 4 smoke across 7 scenarios"
```

---

## Task 8: Smoke + tag phase complete

- [ ] **Step 1:** Full test suite `python3 -m pytest -v` → expect all green
- [ ] **Step 2:** Tag `git tag phase4-ui-complete`
- [ ] **Step 3:** Audit gate — 2 parallel agents:
  - **Agent A** — UI correctness: wizard flow covers all 5 steps; error states surface; chosen style consistent across views
  - **Agent B** — Back-compat: existing upload flow still works; legacy project.json still loads; no breaking change to API routes

If any audit fails, fix before marking done.

---

## Implementation order notes

- Task 0 → 1 must be sequential (choose style first, then extract)
- Tasks 2–6 can be done in any order after Task 1 (they touch the same files but don't collide badly)
- Task 7 must be last (depends on everything above)
- Each task should produce a working app at its boundaries — don't leave the UI broken between commits

---

## Risk register

| Risk | Mitigation |
|-----|-----------|
| Design agent produces bloated HTML | Hard 300-line cap in Task 0 prompt; reject if exceeded |
| Chosen style doesn't match existing semantic classes | Map tokens to existing class names in Task 1; don't rename classes |
| Inline extraction breaks subtle CSS ordering | Keep identical selector order in the new .css file |
| Alpine state object too large for one file | If app.js grows >500 lines, split into modules; but start with single file |
| TMDB / claude_cli API errors surface badly in UI | Each request wrapped in try/catch with Chinese error toast |
| Trailer wizard state leaks between sessions | Reset `trailerStep`, arrays on view exit |
| KB editor saves race with translator read | After save, client calls GET to refresh; server-side already invalidates translator cache |
