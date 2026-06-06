/* eslint-disable */
// Methodology page — long-form editorial document. One canonical doc;
// anchor links via the TOC give per-section navigation. Reuses T_V3 / SX_V3
// and FundHeader / FundFooter from fund-chrome.jsx.

const SECTIONS = [
  { id: "universe",     num: "§1", title: "Universe" },
  { id: "pipeline",     num: "§2", title: "Data pipeline" },
  { id: "construction", num: "§3", title: "Index construction" },
  { id: "returns",      num: "§4", title: "Return calculation" },
  { id: "analytics",    num: "§5", title: "Universe analytics" },
  { id: "limitations",  num: "§6", title: "Limitations & versioning" },
];

const VERSION_HISTORY = [
  { v: "v3.1", date: "May 2026",      summary: "Common Equity index launched. Vintage-year reporting added to all equity indices." },
  { v: "v3.0", date: "January 2026",  summary: "Reconciliation layer overhaul — XBRL ↔ N-PORT cross-check now resolves ~94% of position-level discrepancies (up from 78% under v2)." },
  { v: "v2.1", date: "September 2025", summary: "Tender-offer funds added to the eligible universe. Fund universe coverage rose from $612B → $830B AUM." },
  { v: "v2.0", date: "June 2025",     summary: "Preferred Equity index launched. Eligibility rules and stated-rate normalization defined." },
  { v: "v1.1", date: "October 2024",  summary: "Industry classification migrated from internal taxonomy to GICS sector mapping." },
  { v: "v1.0", date: "March 2024",    summary: "Initial release — Direct Lending index only. Quarterly rebalance, FV-weighted construction." },
];

// ─── Shared editorial primitives ─────────────────────────────────────────────
function Body({ T, children }) {
  return <p style={{ fontSize: 16, lineHeight: 1.65, color: T.ink2, margin: "0 0 18px", maxWidth: 760 }}>{children}</p>;
}

function SubHead({ T, SX, children, id }) {
  return <h3 id={id} style={{ ...SX.display, fontSize: 22, color: T.ink, margin: "36px 0 14px", letterSpacing: "-0.01em", scrollMarginTop: 32 }}>{children}</h3>;
}

function Lede({ T, children }) {
  return <p style={{ fontSize: 20, lineHeight: 1.55, color: T.ink, margin: "0 0 28px", maxWidth: 760, letterSpacing: "-0.005em" }}>{children}</p>;
}

function Callout({ T, SX, kind = "design", title, children }) {
  const styles = {
    design:     { mark: "▸", label: "Design choice", color: T.accent, ink: T.ink },
    edge:       { mark: "◇", label: "Edge case",     color: T.ink,    ink: T.ink },
    limitation: { mark: "⚠", label: "Limitation",    color: T.amber,  ink: T.ink },
  }[kind];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 18, padding: "18px 22px", margin: "22px 0", background: T.rule3, borderLeft: `3px solid ${styles.color}`, maxWidth: 760 }}>
      <div style={{ ...SX.num, fontSize: 18, color: styles.color, lineHeight: 1.4 }}>{styles.mark}</div>
      <div>
        <div style={{ ...SX.eyebrow, color: styles.color, marginBottom: 6 }}>{styles.label} · {title}</div>
        <div style={{ fontSize: 14, lineHeight: 1.6, color: styles.ink }}>{children}</div>
      </div>
    </div>
  );
}

