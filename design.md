# Design — CodeReviewer

A locked design system for this app. Every page redesign reads this file before emitting code.
Do not regenerate per page — extend or amend this file when the system needs to grow.

Produced by `hallmark redesign` on 2026-09-20 against the target `frontend/src/` — a **multi-page**
redesign (`scope: app`). Genre and theme evidence came from the `inspo` MCP archive (24
developer-tool / AI sites), with Sourcegraph's real CSS custom properties as the palette anchor.

## Genre
modern-minimal, technical register.

Measured consensus over those 24 sites: paper band **dark** (67%), display class **grotesk-sans**
(79%), accent hue split **cool 38% / warm 38%**. modern-minimal is chosen deliberately because it
loosens the zero-chroma neutral gate — this system's neutrals sit at chroma 0.004–0.014, which would
otherwise trip it.

## Macrostructure family
- Marketing pages (`ProblemsPage`): **Feature Stack** — hero with CTA, then an ordinal step
  sequence, then the catalogue.
- App pages (`WorkspacePage`): **Workbench** — a sticky brief rail beside a single working column
  that stacks editor → test results → AI review.
- Content pages: not applicable.

## Theme
Anchored on Sourcegraph's live tokens (`oklch(16% .00284 27deg)` paper, `oklch(57% .2 265deg)`
accent, `oklch(41% .13 265deg)` accent-muted), with the neutral hue moved 27° → 265° so the blacks
lean blue rather than red.

- `--color-paper`        oklch(14% 0.004 265)
- `--color-paper-2`      oklch(17% 0.006 265)
- `--color-paper-3`      oklch(20% 0.008 265)
- `--color-ink`          oklch(96% 0.004 265)
- `--color-ink-2`        oklch(74% 0.010 265)
- `--color-ink-3`        oklch(58% 0.012 265)
- `--color-rule`         oklch(26% 0.010 265)
- `--color-rule-2`       oklch(33% 0.014 265)
- `--color-accent`       oklch(58% 0.19 265)
- `--color-accent-hover` oklch(64% 0.19 265)
- `--color-accent-muted` oklch(38% 0.10 265)
- `--color-accent-ink`   oklch(14% 0.02 265)
- `--color-focus`        oklch(66% 0.20 265)
- `--color-ok`           oklch(72% 0.13 155)
- `--color-warn`         oklch(78% 0.12 75)
- `--color-bad`          oklch(68% 0.15 25)

### Accent discipline
"Dark blue" cannot be the accent everywhere. `--color-accent-muted` (L 38%) on `--color-paper`
(L 14%) is roughly **2.3:1** — it fails WCAG for text. So the dark blue carries **surfaces, borders
and secondary fills**, while one brighter blue (`--color-accent`, ≈**4.7:1** on paper) is reserved
for the primary CTA, links and the focus ring. Accent coverage target: ≤ 5% of any viewport.

## Typography
- Display: Space Grotesk, weight 500, normal
- Body:    Inter, weight 400
- Mono:    JetBrains Mono, weight 400
- Display tracking: -0.03em
- Type scale anchor: `--text-display` = clamp(2.25rem, 5vw, 3.75rem)

Display → section-heading ratio is held at ≈**2.34:1** (Sourcegraph runs 80px → 34px = 2.35:1), and
section headings stay at a **light weight**. That ratio and the light subhead are this genre's
signature, and they are what keep the page from reading as a generic template.

## Spacing
4-point named scale on Sourcegraph's detected rhythm (4 / 12 / 16 / 24 / 32 / 56 / 88). Values live
in `tokens.css`. Pages must use named tokens (`var(--space-md)`), never raw values.

- Section rhythm: ONE value — `--space-3xl` = `clamp(4.5rem, 10vw, 8.75rem)` — at every seam.
- Containers get `padding-inline` only. Never the `padding` shorthand: it outranks
  `section{padding-block}` on the same element and silently zeroes the rhythm.

## Motion
- Easings: `--ease-out` cubic-bezier(0.16, 1, 0.3, 1) · `--ease-in` cubic-bezier(0.7, 0, 0.84, 0) ·
  `--ease-in-out` cubic-bezier(0.65, 0, 0.35, 1). The browser default `ease` is never used.
- Reveal pattern: **none.** No scroll reveals anywhere. Exactly two animations exist in the app — the
  review panel's entrance fade, and the beams background's opacity pulse.
- Animate `transform` and `opacity` only — never layout properties.
- Reduced-motion fallback: opacity-only, ≤ 150ms.

## Microinteractions stance
- Silent success. No toasts, no celebratory animation when tests pass.
- Hover tooltips delay 800ms; focus tooltips 0ms.
- `:focus-visible` rings appear instantly and are never animated.
- No confirmation dialogs — re-run and re-review are idempotent.

