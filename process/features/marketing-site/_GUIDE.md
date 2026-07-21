# marketing-site

<!-- Part of Beam -->

## Scope

The public-facing surface: landing page, blog (markdown-driven), auto-generated changelog ("what's new" from merged PRs via GitHub → Gemini), founders wall, feature board, and SEO. Content strategy, brand voice, and launch assets live in the top-level `marketing/` directory — the site renders them; the strategy docs are NOT process artifacts.

Brand voice is load-bearing: anti-bot, human-sends-everything, "not a bot, just you being a human to a human". Copy that implies automation breaks positioning.

## Key Source Files

- `apps/web/src/app/blog/` — blog list + `[slug]` pages (react-markdown + remark-gfm)
- `apps/web/src/app/` landing/marketing routes, `apps/web/public/beam/` onboarding assets
- `apps/api/routers/blog.py`, `apps/api/routers/changelog*.py`, `apps/api/services/changelog_generator.py` (`CHANGELOG_SYNC_ENABLED`)
- `apps/api/routers/founders_wall.py`, feature board routers
- `marketing/` — brand/ (manifesto, voice), launch/ (copy, outreach pitches, submission kit, twitter lessons — moved from process/general-plans/references on 21-07-26), strategy/, assets/, beam-content-writer/references/product-facts.md (**source of truth for public claims**)
- Supabase Storage for blog images (`SUPABASE_*`, mock mode when keyless)

## Related Context

- `process/context/all-context.md` — What Beam Is (brand stance)
- `process/context/tests/all-tests.md` — `test_blog.py`, `test_changelog*.py`, e2e `blog.spec.ts`

## Current Status

Status: in-progress — blog + changelog live; SEO/content pipeline actively worked (see marketing/ strategy docs).

## Folder Contents

```
process/features/marketing-site/
  active/       -- in-progress plans (each task in a {slug}_{date}/ folder)
  completed/    -- archived completed plans
  backlog/      -- deferred/future plans
```

All artifacts colocate inside each `{slug}_{date}/` task folder. Do NOT create `reports/` or `references/` sibling dirs.
