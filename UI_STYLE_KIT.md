# UI Style Kit

The scrapyard's own design system for its web/UI parts. It is **not** the factory
Style Bible (that one art-directs generated video/imagery via FLUX + Remotion).
This is the web equivalent: a small set of design tokens and themes that the
`frontend/` and `ui/` parts style themselves from, so an assembled app looks
coherent instead of browser-default.

## How it fits together

```
ui/design_tokens   # the data: color/type/space/radius/shadow/z scales + themes
      │
ui/theme           # renders tokens -> CSS custom properties (:root { --... })
      │
ui/css_baseline    # reset + base element styling that references those vars
      │
frontend/*, ui/*   # components use var(--color-primary), var(--space-4), ...
```

A part never hardcodes a hex or a pixel; it references a token variable, so
switching the whole look is one theme change on `<html data-theme="...">`.

## Themes (derived from the factory Style Bible)

| Theme | Mode | Source spec | Feel |
|---|---|---|---|
| `bento` | dark | `style-bible/styles/bento-dashboard.md` | Glassmorphic SaaS; aurora violet/cyan |
| `keynote` | dark | `style-bible/styles/keynote-gloss.md` | Apple-launch minimal; single blue accent |
| `swiss` | light | `style-bible/styles/swiss-international.md` | Editorial grid; one red accent |

The palette hexes are traced directly to those specs (e.g. Swiss red `#E30613`,
aurora violet `#7C5CFF`). Add a theme by adding one entry to `THEMES` in
`design_tokens.py` with the same color keys — the selftest enforces key parity.

## Token categories

- **color** — base, surface, border, primary, accent, success, warning, danger,
  text, text_muted (per theme)
- **font** — sans, mono · **text** — xs…4xl · **weight** · **leading**
- **space** — 4px scale (0…12) · **radius** — none/sm/md/lg/full
- **shadow** — sm/md/lg · **z** — dropdown/sticky/modal/toast

## Quick start

```python
from scrapyard.frontend.forms import render_form
from scrapyard.ui.css_baseline import render_document

body = render_form("/login", [{"name": "email"}, {"name": "pw", "type": "password"}])
page = render_document(body, theme="bento", title="Sign in")   # full themed HTML doc
```

Or wire the pieces yourself:

```python
from scrapyard.ui.theme import render_css_variables      # :root { --color-...: ... }
from scrapyard.ui.css_baseline import render_baseline_css  # reset + base styles
```

## Contract for new UI parts

Same as every scrapyard part: one `### PART-META-JSON` block, `STATUS = "core"`
only when implemented and the selftest passes, and a real `_selftest()` that
asserts the rendered HTML contains the expected structure **and** escapes user
input. New components must style via `var(--token)` — never hardcode colors or
spacing — so they inherit whatever theme the build applies.

## Roadmap (component parts to stock on this foundation)

Primitives: button, input, select, modal, toast, tabs, card, alert, badge,
dropdown_menu, breadcrumbs, pagination_control, avatar, skeleton_loader, banner
(incl. cookie/GDPR consent), app_shell, footer.
Sections: hero, feature_grid, testimonial, faq, cta.
Adjacent: frontend/email_templates, frontend/error_pages.
Interactivity: an optional `ui/behaviors` layer of small vanilla-JS parts
(modal open/close, toast, tabs, client-side validation) — drop-in, no build step.