## CTA voice
- Primary: solid `--color-accent` fill, `--radius-input` (8px) corners, `--text-sm` at weight 500,
  near-black label (`--color-accent-ink`), sentence case.
- Secondary: transparent fill, `--color-rule-2` hairline, `--color-ink-2` label, same radius and
  padding rhythm.
- Pills are reserved for status chips only.

## Per-page allowances
- Marketing pages MAY use enrichment. This project's enrichment is the existing `BeamsBackground`
  canvas, already perf-guarded (30fps cap, `MAX_DPR` 1.5, visibility pause, reduced-motion).
- App pages MUST NOT add enrichment — function carries the page. By explicit user decision the beams
  background still renders behind the workspace; it is inert and sits in its own fixed layer, so no
  *new* enrichment is added to app pages.
- Content pages: typography only.

## What pages MUST share
- The wordmark: `Code` + `Reviewer`, second word in `--color-accent`.
- The accent colour and its placement (≤ 5% per viewport).
- The display + body + mono fonts.
- The CTA voice (radius, padding rhythm, sentence case).
- Section heading rhythm: display-scale heading, light weight, no kicker above it.

## What pages MAY differ on
- Macrostructure within the page-type family.
- Hero archetype.
- Enrichment — marketing pages only.

## Deliberate removals
- **The `.eyebrow` kicker pattern** — banned by the skill's slop test (gate 54, the tag-above /
  tag-beside-heading pattern). Removed from all four screens; section headings now stand alone.
- **The `body` radial-gradient** — `radial-gradient(circle at 50% -20%, #162235 0, #090d14 45%)`
  replaced with flat `--color-paper`, since the beams canvas supplies the atmosphere and plan.md asks
  to avoid excessive gradients.
- **DM Sans**, and the bright `#78a9ff` / `#79a7ff` accent pair it shipped with.

## Exports

The live tokens are the `:root` block appended to `frontend/src/styles.css` — that file is the
project's entry stylesheet and is append-only per the skill's contract. `tokens.css` at the repo root
is the portable mirror of that block.

The Tailwind v4 `@theme` and shadcn/ui variable blocks are **deliberately omitted**: this project has
neither Tailwind nor shadcn, project memory records that adding them is out of scope, and emitting
dead config would be worse than omitting it. See `export-formats.md` in the skill for the canonical
mapping if that ever changes.

### tokens.css
See [`tokens.css`](tokens.css) at the repo root.

### DTCG tokens.json
```json
{
  "color": {
    "paper":        { "$value": "oklch(14% 0.004 265)", "$type": "color" },
    "paper-2":      { "$value": "oklch(17% 0.006 265)", "$type": "color" },
    "paper-3":      { "$value": "oklch(20% 0.008 265)", "$type": "color" },
    "ink":          { "$value": "oklch(96% 0.004 265)", "$type": "color" },
    "ink-2":        { "$value": "oklch(74% 0.010 265)", "$type": "color" },
    "ink-3":        { "$value": "oklch(58% 0.012 265)", "$type": "color" },
    "rule":         { "$value": "oklch(26% 0.010 265)", "$type": "color" },
    "rule-2":       { "$value": "oklch(33% 0.014 265)", "$type": "color" },
    "accent":       { "$value": "oklch(58% 0.19 265)",  "$type": "color" },
    "accent-hover": { "$value": "oklch(64% 0.19 265)",  "$type": "color" },
    "accent-muted": { "$value": "oklch(38% 0.10 265)",  "$type": "color" },
    "accent-ink":   { "$value": "oklch(14% 0.02 265)",  "$type": "color" },
    "focus":        { "$value": "oklch(66% 0.20 265)",  "$type": "color" }
  },
  "font": {
    "display": { "$value": "Space Grotesk", "$type": "fontFamily" },
    "body":    { "$value": "Inter",         "$type": "fontFamily" },
    "mono":    { "$value": "JetBrains Mono","$type": "fontFamily" }
  },
  "space": {
    "3xs": { "$value": "0.25rem", "$type": "dimension" },
    "2xs": { "$value": "0.5rem",  "$type": "dimension" },
    "xs":  { "$value": "0.75rem", "$type": "dimension" },
    "sm":  { "$value": "1rem",    "$type": "dimension" },
    "md":  { "$value": "1.5rem",  "$type": "dimension" },
    "lg":  { "$value": "2rem",    "$type": "dimension" },
    "xl":  { "$value": "3.5rem",  "$type": "dimension" },
    "2xl": { "$value": "5.5rem",  "$type": "dimension" }
  }
}
```
