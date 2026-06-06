/* eslint-disable */
// About page — short, editorial. Mission, manifesto, principles, people, contact.
// Reuses T_V3 / SX_V3 + FundHeader / FundFooter / Breadcrumb from fund-chrome.

const PRINCIPLES = [
  {
    num: "01",
    title: "Independent",
    body: "No fund manager owns us. No marketing budget pays us. No allocator gets pre-release access. The data we publish is the data anyone reading the site sees.",
  },
  {
    num: "02",
    title: "Rules-based",
    body: "Every figure on this site is the output of a documented rule applied to a public filing. There are no analyst overlays, no proprietary scores, no opinions baked into the numbers.",
  },
  {
    num: "03",
    title: "Transparent",
    body: "Methodology is versioned and public. Coverage gaps are disclosed on every dashboard. When the data has a limitation, the limitation is labelled — not averaged away.",
  },
  {
    num: "04",
    title: "Reproducible",
    body: "Anyone with our data file and the published methodology can reproduce every number on this site. That is the discipline that turns a website into a research artifact.",
  },
];

const TEAM = [
  { role: "Cofounder & CEO",                 focus: "Strategy · Product · Distribution" },
  { role: "Cofounder & Head of Engineering", focus: "Data pipeline · Reconciliation · Infrastructure" },
  { role: "Head of Research",                focus: "Methodology · Index construction · Editorial" },
  { role: "Head of Data Operations",         focus: "Filings ingestion · Coverage · Data quality" },
];

const ADVISORS = [
  { role: "Senior advisor",  focus: "Former senior staff, SEC Investment Management Division" },
  { role: "Senior advisor",  focus: "Quantitative researcher · private credit benchmarks" },
  { role: "Senior advisor",  focus: "Financial journalism · editor and columnist" },
  { role: "Senior advisor",  focus: "Allocator · institutional consulting and OCIO" },
];

const CONTACT = [
  { k: "Media inquiries",        email: "press@metrislens.com",         note: "Quotes, embargoed data, and source meetings. Response within 1 business day." },
  { k: "Data access & technical",email: "data@metrislens.com",          note: "Questions about the dataset, methodology, or API. See also the Data page." },
  { k: "Partnerships & licensing",email: "partnerships@metrislens.com", note: "Distribution, redistribution, white-label, and API licensing." },
  { k: "Everything else",        email: "hello@metrislens.com",         note: "General inbox. We read everything; we reply to most." },
];

// ─── Hero ────────────────────────────────────────────────────────────────────
function AboutHero({ T, SX }) {
  return (
    <div style={{ padding: "56px 72px 36px" }}>
      <div style={{ ...SX.eyebrowAccent }}>About Metris Lens</div>
      <h1 style={{ ...SX.display, fontSize: 88, lineHeight: 1.0, margin: "12px 0 24px", letterSpacing: "-0.032em", color: T.ink, maxWidth: 1000 }}>
        Making private markets observable.
      </h1>
      <p style={{ fontSize: 20, lineHeight: 1.55, color: T.ink2, maxWidth: 760, margin: 0 }}>
        Built from mandatory disclosure, not privileged access. We turn the SEC filings of registered private-market vehicles into a single, reconciled, position-level dataset — and publish the analytics, indices, and fund pages that sit on top of it.
      </p>
    </div>
  );
}

