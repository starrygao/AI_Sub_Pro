# Phase 4 UI Style Decision

**Date:** 2026-04-19
**Choice:** **Style B — Notion/Obsidian warm**

## Rationale

User picked B after reviewing A/B/C mockups at `docs/superpowers/mockups/`.

Style B characteristics:
- Warm paper background `#fafaf8`
- Amber / orange accent (`amber-500` family)
- Serif headings (`Iowan Old Style` or equivalent)
- Generous whitespace, single-column reading flow
- Rounded-2xl (12–16px) panels
- Comfortable body type (`text-sm` body, `text-xl` headings)
- Feels like a document — reading-friendly, not a dashboard

## Token mapping (to be applied in Task 1)

| Token | Value |
|-------|-------|
| Background | `#fafaf8` |
| Panel background | `#ffffff` |
| Text primary | `#2a2a28` |
| Text muted | `#706e68` |
| Accent | `amber-500 #f59e0b` |
| Accent hover | `amber-600 #d97706` |
| Border | `#e8e5db` |
| Border radius (card) | `16px` |
| Border radius (button) | `10px` |
| Headings font | `"Iowan Old Style", "PingFang SC", serif` |
| Body font | `"PingFang SC", -apple-system, sans-serif` |
| Spacing (section gap) | `2.5rem` |

## Reference mockup

`docs/superpowers/mockups/B-notion-warm.html` — preserved as visual reference during implementation.

## Out of scope

- Dark mode variant (Phase 4 stays light-first; dark mode can be added later as a token-only change)