function ParamTable({ T, SX, rows, caption }) {
  return (
    <div style={{ margin: "20px 0 24px", maxWidth: 760 }}>
      {caption && <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 8 }}>{caption}</div>}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, border: `1px solid ${T.rule}` }}>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.k} style={{ borderBottom: i < rows.length - 1 ? `1px solid ${T.rule2}` : "none" }}>
              <td style={{ padding: "12px 18px", color: T.ink3, fontSize: 12, letterSpacing: "0.02em", width: 220, verticalAlign: "top", borderRight: `1px solid ${T.rule2}`, background: T.rule3 }}>{r.k}</td>
              <td style={{ padding: "12px 18px", color: T.ink, fontFamily: r.mono ? T.monoFont : "inherit", fontSize: r.mono ? 13 : 14 }}>{r.v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FormulaBlock({ T, SX, formula, gloss }) {
  return (
    <div style={{ margin: "24px 0 28px", maxWidth: 760, padding: "22px 26px", background: T.navy, color: "#fff" }}>
      <div style={{ ...SX.num, fontSize: 16, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{formula}</div>
      {gloss && (
        <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid rgba(255,255,255,0.14)", display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "10px 28px", fontSize: 12, color: "rgba(255,255,255,0.78)" }}>
          {gloss.map(g => (
            <div key={g.sym} style={{ display: "flex", gap: 10 }}>
              <span style={{ ...SX.num, color: T.accent, minWidth: 60 }}>{g.sym}</span>
              <span style={{ lineHeight: 1.5 }}>{g.desc}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function NumberedList({ T, items }) {
  return (
    <ol style={{ margin: "0 0 24px", padding: 0, listStyle: "none", maxWidth: 760 }}>
      {items.map((it, i) => (
        <li key={i} style={{ display: "grid", gridTemplateColumns: "44px 1fr", gap: 0, padding: "14px 0", borderTop: i === 0 ? `1px solid ${T.rule2}` : "none", borderBottom: `1px solid ${T.rule2}`, fontSize: 15, lineHeight: 1.55, color: T.ink2 }}>
          <span style={{ fontFamily: T.monoFont, fontSize: 12, color: T.accent, fontWeight: 600, paddingTop: 2 }}>{String(i + 1).padStart(2, "0")}</span>
          <span>{it}</span>
        </li>
      ))}
    </ol>
  );
}

// ─── Section wrapper ─────────────────────────────────────────────────────────
function Section({ T, SX, num, id, title, sub, children }) {
  return (
    <section id={id} style={{ scrollMarginTop: 32, padding: "60px 0 20px", borderTop: `1px solid ${T.rule}` }}>
      <div style={{ ...SX.num, fontSize: 12, color: T.accent, letterSpacing: "0.18em", marginBottom: 12 }}>{num}</div>
      <h2 style={{ ...SX.display, fontSize: 40, color: T.ink, margin: "0 0 14px", letterSpacing: "-0.02em", lineHeight: 1.05 }}>{title}</h2>
      {sub && <Lede T={T}>{sub}</Lede>}
      {children}
    </section>
  );
}

// ─── §2 Data pipeline diagram ────────────────────────────────────────────────
function PipelineDiagram({ T, SX }) {
  const stages = [
    { num: "01", title: "Ingest",      desc: "Pull raw filings from SEC EDGAR as they land.", details: ["BDC XBRL (10-K/10-Q)", "N-PORT (quarterly)", "N-CEN (annual)", "N-2 (registration)"] },
    { num: "02", title: "Reconcile",   desc: "Cross-check XBRL ↔ N-PORT position-by-position, normalize identifiers.", details: ["CUSIP / ISIN / CIK match", "Cost & FV agreement", "Look-through for FoFs", "Currency → USD"] },
    { num: "03", title: "Aggregate",   desc: "Build the position-level dataset that every metric is computed from.", details: ["27,124 DL positions", "1,267 PE positions", "2,938 CE positions", "8,412 unique issuers"] },
    { num: "04", title: "Publish",     desc: "Compute indices, universe analytics, fund-level summaries; release.", details: ["3 indices, FV-weighted", "Universe coverage stats", "Fund-level pages", "API + CSV"] },
  ];
  return (
    <div style={{ margin: "28px 0 32px", maxWidth: 1080 }}>
      <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 14 }}>The four-stage pipeline · runs end-to-end ~45 days after quarter end</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 0, border: `1px solid ${T.rule}`, background: T.surface }}>
        {stages.map((s, i) => (
          <div key={s.num} style={{ padding: "22px 22px 24px", borderRight: i < 3 ? `1px solid ${T.rule2}` : "none", position: "relative" }}>
            <div style={{ ...SX.num, fontSize: 11, color: T.accent, letterSpacing: "0.14em", marginBottom: 8 }}>{s.num}</div>
            <div style={{ ...SX.display, fontSize: 20, color: T.ink, letterSpacing: "-0.01em", marginBottom: 8 }}>{s.title}</div>
            <div style={{ fontSize: 13, lineHeight: 1.5, color: T.ink2, marginBottom: 14, minHeight: 60 }}>{s.desc}</div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
              {s.details.map(d => (
                <li key={d} style={{ fontSize: 11, color: T.ink3, padding: "4px 0", borderTop: `1px solid ${T.rule2}`, fontFamily: T.monoFont, letterSpacing: "-0.005em" }}>{d}</li>
              ))}
            </ul>
            {i < 3 && (
              <div style={{ position: "absolute", right: -8, top: "50%", transform: "translateY(-50%)", width: 16, height: 16, background: T.bg, color: T.ink3, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>→</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Hero + meta strip ───────────────────────────────────────────────────────
function MethodologyHero({ T, SX }) {
  return (
    <div style={{ padding: "56px 72px 36px", maxWidth: 1280 }}>
      <div style={{ ...SX.eyebrowAccent }}>Documentation · Independent · Rules-based</div>
      <h1 style={{ ...SX.display, fontSize: 84, lineHeight: 1.02, margin: "12px 0 22px", letterSpacing: "-0.03em", color: T.ink }}>Methodology</h1>
      <p style={{ fontSize: 19, lineHeight: 1.55, color: T.ink2, maxWidth: 760, margin: 0 }}>
        How the Metris Lens universe, indices, and analytics are constructed — from mandatory SEC filings, through reconciliation, into the position-level dataset every figure on this site is computed from. Versioned, change-logged, reproducible.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, auto)", gap: "16px 56px", marginTop: 36, paddingTop: 24, borderTop: `1px solid ${T.rule}`, maxWidth: 920, fontSize: 13 }}>
        <MetaCell T={T} SX={SX} k="Version"      v="v3.1" />
        <MetaCell T={T} SX={SX} k="Last updated" v="May 14, 2026" />
        <MetaCell T={T} SX={SX} k="Maintained by"v="Metris Research" />
        <MetaCell T={T} SX={SX} k="Format"       v="HTML · PDF · machine-readable" />
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 24 }}>
        <a href="#universe" style={{ padding: "11px 20px", background: T.navy, color: "#fff", fontSize: 13, fontWeight: 500, letterSpacing: "0.04em", textDecoration: "none" }}>Read methodology ↓</a>
        <a href="#" style={{ padding: "11px 20px", border: `1px solid ${T.rule}`, color: T.ink, fontSize: 13, fontWeight: 500, textDecoration: "none" }}>Download PDF ↗</a>
        <a href="#limitations" style={{ padding: "11px 20px", border: `1px solid ${T.rule}`, color: T.ink, fontSize: 13, fontWeight: 500, textDecoration: "none" }}>Change log →</a>
      </div>
    </div>
  );
}

function MetaCell({ T, SX, k, v }) {
  return (
    <div>
      <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 4 }}>{k}</div>
      <div style={{ fontSize: 14, color: T.ink, fontWeight: 500 }}>{v}</div>
    </div>
  );
}

// ─── TOC ────────────────────────────────────────────────────────────────────
function TOC({ T, SX, active }) {
  return (
    <aside style={{ position: "sticky", top: 32, alignSelf: "start", width: 220, paddingRight: 24 }}>
      <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 14, paddingBottom: 10, borderBottom: `1px solid ${T.rule}` }}>Contents</div>
      <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
        {SECTIONS.map(s => {
          const on = s.id === active;
          return (
            <li key={s.id} style={{ padding: "10px 0", borderBottom: `1px solid ${T.rule2}` }}>
              <a href={`#${s.id}`} style={{ display: "grid", gridTemplateColumns: "32px 1fr", gap: 0, textDecoration: "none", color: on ? T.ink : T.ink2 }}>
                <span style={{ fontFamily: T.monoFont, fontSize: 11, color: on ? T.accent : T.ink3, fontWeight: 600 }}>{s.num}</span>
                <span style={{ fontSize: 13, fontWeight: on ? 600 : 500, letterSpacing: "-0.005em" }}>{s.title}</span>
              </a>
            </li>
          );
        })}
      </ol>
      <div style={{ marginTop: 24, paddingTop: 14, borderTop: `1px solid ${T.rule}`, fontSize: 11, color: T.ink3, lineHeight: 1.5 }}>
        Last updated <span style={{ ...SX.num, color: T.ink2 }}>May 14, 2026</span>. Methodology is versioned — see <a href="#limitations" style={{ color: T.accent, textDecoration: "none", borderBottom: `1px solid ${T.accent}`, paddingBottom: 1 }}>§6 change log</a>.
      </div>
    </aside>
  );
}

// ─── Sections ───────────────────────────────────────────────────────────────
function UniverseSection({ T, SX }) {
  return (
    <Section T={T} SX={SX} num="§1" id="universe" title="Universe"
      sub="Metris Lens covers the investor-accessible side of US private credit and equity — the closed-end registered vehicles whose holdings are visible through mandatory SEC disclosure.">
      <SubHead T={T} SX={SX} id="universe-eligibility">1.1  Eligible vehicle types</SubHead>
      <Body T={T}>
        Three vehicle types make up the universe: <strong>business development companies (BDCs)</strong>, <strong>interval funds</strong>, and <strong>tender-offer funds</strong>. Listed and non-listed BDCs are both included; interval funds and tender-offer funds are closed-end registered vehicles that periodically repurchase shares from holders.
      </Body>
      <Body T={T}>
        Private funds (3(c)(7), 3(c)(1)), separately managed accounts, and offshore vehicles are <em>excluded</em> — not because they're unimportant, but because their holdings are not publicly disclosed. The universe is defined by what can be observed without information asymmetry.
      </Body>
      <Callout T={T} SX={SX} kind="design" title="Why this universe">
        These three vehicle types together represent the entirety of US private market exposure that an individual investor can access through a registered wrapper. They also share the same mandatory N-PORT / N-CEN disclosure regime, which is what makes a position-level dataset possible. Adding private funds would double the AUM coverage but eliminate the ability to do any holdings-level work.
      </Callout>

      <SubHead T={T} SX={SX} id="universe-membership">1.2  Adding and removing funds</SubHead>
      <Body T={T}>
        A fund enters the universe with its first N-PORT or N-CEN filing as one of the three eligible vehicle types. It exits the universe with its final filing — typically liquidation, conversion to a different structure, or merger into another vehicle.
      </Body>
      <Body T={T}>
        Funds in registration (filed N-2 but not yet operating) are not included; they have no holdings to analyze and are tracked separately in the launch-watch list.
      </Body>

      <SubHead T={T} SX={SX} id="universe-survivorship">1.3  Survivorship treatment</SubHead>
      <Body T={T}>
        Historical universe data includes every fund that ever filed — including those subsequently liquidated, merged, or de-registered. A fund that ran from 2019 to 2023 contributes to the 2019–2023 statistics; it is not retroactively removed when it exits.
      </Body>
      <Callout T={T} SX={SX} kind="design" title="No survivorship bias by construction">
        Index returns and universe analytics are computed as point-in-time aggregates of <em>everyone who reported that quarter</em>. There is no decision about which funds count — the answer is "all of them, then, as they reported then." This is the methodological floor for any rules-based benchmark.
      </Callout>
    </Section>
  );
}

function PipelineSection({ T, SX }) {
  return (
    <Section T={T} SX={SX} num="§2" id="pipeline" title="Data pipeline"
      sub="Every figure on this site is computed from one position-level dataset. The dataset is built by ingesting raw SEC filings, reconciling across forms, and aggregating into a normalized schema. The pipeline runs once per quarter, ~45 days after the quarter close.">
      <PipelineDiagram T={T} SX={SX} />

      <SubHead T={T} SX={SX} id="pipeline-sources">2.1  Source forms</SubHead>
      <Body T={T}>
        Four SEC form types feed the pipeline. Each captures a different facet — schedule of investments, portfolio holdings, fund census, registration — and the reconciliation layer (next subsection) is responsible for resolving discrepancies between them.
      </Body>
      <ParamTable T={T} SX={SX} caption="Source-form inventory"
        rows={[
          { k: "BDC XBRL (10-K, 10-Q)", v: "Audited / unaudited schedule of investments — position-level cost, fair value, coupon, lien position, accrual status. Filed by listed and non-listed BDCs.", mono: false },
          { k: "N-PORT",                 v: "Monthly portfolio holdings; quarterly public release. Required for interval funds, tender-offer funds, and most BDCs. Holdings broken out by issuer, security type, and reported FV.", mono: false },
          { k: "N-CEN",                  v: "Annual fund census — adviser, structure, share classes, expense ratios. The closest thing to a static fund identity record.", mono: false },
          { k: "N-2",                    v: "Registration statement (and amendments). Captures fund launch, share-class additions, eligible-investor changes.", mono: false },
        ]} />

      <SubHead T={T} SX={SX} id="pipeline-reconciliation">2.2  Reconciliation</SubHead>
      <Body T={T}>
        BDC XBRL and N-PORT both report holdings, on different schedules and with different identifiers. The reconciliation layer resolves each filing pair position-by-position, matching on CUSIP, ISIN, CIK, and a name-similarity fallback when no identifier matches.
      </Body>
      <Body T={T}>
        When the two sources disagree on fair value (a small fraction of cases — typically rounding or restatement timing), N-PORT is treated as authoritative for the published-quarter snapshot, with the XBRL value retained as a reconciliation flag and surfaced on the Data Quality page.
      </Body>
      <Callout T={T} SX={SX} kind="edge" title="Look-through for pooled vehicles">
        Some funds report holdings of other funds — fund-of-fund structures, master/feeder. We look through to the underlying positions whenever the underlying fund is itself in our universe. Where the underlying is a non-disclosing vehicle (e.g., a private fund), the holding is left at the wrapper level and tagged as opaque.
      </Callout>

      <SubHead T={T} SX={SX} id="pipeline-cadence">2.3  Cadence</SubHead>
      <Body T={T}>
        Regulatory deadlines determine the cadence: N-PORT is due 60 days after quarter end, BDC 10-Q is due 45 days after quarter end (40 for accelerated filers). The pipeline runs continuously as filings land; the official "as of" snapshot is taken 45 days after quarter end and frozen for the index rebalance.
      </Body>
    </Section>
  );
}

function ConstructionSection({ T, SX }) {
  return (
    <Section T={T} SX={SX} num="§3" id="construction" title="Index construction"
      sub="Three indices, one common construction pattern. Each index is fair-value-weighted across its eligible positions, rebalanced quarterly, and computed in gross and net terms. The differences live in the eligibility rules.">
      <SubHead T={T} SX={SX} id="construction-shared">3.1  Shared rules</SubHead>
      <Body T={T}>
        All three indices share the following construction parameters. Index-specific overrides are listed under each index below.
      </Body>
      <ParamTable T={T} SX={SX} caption="Shared construction parameters"
        rows={[
          { k: "Weighting scheme",      v: "Fair-value-weighted across eligible positions", mono: false },
          { k: "Rebalance frequency",   v: "Quarterly, ~45 days after quarter end (post N-PORT)", mono: false },
          { k: "Reconstitution",        v: "Full — universe rebuilt each quarter from current filings", mono: false },
          { k: "Base level / date",     v: "100 / January 1, 2019", mono: true },
          { k: "Currency",              v: "USD (non-USD positions converted at quarter-end FX)", mono: false },
          { k: "Return types published",v: "Gross (pre-fund-fee) and Net (post-fund-fee)", mono: false },
        ]} />
      <Callout T={T} SX={SX} kind="design" title="Why fair-value-weighted">
        Considered three alternatives: par-weighted (defensible for credit but ignores realized impairment), equal-weighted (overweights small positions and noise), and AUM-weighted (counts the same dollar twice when multiple funds hold it). FV-weighting is the only scheme where the index level corresponds directly to a hypothetical investor's exposure to the underlying assets.
      </Callout>

      <SubHead T={T} SX={SX} id="construction-dl">3.2  PMW Direct Lending</SubHead>
      <Body T={T}>
        Position-level benchmark of private debt — first lien, unitranche, second lien, subordinated, mezzanine — held by US-registered closed-end vehicles. The largest index by holdings count and by FV.
      </Body>
      <ParamTable T={T} SX={SX}
        rows={[
          { k: "Eligible security type", v: "Debt — first lien, unitranche, second lien, sub/mezz", mono: false },
          { k: "Eligible issuer",         v: "Private (no public ticker for common stock) at position open", mono: false },
          { k: "Required fields",         v: "Reported FV, cost basis, coupon, lien position", mono: false },
          { k: "Minimum hold period",     v: "1 full quarter (avoids transit / syndication noise)", mono: false },
          { k: "Exit treatment",          v: "Marked at last reported FV, removed at next rebalance", mono: false },
        ]} />

      <SubHead T={T} SX={SX} id="construction-pe">3.3  PMW Preferred Equity</SubHead>
      <Body T={T}>
        Preferred stock positions in private companies — instruments with a stated dividend rate, redemption optionality, and seniority over common stock. Smaller universe (1,267 positions across 421 issuers); structurally more volatile than direct lending.
      </Body>
      <ParamTable T={T} SX={SX}
        rows={[
          { k: "Eligible security type", v: "Preferred equity — including convertible and participating", mono: false },
          { k: "Eligible issuer",         v: "Private at position open (no public common-stock ticker)", mono: false },
          { k: "Required fields",         v: "Reported FV, cost basis, stated rate OR conversion terms", mono: false },
          { k: "IPO conversion",          v: "Marked at conversion price; position removed at next rebalance", mono: false },
          { k: "Minimum hold period",     v: "1 full quarter", mono: false },
        ]} />
      <Callout T={T} SX={SX} kind="edge" title="IPO conversion">
        When a portfolio company goes public, preferred typically converts to common. We mark the position at the conversion price (the IPO price, adjusted by the conversion ratio) and remove it at the next rebalance. The proceeds are not carried over to the index — investors who held preferred-then-common get the realized return up to conversion, the index resets.
      </Callout>

      <SubHead T={T} SX={SX} id="construction-ce">3.4  PMW Common Equity</SubHead>
      <Body T={T}>
        Direct common-equity stakes in private companies — co-investments, primary minority stakes, secondaries, and warrants. The highest-return, highest-volatility index.
      </Body>
      <ParamTable T={T} SX={SX}
        rows={[
          { k: "Eligible security type", v: "Common equity, LP interests, warrants, equity-form converts", mono: false },
          { k: "Eligible issuer",         v: "Private at position open", mono: false },
          { k: "Required fields",         v: "Reported FV, cost basis, acquisition date (98% coverage)", mono: false },
          { k: "Exclusions",              v: "Fund-of-fund and pooled-vehicle wrappers (avoid double-count)", mono: false },
          { k: "Exit treatment",          v: "Marked at IPO price or last reported FV; removed at next rebalance", mono: false },
        ]} />
    </Section>
  );
}

function ReturnsSection({ T, SX }) {
  return (
    <Section T={T} SX={SX} num="§4" id="returns" title="Return calculation"
      sub="Quarterly returns are computed from changes in position fair value plus realized cash and PIK income, divided by starting fair value. Gross is published pre-fund-fee; Net is post-fund-fee. The difference is the fee drag.">
      <SubHead T={T} SX={SX}>4.1  Quarterly return formula</SubHead>
      <Body T={T}>
        For each quarter <em>t</em>, the gross return is:
      </Body>
      <FormulaBlock T={T} SX={SX}
        formula={"R_gross(t)  =  [ Σ FV_end(i, t)  +  Σ Income(i, t)  −  Σ Loss(i, t) ]  ÷  Σ FV_start(i, t)  −  1"}
        gloss={[
          { sym: "FV_end",     desc: "Position fair value at quarter close" },
          { sym: "FV_start",   desc: "Position fair value at prior quarter close" },
          { sym: "Income",     desc: "Realized cash + PIK interest / dividends earned during the quarter" },
          { sym: "Loss",       desc: "Realized credit losses (writes from impairment, default workouts)" },
          { sym: "i",          desc: "Each eligible position in the index that quarter" },
          { sym: "t",          desc: "Quarter (1 of 4 per year)" },
        ]} />
      <Body T={T}>
        Net return is computed by subtracting an estimated fund-level fee drag from gross. The drag is calibrated quarterly from N-CEN expense ratios across the universe of contributing funds, weighted by their share of index FV.
      </Body>
      <Callout T={T} SX={SX} kind="design" title="Why a calibrated drag, not a raw aggregation">
        We could compute Net by aggregating each fund's actual reported net return, weighted by its share of index FV. Two problems: (1) fund returns include cash drag, leverage, and unrelated holdings — they are not a clean reflection of position-level performance net of fees, and (2) reporting cadences differ. The calibrated drag isolates the question Net is meant to answer: <em>what does an investor see, after the fund's standard expenses, from these underlying assets?</em>
      </Callout>

      <SubHead T={T} SX={SX}>4.2  Compounding</SubHead>
      <Body T={T}>
        Quarterly returns are geometrically chained to produce trailing-period returns (1Y, 3Y, 5Y, since-inception). Annualized figures use the standard (1 + R)^(4/n) − 1 formula where n is the number of compounded quarters.
      </Body>
    </Section>
  );
}

function AnalyticsSection({ T, SX }) {
  return (
    <Section T={T} SX={SX} num="§5" id="analytics" title="Universe analytics"
      sub="Beyond the three indices, Metris Lens publishes universe-level statistics: AUM aggregations, industry exposure, manager concentration, coverage ratios. These are computed off the same position-level dataset but with different aggregation rules.">
      <SubHead T={T} SX={SX}>5.1  AUM aggregation</SubHead>
      <Body T={T}>
        Universe AUM is the sum of total net assets across all funds in the universe at the as-of date. Total net assets is taken from N-PORT (open-end / closed-end) or 10-Q/10-K (BDC) — whichever was most recently filed.
      </Body>
      <Body T={T}>
        AUM is reported at the fund level. Manager-level and category-level aggregations sum the underlying funds; the per-vehicle AUM is never split or attributed.
      </Body>

      <SubHead T={T} SX={SX}>5.2  Industry classification</SubHead>
      <Body T={T}>
        Holdings-level industry exposure uses the GICS sector taxonomy. Mapping is done from issuer CIK or LEI to a master industry table; where neither is available, the issuer name is matched against a curated reference list. Unmapped positions are classified as "Other / Unclassified" and disclosed separately in every sector breakdown.
      </Body>

      <SubHead T={T} SX={SX}>5.3  Coverage</SubHead>
      <Body T={T}>
        "Universe coverage" is the share of eligible AUM that is fully reconciled, classified, and included in the position-level dataset. The gap to 100% comes from late-filing funds, reconciliation breaks, and positions still under review. Coverage is published on every dashboard so the reader knows how complete the snapshot is.
      </Body>
    </Section>
  );
}

function LimitationsSection({ T, SX }) {
  return (
    <Section T={T} SX={SX} num="§6" id="limitations" title="Limitations & versioning"
      sub="No methodology is without compromise. Below are the structural limitations of this one — known, named, and surfaced so readers can decide how to use the data — followed by the version history.">
      <SubHead T={T} SX={SX}>6.1  Known limitations</SubHead>
      <NumberedList T={T} items={[
        <span><strong>Quarterly cadence.</strong> All data is quarterly. Intra-quarter moves — credit deteriorations, new positions, sponsor-led recaps — are not visible until the next filing lands. The dataset is a stop-action snapshot, not a real-time stream.</span>,
        <span><strong>Reporting lag.</strong> The official "as of" snapshot is taken 45 days after quarter close. Funds that file later are included on a rolling basis but with a coverage-flag until the next official snapshot.</span>,
        <span><strong>Spread / rate coverage gaps.</strong> 64% of Direct Lending FV reports a spread over benchmark; 36% does not. The weighted-average spread is computed on the reporting subset and labelled accordingly. Same logic applies to coupon (86%), maturity (59%), and preferred stated rate (92%).</span>,
        <span><strong>Fiscal-year mismatch.</strong> A small number of BDCs (Apollo and others) report on a fiscal year that doesn't align with calendar quarters. We treat their filings as falling in the calendar quarter that contains the fiscal quarter close, accepting a small timing distortion.</span>,
        <span><strong>Private-to-public transition.</strong> When a portfolio company goes public, the position exits the index at the IPO mark and the proceeds are <em>not</em> reinvested back into the index. This makes index returns directly comparable across periods but distinct from the returns an actual fund holder would experience (who often holds through the IPO).</span>,
        <span><strong>Sector classification opacity.</strong> ~8% of Direct Lending FV is in "Other / Unclassified" — issuers we cannot reliably map to a GICS sector. This is a known reconciliation gap, not a hidden category.</span>,
      ]} />
      <Callout T={T} SX={SX} kind="limitation" title="None of these are hidden">
        Every figure on this site is labelled with the coverage subset that produced it. Where coverage is below 95%, the figure is annotated. This is the discipline that lets a reader use the data confidently: nothing is averaged across a denominator it shouldn't have been.
      </Callout>

      <SubHead T={T} SX={SX}>6.2  Version history</SubHead>
      <div style={{ maxWidth: 920, marginTop: 14 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: T.rule3 }}>
              <th style={{ ...SX.eyebrow, color: T.ink2, textAlign: "left", padding: "10px 18px", width: 80 }}>Version</th>
              <th style={{ ...SX.eyebrow, color: T.ink2, textAlign: "left", padding: "10px 18px", width: 140 }}>Date</th>
              <th style={{ ...SX.eyebrow, color: T.ink2, textAlign: "left", padding: "10px 18px" }}>Summary</th>
            </tr>
          </thead>
          <tbody>
            {VERSION_HISTORY.map((h, i) => (
              <tr key={h.v} style={{ borderBottom: `1px solid ${T.rule2}` }}>
                <td style={{ ...SX.num, padding: "14px 18px", color: i === 0 ? T.accent : T.ink, fontWeight: 600 }}>{h.v}</td>
                <td style={{ padding: "14px 18px", color: T.ink2, fontSize: 12 }}>{h.date}</td>
                <td style={{ padding: "14px 18px", color: T.ink, lineHeight: 1.55 }}>{h.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

// ─── App shell ──────────────────────────────────────────────────────────────
function MethodologyApp() {
  const T = window.T_V3, SX = window.SX_V3;
  return (
    <div style={SX.root} data-screen-label="Methodology">
      <FundHeader T={T} SX={SX} navActive="Methodology" />
      <Breadcrumb T={T} items={[
        { label: "Home", href: "index.html" },
        { label: "Methodology" },
      ]} />
      <MethodologyHero T={T} SX={SX} />
      {/* Two-column body: sticky TOC + content */}
      <div style={{ padding: "0 72px 80px", display: "grid", gridTemplateColumns: "220px minmax(0, 1fr)", gap: 56, alignItems: "start" }}>
        <TOC T={T} SX={SX} active="universe" />
        <main>
          <UniverseSection     T={T} SX={SX} />
          <PipelineSection     T={T} SX={SX} />
          <ConstructionSection T={T} SX={SX} />
          <ReturnsSection      T={T} SX={SX} />
          <AnalyticsSection    T={T} SX={SX} />
          <LimitationsSection  T={T} SX={SX} />
        </main>
      </div>
      <FundFooter T={T} SX={SX} />
    </div>
  );
}

window.MethodologyApp = MethodologyApp;
