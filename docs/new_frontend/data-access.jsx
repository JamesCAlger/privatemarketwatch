/* eslint-disable */
// Data access landing page. Hero + request form + dataset overview cards.
// Form is purely client-side — no backend; submit transitions to a thank-you state.

const ROLE_OPTIONS = [
  "Asset allocator (institutional)",
  "Investment adviser / RIA",
  "Wealth manager",
  "Fund manager / private-markets firm",
  "Equity or credit analyst",
  "Academic researcher",
  "Journalist",
  "Policy or regulatory researcher",
  "Retail / individual investor",
  "Student",
  "Other",
];

const DATASETS = [
  {
    key: "universe",
    eyebrow: "Tier 1 · Open access",
    title: "Universe data",
    desc: "Fund-level aggregates: AUM history, fund classifications, share-class metadata, manager concentration, distribution and leverage statistics across every BDC, interval fund, and tender-offer fund in our universe.",
    bullets: [
      "385 funds · $830.6B AUM",
      "Quarterly since 2019",
      "CSV + JSON · ~2 MB",
    ],
    cta: "Included with any request",
  },
  {
    key: "indices",
    eyebrow: "Tier 2 · Open access",
    title: "Index data",
    desc: "Quarterly levels, gross and net returns, and constituent histories for the three PMW indices — Direct Lending, Preferred Equity, Common Equity. Including the back-tested period to the January 2019 base date.",
    bullets: [
      "3 indices · 28 quarters",
      "Daily-equivalent total return series",
      "CSV + JSON · ~6 MB",
    ],
    cta: "Included with any request",
  },
  {
    key: "positions",
    eyebrow: "Tier 3 · Reviewed access",
    title: "Position-level data",
    desc: "The underlying dataset — every position the universe analytics and indices are built from. Cost, fair value, lien, coupon, accrual flags, sector classification, and source-filing trail.",
    bullets: [
      "27,124 + 1,267 + 2,938 positions",
      "Reconciled XBRL ↔ N-PORT",
      "Parquet + CSV · ~340 MB",
    ],
    cta: "Reviewed — role and use case determine eligibility",
    gated: true,
  },
];

const DELIVERY = [
  { k: "Format",         v: "CSV, JSON, and Parquet (position-level only). Files are versioned and timestamped." },
  { k: "Update cadence", v: "Quarterly — published ~45 days after quarter end, once the SEC filings underlying each snapshot have landed." },
  { k: "Citation",       v: "Attribution required for any published use. Suggested form: \u201cSource: Metris Lens (metrislens.com), data as of [quarter].\u201d" },
];