// ─── Manifesto ───────────────────────────────────────────────────────────────
function Manifesto({ T, SX }) {
  return (
    <div style={{ padding: "32px 72px 80px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 200px) minmax(0, 760px)", gap: 64, alignItems: "start" }}>
        <div style={{ ...SX.eyebrow, color: T.ink3, paddingTop: 8 }}>Why this exists</div>
        <div>
          <p style={{ fontSize: 18, lineHeight: 1.6, color: T.ink, margin: "0 0 22px", letterSpacing: "-0.003em" }}>
            <strong style={{ color: T.ink, fontWeight: 600 }}>Private markets have grown into a multi-trillion dollar asset class, but the data has lagged behind.</strong> Most reporting is proprietary, gated behind subscriptions, curated by the firms whose products it describes, or reduced to fund-of-funds composites that hide as much as they show.
          </p>
          <p style={{ fontSize: 16, lineHeight: 1.65, color: T.ink2, margin: "0 0 22px" }}>
            What changed is the disclosure regime. The SEC requires every registered closed-end vehicle — BDCs, interval funds, tender-offer funds — to file its complete portfolio, position by position, every quarter. That mandate created the only large, position-level dataset of private-market exposures that anyone can analyze without privileged access.
          </p>
          <p style={{ fontSize: 16, lineHeight: 1.65, color: T.ink2, margin: 0 }}>
            We've been reconciling that data, position by position, since 2024. Investors use it to size positions and compare managers; allocators use it to construct portfolios; journalists use it to write stories that wouldn't otherwise be possible; regulators and academics use it to study how the asset class is actually behaving. We charge nothing for the universe and index data, review access for the position-level file, and ask only that you cite us when you publish. The data wants to be useful.
          </p>
        </div>
      </div>
    </div>
  );
}

// ─── Principles ──────────────────────────────────────────────────────────────
function Principles({ T, SX }) {
  return (
    <div style={{ padding: "0 72px 80px" }}>
      <div style={{ marginBottom: 28 }}>
        <div style={{ ...SX.eyebrowAccent }}>What we stand for</div>
        <h2 style={{ ...SX.display, fontSize: 40, margin: "10px 0 0", letterSpacing: "-0.02em", color: T.ink }}>Four principles, stated out loud.</h2>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 0, border: `1px solid ${T.rule}`, background: T.surface }}>
        {PRINCIPLES.map((p, i) => (
          <div key={p.num} style={{ padding: "28px 28px 32px", borderRight: i < 3 ? `1px solid ${T.rule2}` : "none" }}>
            <div style={{ fontFamily: T.monoFont, fontSize: 11, color: T.accent, letterSpacing: "0.14em", marginBottom: 12 }}>{p.num}</div>
            <h3 style={{ ...SX.display, fontSize: 24, margin: "0 0 14px", letterSpacing: "-0.01em", color: T.ink }}>{p.title}</h3>
            <p style={{ fontSize: 13, lineHeight: 1.6, color: T.ink2, margin: 0 }}>{p.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── People (Team + Advisors) ───────────────────────────────────────────────
function People({ T, SX }) {
  return (
    <div style={{ padding: "0 72px 80px" }}>
      <div style={{ marginBottom: 28 }}>
        <div style={{ ...SX.eyebrowAccent }}>People</div>
        <h2 style={{ ...SX.display, fontSize: 40, margin: "10px 0 0", letterSpacing: "-0.02em", color: T.ink }}>The team and advisors.</h2>
      </div>

      <div style={{ ...SX.eyebrow, color: T.ink3, marginTop: 20, marginBottom: 14 }}>Core team</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 18 }}>
        {TEAM.map((p, i) => <PersonCard key={i} T={T} SX={SX} p={p} large />)}
      </div>

      <div style={{ ...SX.eyebrow, color: T.ink3, marginTop: 44, marginBottom: 14 }}>Advisors</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 18 }}>
        {ADVISORS.map((p, i) => <PersonCard key={i} T={T} SX={SX} p={p} />)}
      </div>

      <div style={{ marginTop: 36, paddingTop: 16, borderTop: `1px solid ${T.rule2}`, fontSize: 12, color: T.ink3, fontStyle: "italic", maxWidth: 760, lineHeight: 1.55 }}>
        Names and bios are intentionally blank in this build — Claude Code will fill them in against the real roster. The structural decision being shown is the 4-person founding team + 4-advisor pattern.
      </div>
    </div>
  );
}

