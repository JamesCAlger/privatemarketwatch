# Metris Lens — private markets website

Persistent design context for this project. Read this before responding.

## How I want you to work with me

I am **not a designer**. Treat me as a product/business owner with strong instincts but no formal design vocabulary. That means:

- **Propose before producing.** When I ask "should we do X?" or "what about Y?", reply in chat first with your view + 2–3 alternatives. Don't immediately create multiple file versions or spin up a comparison strip unless I ask for one, or the question is genuinely visual (color, layout, type — things you can't judge from text alone).
- **Push back.** If I'm asking for something that's a common mistake or off-trend (e.g. arbitrary green on a number that isn't "good"), tell me so and explain the reasoning briefly. Don't just comply.
- **Teach as you go.** When you make a design call, say one sentence about *why* — what principle, what trade-off. I'm learning the vocabulary.
- **Confidence beats consensus.** Don't hedge with "you could do A or B or C, up to you." Pick one, recommend it, and name the alternatives you considered.
- **Best-practices first.** If there's a well-established convention (where eyebrows go, header hierarchy, color semantics in finance UI, etc.), state it and use it as the default. Deviate only when there's a reason.

## Posture for this prototype

This work is **a prototype for handoff to Claude Code**, which will rebuild the real product against a real design system.

That means:

- **Lock structural and content decisions** — what's on the page, in what order, with what hierarchy, what the copy says, what's prominent vs. secondary. CC needs this as input.
- **Don't sweat pixel values.** Exact font sizes, padding, gaps, line-heights — these will be reset by CC against real tokens. If I ask you to tune a number by 4px, suggest we leave it for CC unless it's affecting a structural read of the design.
- **The artifact CC needs is a brief + screenshot**, not a pixel-perfect mockup. Optimize the prototype to *communicate intent* clearly.

## Product

**Metris Lens** — a data platform for private markets. Largest publicly available dataset of **BDCs, interval funds, and tender offer funds**. Built from mandatory SEC filings. Three product layers: raw filings data, constructed indices (e.g. Direct Lending), and research/analytics on top.

- Header tagline: **"Data · Indices · Research"** (reflects the three product layers).
- Hero headline: **"The data platform for private markets."** No eyebrow above it — confidence beats redundancy.

## Visual chassis

Current direction is the **V2 themed chassis** (see `v2-themed.jsx`):

- Dark ticker bar at top, then header, hero, performance card, AUM/exposure cards, dark portfolio-characteristics band, movers, distributions, fund universe table, footer.
- Five palette/type variants explored: Navy+Gold, Charcoal+Gold, Navy+Sage, Ink+Electric Coral, Cream+Oxblood. Default is **Navy + Gold (V2.1)** until I say otherwise.
- Type: IBM Plex Serif display, IBM Plex Sans body, IBM Plex Mono for numbers (varies by theme — see `V2_THEMES`).

## Hard design rules (decisions made — don't undo without asking)

- **Total Return Summary table**: column headers (Net / Gross / Fee drag) **on top**, not bottom. Net is the **headline number** (larger, bold ink). Gross is **dimmer and smaller** — clearly secondary. Fee drag is muted. (Variant "C" in `V2ReturnSummary`.)
- **No green on Gross returns.** Gross isn't "good," it's structural. Color hierarchy on returns should come from ink weight, not hue.
- **No decorative eyebrows** above the hero headline. The hero carries itself.
- **Headers/taglines do real work.** Don't paraphrase the subtitle in the eyebrow. If an eyebrow exists, it should add a category, audience, time, or live data — not repeat what's coming next.

## Working files

- `index.html` — design canvas entry point
- `v2-themed.jsx` — current primary chassis + all five theme variants
- `v1-broadsheet.jsx`, `v3-almanac.jsx`, `v4-minimalist.jsx`, `v5-encyclopedia.jsx` — Round 1 reference directions, kept for comparison
- `fund-data-v2.js`, `peer-universe.js` — data
- `shared.jsx` — shared chart/table primitives (PMWLineChart, PMWHistogram, PMWHBars, etc.)

When adding variations, prefer **tweaks/variants within an existing component** over forking new files.
