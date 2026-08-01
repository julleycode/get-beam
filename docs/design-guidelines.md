# Design Guidelines

Last updated: 2026-07-28

## Overview

The Beam web app (`apps/web`) uses **Tailwind CSS 3.4**, **shadcn/ui** (Radix primitives), and a **warm cream** design token set defined in CSS variables. Marketing and dashboard share the Beam brand: approachable indie-SaaS, not cold enterprise gray.

## Design Stack

| Layer | Choice |
|-------|--------|
| CSS framework | Tailwind 3.4 (`tailwind.config.ts`) |
| Component library | shadcn/ui (`src/components/ui/`) |
| Icons | lucide-react (typical shadcn pattern) |
| Charts | Recharts (dashboard analytics) |
| Dark mode | `class` strategy in Tailwind (tokens in `:root` today) |

## Typography

Loaded in `src/app/layout.tsx` via `next/font/google`:

| Role | Font | CSS variable | Usage |
|------|------|--------------|-------|
| Sans (UI) | **Inter** | `--font-sans` | Body, UI chrome (`font-sans` on body) |
| Serif (display) | **Fraunces** | `--font-serif` | Headlines, marketing emphasis |
| Mono | **DM Mono** | `--font-mono` | Code, technical labels |

Serif feature setting: `font-feature-settings: "ss01" 1` on `.font-serif`.

## Color System

Tokens live in `src/app/globals.css` as HSL components (`hsl(var(--token))` in Tailwind config).

### Core palette (warm cream)

| Token | Role | HSL (from `:root`) |
|-------|------|---------------------|
| `--background` | Page background | 36 50% 96% (warm cream) |
| `--foreground` | Primary text | 273 13% 17% (deep purple-gray) |
| `--card` | Card surfaces | 37 62% 96% |
| `--primary` | Brand accent | 345 100% 60% (Beam pink) |
| `--primary-foreground` | On primary | 36 50% 96% |
| `--secondary` / `--muted` | Subtle fills | 40 45% 91% |
| `--border` / `--input` | Borders | 36 15% 88% |
| `--ring` | Focus ring | 345 100% 60% |
| `--radius` | Corner radius | 0.75rem |

### Semantic status (warm-tuned)

Designed to sit on cream—not clinical SaaS green/blue defaults.

| Token | Purpose |
|-------|---------|
| `--success` / `-foreground` / `-muted` | Positive states |
| `--warning` / `-foreground` / `-muted` | Caution |
| `--info` / `-foreground` / `-muted` | Informational |
| `--destructive` / `-foreground` / `-muted` | Errors |

### Intent score ramp (Visitors UI)

| Token | Meaning |
|-------|---------|
| `--intent-high` | High intent (brand pink) |
| `--intent-medium` | Medium (amber) |
| `--intent-low` | Low (muted purple-gray) |

## Tailwind Mapping

`tailwind.config.ts` extends theme colors to reference CSS variables, e.g.:

- `bg-background`, `text-foreground`
- `bg-primary`, `text-primary-foreground`
- `bg-success-muted`, `text-warning-foreground`
- `rounded-lg` uses `--radius`

Use semantic tokens—not raw hex—in components.

## shadcn/ui

Components under `src/components/ui/` follow shadcn patterns:

- `button`, `card`, `dialog`, `table`, `skeleton`, etc.
- Variants via `class-variance-authority` + `cn()` from `@/lib/utils`

When adding UI, prefer extending existing shadcn components over one-off styles.

## Layout Patterns

### Dashboard shell

- Main scroll area may use `.bg-pixel-sky` — soft sky-blue gradient with pixel-art cloud tile fading into cream
- Cards on cream/sky backgrounds with `card` token
- Skeleton loading: `.skeleton` shimmer (respects `prefers-reduced-motion`)

### Marketing (`public/beam/`)

Static JS scenes (`beam-scene.js`, `onboarding-app.js`) complement React routes. Keep visual language aligned with cream + pink accent.

## Component Guidelines

| Practice | Detail |
|----------|--------|
| Spacing | Tailwind scale; cards use consistent `p-4` / `p-6` patterns in dashboard |
| Buttons | Primary = brand pink; destructive for irreversible actions |
| Tables | shadcn `Table` for visitor/campaign lists |
| Forms | react-hook-form + zod; label + error text from shadcn form patterns |
| Empty states | Muted foreground text; avoid harsh pure gray |

## Accessibility

- Focus rings use `--ring` (pink) — ensure visible on cream backgrounds
- Skeleton animation disabled under `prefers-reduced-motion`
- Body `-webkit-font-smoothing: antialiased`
- Use semantic HTML in shadcn components (Radix handles many a11y roles)

## Do Not

- Introduce a second primary accent unrelated to `--primary` pink without design reason
- Use default shadcn zinc/slate theme without mapping to warm tokens
- Hardcode colors that bypass CSS variables (breaks theming consistency)

## References

- `apps/web/src/app/globals.css` — token source of truth
- `apps/web/tailwind.config.ts` — Tailwind extension
- `apps/web/src/app/layout.tsx` — fonts
- `marketing/` — brand assets and copy references