function PersonCard({ T, SX, p, large }) {
  const photoSize = large ? 88 : 64;
  return (
    <div style={{ ...SX.card, padding: large ? 22 : 18, display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Headshot placeholder — empty bordered circle */}
      <div style={{
        width: photoSize, height: photoSize, borderRadius: "50%",
        background: `repeating-linear-gradient(45deg, ${T.rule3} 0, ${T.rule3} 6px, ${T.rule2} 6px, ${T.rule2} 12px)`,
        border: `1px solid ${T.rule}`,
        position: "relative",
      }}>
        <span style={{
          position: "absolute", inset: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontFamily: T.monoFont, fontSize: 9, color: T.ink3, letterSpacing: "0.06em",
        }}>headshot</span>
      </div>
      <div>
        <div style={{ fontSize: 11, fontFamily: T.monoFont, color: T.ink3, letterSpacing: "0.06em", marginBottom: 6, textTransform: "uppercase" }}>[ Name ]</div>
        <div style={{ ...SX.display, fontSize: large ? 17 : 15, color: T.ink, letterSpacing: "-0.005em", marginBottom: 6, lineHeight: 1.25 }}>{p.role}</div>
        <div style={{ fontSize: 12, color: T.ink2, lineHeight: 1.5 }}>{p.focus}</div>
      </div>
    </div>
  );
}

// ─── Contact ────────────────────────────────────────────────────────────────
function Contact({ T, SX }) {
  return (
    <div style={{ padding: "0 72px 80px" }}>
      <div style={{ ...SX.card, padding: 0, background: T.navy, color: "#fff" }}>
        <div style={{ padding: "36px 36px 22px" }}>
          <div style={{ ...SX.eyebrow, color: T.accent }}>Contact</div>
          <h2 style={{ ...SX.display, fontSize: 36, margin: "8px 0 6px", letterSpacing: "-0.02em", color: "#fff" }}>Get in touch.</h2>
          <p style={{ fontSize: 14, lineHeight: 1.6, color: "rgba(255,255,255,0.7)", maxWidth: 580, margin: 0 }}>
            Pick the inbox that fits — or use the general one if you're not sure. Replies come from the team, not an autoresponder.
          </p>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", borderTop: "1px solid rgba(255,255,255,0.12)" }}>
          {CONTACT.map((c, i) => (
            <div key={c.k} style={{ padding: "28px 32px", borderLeft: i > 0 ? "1px solid rgba(255,255,255,0.12)" : "none" }}>
              <div style={{ ...SX.eyebrow, color: T.accent, marginBottom: 10 }}>{c.k}</div>
              <a href={`mailto:${c.email}`} style={{ ...SX.num, fontSize: 14, color: "#fff", textDecoration: "none", borderBottom: `1px solid ${T.accent}`, paddingBottom: 2, display: "inline-block", marginBottom: 12 }}>{c.email}</a>
              <div style={{ fontSize: 12, color: "rgba(255,255,255,0.65)", lineHeight: 1.5, marginTop: 6 }}>{c.note}</div>
            </div>
          ))}
        </div>
        <div style={{ padding: "20px 36px", borderTop: "1px solid rgba(255,255,255,0.12)", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
          <span style={{ fontSize: 12, color: "rgba(255,255,255,0.55)" }}>
            Metris, Inc. · Delaware corporation · est. 2024
          </span>
          <div style={{ display: "flex", gap: 18, fontSize: 12, color: "rgba(255,255,255,0.78)" }}>
            <a href="Methodology.html" style={{ color: "inherit", textDecoration: "none", borderBottom: `1px solid ${T.accent}`, paddingBottom: 2 }}>Methodology</a>
            <a href="Data.html"        style={{ color: "inherit", textDecoration: "none", borderBottom: `1px solid ${T.accent}`, paddingBottom: 2 }}>Data access</a>
            <a href="index.html"       style={{ color: "inherit", textDecoration: "none", borderBottom: `1px solid ${T.accent}`, paddingBottom: 2 }}>Universe homepage</a>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── App shell ──────────────────────────────────────────────────────────────
function AboutApp() {
  const T = window.T_V3, SX = window.SX_V3;
  return (
    <div style={SX.root} data-screen-label="About">
      <FundHeader T={T} SX={SX} navActive="About" />
      <Breadcrumb T={T} items={[
        { label: "Home",  href: "index.html" },
        { label: "About" },
      ]} />
      <AboutHero  T={T} SX={SX} />
      <Manifesto  T={T} SX={SX} />
      <Principles T={T} SX={SX} />
      <People     T={T} SX={SX} />
      <Contact    T={T} SX={SX} />
      <FundFooter T={T} SX={SX} />
    </div>
  );
}

window.AboutApp = AboutApp;
