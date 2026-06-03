# Phase 4 — E2E Smoke Checklist

**Date:** 2026-04-19
**Status:** Template — to be filled by user during manual testing

## How to run

```bash
cd /Users/gaopengxiang/Desktop/AI_Sub_Pro
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# then open http://127.0.0.1:8000/
```

## Scenarios (7 from spec §13.2)

### 1. Legacy upload regression
- [ ] Upload a short (≤30s) video via drag-drop
- [ ] ASR → translate → burn completes
- [ ] Output mp4 plays with Chinese subtitles
- Notes:

### 2. Trailer name search — full pipeline
- [ ] First configure TMDB API key in Settings → 预告片 section
- [ ] Go to Homepage → click "预告翻译" card
- [ ] Search "权力的游戏" (or any show you know)
- [ ] Pick show → pick season 1 → select 2 trailers → 开始翻译
- [ ] Return to Projects view, see 2 new "下载中" cards
- [ ] Wait ~5-10 min per trailer; watch status progress 下载中→识别中→翻译中→烧录中→已完成
- [ ] Play output mp4 — should show bilingual (中文 top, English bottom) hard-burned subtitles
- Notes:

### 3. Trailer — TMDB ID direct (degraded)
- Switch search mode to "按 TMDB ID", enter a numeric ID (e.g. 1399)
- Known gap: search endpoint doesn't resolve bare IDs cleanly; may return empty
- [ ] Verify graceful "未找到" empty state (no crash)
- Notes:

### 4. Config first-run
- [ ] Stop the server
- [ ] Rename `~/AI_Sub_Pro_Data/data/config.json` → `config.json.bak`
- [ ] Restart the server
- [ ] Open Settings — all defaults populated, no crash
- [ ] Restore config.json.bak
- Notes:

### 5. Concurrency
- [ ] Start 3-5 uploads simultaneously + 1-2 trailer jobs
- [ ] All complete without crash
- [ ] Check server logs for `semaphore[asr] acquiring/acquired/released` lines
- [ ] ASR concurrency capped at 2, burn at 1 (per config)
- Notes:

### 6. Claude CLI not logged in
- [ ] In Settings, switch primary provider to "Claude CLI (本机)"
- [ ] Click "检查登录状态" — if you're logged in, it should show green
- [ ] (Manual test) Log out of Claude Code via `claude logout` (if supported)
- [ ] Start a translation → UI surfaces clear error "未登录"
- Notes:

### 7. All-music trailer
- [ ] Pick a trailer that's almost entirely music (very little or no dialog)
- [ ] Pipeline completes without crashing
- [ ] Output mp4 renders — empty/sparse subtitles expected
- Notes:

## Results

| # | Scenario | Pass/Fail | Observations |
|---|---|---|---|
| 1 | Legacy upload | | |
| 2 | Trailer name search | | |
| 3 | TMDB ID degraded | | |
| 4 | First-run config | | |
| 5 | Concurrency | | |
| 6 | Claude CLI not logged in | | |
| 7 | All-music trailer | | |

## Regressions filed

Track any found bugs as follow-up tasks. Nothing blocking found during audit-gate paper review.

---

## Known UI concerns (from implementation notes)

- TMDB ID direct mode degraded (search endpoint doesn't resolve bare IDs) — future: add `/api/tmdb/resolve/{id}` route
- Season count fallback to 10 when TMDB metadata missing — acceptable
- Polish-only claude_cli use doesn't show sub-panel (only primary gates it) — edge case
- TMDB test button disabled ("即将推出") — no backend route yet
- Project detail header status pill not styled with new stage colors (only card list is) — future polish
