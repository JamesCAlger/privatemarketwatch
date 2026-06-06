/* eslint-disable */
// Shared header / breadcrumb / footer for the v3 fund-detail pages.
// Themed by passing T (the theme object) through.

function FundHeader({ T, SX, fundType, otherFundLink, otherFundLabel, navActive = "Funds" }) {
  return (
    <div style={{ background: T.navy, color: "rgba(255,255,255,0.78)" }}>
      <div style={{ padding: "10px 72px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: `1px solid rgba(255,255,255,0.06)`, fontSize: 11, letterSpacing: "0.06em" }}>
        <span style={{ color: "rgba(255,255,255,0.55)" }}>As of Q4 2025 · Data updated 14 May 2026</span>
        <div style={{ display: "flex", gap: 18 }}>
          <span>EN ▾</span>
          <a href="roadmap.html#advisors" style={{ color: "inherit", textDecoration: "none" }}>For Advisors</a>
          <a href="roadmap.html#institutions" style={{ color: "inherit", textDecoration: "none" }}>For Institutions</a>
          <a href="roadmap.html#login" style={{ color: "inherit", textDecoration: "none" }}>Login</a>
        </div>
      </div>
      <div style={{ padding: "20px 72px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <a href="index.html" style={{ display: "flex", alignItems: "baseline", gap: 14, textDecoration: "none" }}>
          <div style={{ ...SX.display, fontSize: 26, color: "#fff", letterSpacing: "-0.005em", fontWeight: 500 }}>Metris Lens</div>
          <div style={{ fontSize: 10, letterSpacing: "0.2em", textTransform: "uppercase", color: T.accent }}>Data · Indices · Research</div>
        </a>
        <div style={{ display: "flex", gap: 28, alignItems: "center", fontSize: 13, fontWeight: 500 }}>
          {[
            { label: "Indices",     href: "Index Detail - Direct Lending.html" },
            { label: "Funds",       href: "index.html" },
            { label: "Methodology", href: "Methodology.html" },
            { label: "Data",        href: "Data.html" },
            { label: "About",       href: "About.html" },
          ].map(({ label, href }) => {
            const on = label === navActive;
            return <a key={label} href={href} style={{ textDecoration: "none", paddingBottom: 4, borderBottom: on ? `2px solid ${T.accent}` : "2px solid transparent", color: on ? "#fff" : "rgba(255,255,255,0.78)" }}>{label}</a>;
          })}
          <a href="Data.html" style={{ padding: "8px 16px", border: `1px solid ${T.accent}`, color: T.accent, fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", textDecoration: "none" }}>Subscribe →</a>
        </div>
      </div>
      <div style={{ background: T.navyDeep, padding: "0 72px", display: "flex", alignItems: "stretch", borderTop: `1px solid rgba(255,255,255,0.06)` }}>
        <div style={{ padding: "10px 18px 10px 0", color: T.accent, ...SX.eyebrow, color: T.accent, letterSpacing: "0.22em", display: "flex", alignItems: "center", borderRight: `1px solid rgba(255,255,255,0.08)` }}>
          Fund Lookup
        </div>
        <div style={{ flex: 1, padding: "10px 18px", display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ color: "rgba(255,255,255,0.55)" }}>⌕</span>
          <input style={{ flex: 1, background: "transparent", border: "none", color: "#fff", fontFamily: T.bodyFont, fontSize: 13, outline: "none" }} placeholder="Search 385 funds by ticker, name, manager, or CIK…" defaultValue="" />
          <span style={{ ...SX.num, fontSize: 11, color: "rgba(255,255,255,0.45)" }}>⌘K</span>
        </div>
        {otherFundLink && (
          <a href={otherFundLink} style={{ padding: "10px 18px", borderLeft: `1px solid rgba(255,255,255,0.08)`, color: T.accent, fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", textDecoration: "none", display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: "rgba(255,255,255,0.55)" }}>↺</span> {otherFundLabel}
          </a>
        )}
      </div>
    </div>
  );
}

function Breadcrumb({ T, items }) {
  return (
    <div style={{ padding: "20px 72px 0", fontSize: 12, color: T.ink2, letterSpacing: "0.02em" }}>
      {items.map((it, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span style={{ color: T.ink4, margin: "0 8px" }}>›</span>}
          {it.href ? <a href={it.href} style={{ color: T.ink2, textDecoration: "none" }}>{it.label}</a> : <span style={{ color: T.ink }}>{it.label}</span>}
        </React.Fragment>
      ))}
    </div>
  );
}

function FundFooter({ T, SX }) {
  return (
    <div style={{ background: T.navy, color: "rgba(255,255,255,0.78)", padding: "56px 72px 36px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 28 }}>
        <div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ ...SX.display, fontSize: 20, color: "#fff", letterSpacing: "-0.005em", fontWeight: 500 }}>Metris Lens</span>
            <span style={{ fontSize: 9, letterSpacing: "0.2em", textTransform: "uppercase", color: T.accent }}>Data · Indices · Research</span>
          </div>
          <p style={{ fontSize: 12, lineHeight: 1.6, marginTop: 12, maxWidth: 320 }}>
            Independent, rules-based benchmarks for private credit and equity markets — built entirely from mandatory SEC filings. Does not constitute investment advice.
          </p>
        </div>
        {(() => {
          const HREFS = {
            "Direct Lending":   "Index Detail - Direct Lending.html",
            "Preferred Equity": "Index Detail - Preferred Equity.html",
            "Common Equity":    "Index Detail - Common Equity.html",
            "Methodology":      "Methodology.html",
            "About":            "About.html",
            "Data access":      "Data.html",
          };
          return [
            ["Indices",      ["Direct Lending", "Preferred Equity", "Common Equity"]],
            ["Resources",    ["Methodology", "About", "Data access"]],
            ["Data Sources", ["SEC EDGAR — BDC XBRL", "SEC EDGAR — N-PORT", "SEC EDGAR — N-CEN / N-2"]],
          ].map(([h, items]) =>
            <div key={h}>
              <div style={{ ...SX.eyebrow, color: T.accent, marginBottom: 10 }}>{h}</div>
              {items.map((it) => HREFS[it]
                ? <a key={it} href={HREFS[it]} style={{ display: "block", fontSize: 12, padding: "4px 0", color: "inherit", textDecoration: "none" }}>{it}</a>
                : <div key={it} style={{ fontSize: 12, padding: "4px 0" }}>{it}</div>
              )}
            </div>
          );
        })()}
      </div>
      <div style={{ borderTop: `1px solid rgba(255,255,255,0.1)`, marginTop: 28, paddingTop: 14, fontSize: 11, opacity: 0.6, display: "flex", justifyContent: "space-between" }}>
        <span>© 2026 Metris, Inc. · metrislens.com</span>
        <span>Independent · Transparent · Rules-based</span>
      </div>
    </div>
  );
}

// ── Theme & shared style object ──────────────────────────────────────────────
const T_V3 = {
  bg: "#fbfaf7", surface: "#ffffff",
  ink: "#0b1a2c", ink2: "#3b4a5b", ink3: "#6b7280", ink4: "#9aa1ab",
  rule: "#dfe3ea", rule2: "#eef0f4", rule3: "#f5f7fa",
  navy: "#0b1a2c", navyDeep: "#06121f", navyMid: "#16273c",
  accent: "#c7a14a", accent2: "#e2bb66", accentSoft: "#f3e6c0",
  green: "#1f7a4a", red: "#a8362b", amber: "#b07827",
  displayFont: '"IBM Plex Serif","Source Serif 4",Georgia,serif',
  bodyFont: '"IBM Plex Sans","Inter",system-ui,sans-serif',
  monoFont: '"IBM Plex Mono",ui-monospace,monospace'
};
const SX_V3 = {
  root: { background: T_V3.bg, color: T_V3.ink, fontFamily: T_V3.bodyFont, fontSize: 14, lineHeight: 1.45, minHeight: "100vh" },
  display: { fontFamily: T_V3.displayFont, fontWeight: 500 },
  num: { fontFamily: T_V3.monoFont, fontVariantNumeric: "tabular-nums" },
  eyebrow: { textTransform: "uppercase", letterSpacing: "0.18em", fontSize: 10, fontWeight: 600, color: T_V3.ink2 },
  eyebrowAccent: { textTransform: "uppercase", letterSpacing: "0.18em", fontSize: 10, fontWeight: 600, color: T_V3.accent },
  card: { background: T_V3.surface, border: `1px solid ${T_V3.rule}`, borderRadius: 2 },
  pillActive:   { padding: "7px 14px", border: `1px solid ${T_V3.ink}`,  background: T_V3.navy, color: "#fff",      fontSize: 12, fontWeight: 500, letterSpacing: "0.04em", cursor: "pointer" },
  pillInactive: { padding: "7px 14px", border: `1px solid ${T_V3.rule}`, background: "transparent", color: T_V3.ink2, fontSize: 12, fontWeight: 500, letterSpacing: "0.04em", cursor: "pointer" },
};

Object.assign(window, { FundHeader, Breadcrumb, FundFooter, T_V3, SX_V3 });