// ─── Hero with form ──────────────────────────────────────────────────────────
function DataHero({ T, SX }) {
  const [email, setEmail] = React.useState("");
  const [role, setRole]   = React.useState("");
  const [useCase, setUseCase] = React.useState("");
  const [touched, setTouched] = React.useState({});
  const [submitted, setSubmitted] = React.useState(false);

  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  const roleOk  = role !== "";
  const useCaseOk = useCase.trim().length >= 20;
  const formValid = emailOk && roleOk && useCaseOk;

  const onSubmit = (e) => {
    e.preventDefault();
    setTouched({ email: true, role: true, useCase: true });
    if (formValid) setSubmitted(true);
  };

  const onReset = () => {
    setEmail(""); setRole(""); setUseCase("");
    setTouched({}); setSubmitted(false);
  };

  return (
    <div style={{ padding: "44px 72px 56px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)", gap: 56, alignItems: "start" }}>
        {/* LEFT — pitch */}
        <div>
          <div style={{ ...SX.eyebrowAccent }}>Data access · Free for research, editorial, and institutional use</div>
          <h1 style={{ ...SX.display, fontSize: 80, lineHeight: 1.02, margin: "12px 0 22px", letterSpacing: "-0.03em", color: T.ink }}>
            Get the raw data.
          </h1>
          <p style={{ fontSize: 18, lineHeight: 1.55, color: T.ink2, maxWidth: 600, margin: 0 }}>
            The dataset powering every chart on Metris Lens — universe statistics, three position-level indices, and the underlying holdings file behind them. Built from mandatory SEC filings, reconciled, normalized, and ready to use.
          </p>
          <ul style={{ margin: "32px 0 0", padding: 0, listStyle: "none", maxWidth: 600 }}>
            {[
              "Three tiers — open universe + index data, reviewed access for position-level",
              "Quarterly updates synced to N-PORT and 10-K/10-Q filing cadence",
              "Versioned, change-logged, and reproducible against the published methodology",
            ].map((it, i) => (
              <li key={i} style={{ display: "grid", gridTemplateColumns: "24px 1fr", gap: 0, padding: "12px 0", borderTop: i === 0 ? `1px solid ${T.rule2}` : "none", borderBottom: `1px solid ${T.rule2}`, fontSize: 14, color: T.ink2 }}>
                <span style={{ color: T.accent, fontWeight: 700, fontSize: 14 }}>✓</span>
                <span>{it}</span>
              </li>
            ))}
          </ul>
          <div style={{ marginTop: 28, fontSize: 12, color: T.ink3, lineHeight: 1.6, maxWidth: 580 }}>
            Questions before requesting? Read the <a href="Methodology.html" style={{ color: T.ink, textDecoration: "none", borderBottom: `1px solid ${T.accent}` }}>methodology</a> or see the <a href="#" style={{ color: T.ink, textDecoration: "none", borderBottom: `1px solid ${T.accent}` }}>data dictionary</a>. For press inquiries, email <span style={{ ...SX.num, color: T.ink2 }}>press@metrislens.com</span>.
          </div>
        </div>

        {/* RIGHT — form card */}
        <div style={{ ...SX.card, padding: 32, position: "relative" }}>
          {submitted ? (
            <SubmittedState T={T} SX={SX} email={email} role={role} onReset={onReset} />
          ) : (
            <form onSubmit={onSubmit} noValidate>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                <span style={{ ...SX.eyebrowAccent }}>Request access</span>
                <span style={{ fontSize: 11, color: T.ink3 }}>Required · 3 fields</span>
              </div>
              <h2 style={{ ...SX.display, fontSize: 24, margin: "0 0 22px", letterSpacing: "-0.01em", color: T.ink }}>Tell us a little about you.</h2>

              <Field T={T} SX={SX} label="Email"
                error={touched.email && !emailOk ? "Enter a valid email address." : null}>
                <input type="email" required value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onBlur={() => setTouched(t => ({ ...t, email: true }))}
                  placeholder="you@firm.com"
                  style={inputStyle(T, touched.email && !emailOk)} />
              </Field>

              <Field T={T} SX={SX} label="Who are you?"
                error={touched.role && !roleOk ? "Pick the closest match." : null}>
                <div style={{ position: "relative" }}>
                  <select required value={role}
                    onChange={(e) => { setRole(e.target.value); setTouched(t => ({ ...t, role: true })); }}
                    style={{ ...inputStyle(T, touched.role && !roleOk), appearance: "none", WebkitAppearance: "none", paddingRight: 36, cursor: "pointer", color: role === "" ? T.ink3 : T.ink }}>
                    <option value="" disabled>Select a role…</option>
                    {ROLE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                  <span style={{ position: "absolute", right: 14, top: "50%", transform: "translateY(-50%)", fontSize: 10, color: T.ink3, pointerEvents: "none" }}>▾</span>
                </div>
              </Field>

              <Field T={T} SX={SX} label="How will you use the data?"
                hint="A sentence or two is enough. For Tier 3 (position-level), this is what we triage on."
                error={touched.useCase && !useCaseOk ? `At least 20 characters · ${useCase.trim().length} so far.` : null}>
                <textarea required value={useCase}
                  onChange={(e) => setUseCase(e.target.value)}
                  onBlur={() => setTouched(t => ({ ...t, useCase: true }))}
                  rows={4}
                  placeholder="e.g., I'm researching capital flows into non-traded BDCs for a paper at Booth …"
                  style={{ ...inputStyle(T, touched.useCase && !useCaseOk), resize: "vertical", fontFamily: T.bodyFont, lineHeight: 1.5 }} />
              </Field>

              <button type="submit" style={{
                marginTop: 18, width: "100%", padding: "14px 22px",
                background: formValid ? T.navy : T.ink3, color: "#fff",
                border: "none", fontSize: 14, fontWeight: 600, letterSpacing: "0.04em",
                fontFamily: T.bodyFont, cursor: formValid ? "pointer" : "not-allowed",
                display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
                transition: "background 120ms"
              }}>
                Request access <span style={{ color: T.accent }}>→</span>
              </button>

              <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${T.rule2}`, fontSize: 11, color: T.ink3, lineHeight: 1.55 }}>
                We use your email to send the data and follow up on Tier 3 reviews. We don't share, sell, or use it for marketing. See <a href="#" style={{ color: T.ink2, textDecoration: "none", borderBottom: `1px solid ${T.rule}` }}>data handling notes</a>.
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

function SubmittedState({ T, SX, email, role, onReset }) {
  return (
    <div>
      <div style={{ ...SX.eyebrowAccent }}>Request received</div>
      <h2 style={{ ...SX.display, fontSize: 28, margin: "8px 0 14px", letterSpacing: "-0.015em", color: T.ink }}>Thanks — we'll be in touch.</h2>
      <p style={{ fontSize: 14, lineHeight: 1.6, color: T.ink2, margin: "0 0 18px" }}>
        We've logged your request as <span style={{ ...SX.num, color: T.ink, fontWeight: 600 }}>{email}</span> ({role}). For Tier 1 + 2 data, expect download links within 2 business days. Tier 3 (position-level) requests are reviewed; expect a follow-up within 5 business days.
      </p>
      <div style={{ padding: "14px 16px", background: T.rule3, borderLeft: `2px solid ${T.accent}`, fontSize: 12, color: T.ink2, lineHeight: 1.55, marginBottom: 22 }}>
        <strong style={{ color: T.ink }}>Next time</strong> — once your email is verified, requesting additional cuts of the data takes one click. We'll send the verification link to your inbox shortly.
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        <a href="Methodology.html" style={{ flex: 1, padding: "12px 16px", border: `1px solid ${T.rule}`, color: T.ink, fontSize: 13, fontWeight: 500, textDecoration: "none", textAlign: "center" }}>Read the methodology →</a>
        <button onClick={onReset} style={{ padding: "12px 16px", background: "transparent", border: `1px solid ${T.rule}`, color: T.ink2, fontSize: 12, cursor: "pointer", fontFamily: T.bodyFont }}>Submit another</button>
      </div>
    </div>
  );
}

function Field({ T, SX, label, hint, error, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <label style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
        <span style={{ ...SX.eyebrow, color: T.ink2 }}>{label}</span>
        {hint && !error && <span style={{ fontSize: 10, color: T.ink3, letterSpacing: "0.04em", textTransform: "none", fontWeight: 400, maxWidth: 260, textAlign: "right", lineHeight: 1.4 }}>{hint}</span>}
        {error && <span style={{ fontSize: 10, color: T.red, fontWeight: 500 }}>{error}</span>}
      </label>
      {children}
    </div>
  );
}

function inputStyle(T, hasError) {
  return {
    width: "100%",
    padding: "11px 14px",
    border: `1px solid ${hasError ? T.red : T.rule}`,
    background: "#fff",
    color: T.ink,
    fontSize: 14,
    fontFamily: T.bodyFont,
    outline: "none",
    borderRadius: 0,
    boxSizing: "border-box",
  };
}

// ─── Dataset cards ───────────────────────────────────────────────────────────
function DatasetSection({ T, SX }) {
  return (
    <div style={{ padding: "0 72px 56px" }}>
      <div style={{ marginBottom: 22 }}>
        <div style={{ ...SX.eyebrowAccent }}>What you'll receive</div>
        <h2 style={{ ...SX.display, fontSize: 36, margin: "8px 0 0", letterSpacing: "-0.02em", color: T.ink }}>Three tiers, one approval.</h2>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 24 }}>
        {DATASETS.map(d => (
          <DatasetCard key={d.key} T={T} SX={SX} d={d} />
        ))}
      </div>
    </div>
  );
}

function DatasetCard({ T, SX, d }) {
  return (
    <div style={{ ...SX.card, padding: 28, display: "flex", flexDirection: "column", position: "relative", borderColor: d.gated ? T.accent : T.rule }}>
      <div style={{ ...SX.eyebrow, color: d.gated ? T.accent : T.ink3 }}>{d.eyebrow}</div>
      <h3 style={{ ...SX.display, fontSize: 26, margin: "8px 0 14px", letterSpacing: "-0.015em", color: T.ink }}>{d.title}</h3>
      <p style={{ fontSize: 14, lineHeight: 1.6, color: T.ink2, margin: "0 0 22px", minHeight: 110 }}>{d.desc}</p>
      <ul style={{ margin: "0 0 22px", padding: 0, listStyle: "none", borderTop: `1px solid ${T.rule2}` }}>
        {d.bullets.map((b, i) => (
          <li key={i} style={{ padding: "10px 0", borderBottom: `1px solid ${T.rule2}`, fontSize: 12, color: T.ink2, fontFamily: T.monoFont, letterSpacing: "-0.005em" }}>{b}</li>
        ))}
      </ul>
      <div style={{ marginTop: "auto", paddingTop: 14, borderTop: `1px solid ${T.rule}`, fontSize: 12, color: d.gated ? T.accent : T.ink3, fontWeight: d.gated ? 600 : 400, letterSpacing: "0.02em" }}>
        {d.cta}
      </div>
    </div>
  );
}

// ─── Delivery / Terms strip ──────────────────────────────────────────────────
function DeliveryStrip({ T, SX }) {
  return (
    <div style={{ padding: "0 72px 80px" }}>
      <div style={{ ...SX.card, padding: 0, background: T.surface }}>
        <div style={{ padding: "24px 32px", borderBottom: `1px solid ${T.rule2}` }}>
          <div style={{ ...SX.eyebrowAccent }}>Delivery & terms</div>
          <h3 style={{ ...SX.display, fontSize: 24, margin: "6px 0 0", letterSpacing: "-0.015em", color: T.ink }}>How you'll receive it.</h3>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)" }}>
          {DELIVERY.map((d, i) => (
            <div key={d.k} style={{ padding: "24px 32px", borderLeft: i > 0 ? `1px solid ${T.rule2}` : "none" }}>
              <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 10 }}>{d.k}</div>
              <div style={{ fontSize: 13, lineHeight: 1.55, color: T.ink }}>{d.v}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── App shell ───────────────────────────────────────────────────────────────
function DataAccessApp() {
  const T = window.T_V3, SX = window.SX_V3;
  return (
    <div style={SX.root} data-screen-label="Data Access">
      <FundHeader T={T} SX={SX} navActive="Data" />
      <Breadcrumb T={T} items={[
        { label: "Home", href: "index.html" },
        { label: "Data" },
      ]} />
      <DataHero       T={T} SX={SX} />
      <DatasetSection T={T} SX={SX} />
      <DeliveryStrip  T={T} SX={SX} />
      <FundFooter T={T} SX={SX} />
    </div>
  );
}

window.DataAccessApp = DataAccessApp;
