/* eslint-disable */
// Peer / quartile visualization primitives.
//
// All components are theme-agnostic — they take colors via props. The fund
// detail pages pass T.navy / T.accent etc.
//
// Convention for "direction":
//   "higher"  → larger values are better, rank 1 = best
//   "lower"   → smaller values are better, rank 1 = best
//   "neutral" → no canonical direction (e.g. premium to NAV); we just plot

// ── Helpers ──────────────────────────────────────────────────────────────────
function pq_quartileOf(rank, total) {
  // Map rank (1..total) into 1..4. Rank 1 is always the "best" quartile by
  // convention, so callers should pre-rank in the metric's preferred direction.
  if (rank <= total * 0.25) return 1;
  if (rank <= total * 0.50) return 2;
  if (rank <= total * 0.75) return 3;
  return 4;
}

function pq_ordinal(n) {
  const s = ["th","st","nd","rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

// ── KDE helper ───────────────────────────────────────────────────────────────
// Returns { xs, ys } for a smoothed density curve over `values`.
// Gaussian kernel, Silverman's rule of thumb for bandwidth. Density is
// normalized to [0,1] so callers can scale to any pixel height. xMin/xMax
// can be passed to fix the domain (so the curve aligns with quartile axis).
function pq_kde(values, opts = {}) {
  const v = values.filter((x) => x != null);
  const n = v.length;
  if (n === 0) return { xs: [], ys: [], xMin: 0, xMax: 1 };
  const mean = v.reduce((a, b) => a + b, 0) / n;
  const variance = v.reduce((a, b) => a + (b - mean) * (b - mean), 0) / n;
  const sigma = Math.sqrt(variance) || 1;
  // Silverman bandwidth
  const h = 1.06 * sigma * Math.pow(n, -1 / 5) || 0.5;
  const lo = Math.min(...v), hi = Math.max(...v);
  const xMin = opts.xMin ?? lo - (hi - lo) * 0.05;
  const xMax = opts.xMax ?? hi + (hi - lo) * 0.05;
  const grid = opts.grid ?? 96;
  const xs = [];
  const ys = [];
  const inv2h2 = 1 / (2 * h * h);
  const norm = 1 / (n * h * Math.sqrt(2 * Math.PI));
  let maxY = 0;
  for (let i = 0; i < grid; i++) {
    const x = xMin + (i / (grid - 1)) * (xMax - xMin);
    let y = 0;
    for (let j = 0; j < n; j++) {
      const d = x - v[j];
      y += Math.exp(-d * d * inv2h2);
    }
    y *= norm;
    xs.push(x);
    ys.push(y);
    if (y > maxY) maxY = y;
  }
  // Normalize to [0,1]
  const yNorm = ys.map((y) => y / (maxY || 1));
  return { xs, ys: yNorm, xMin, xMax };
}

// ── PeerDensity: KDE distribution curve with fund marker + quartile axis ─────
// peers: numeric values of all funds in the universe (include focal fund's value)
// value: the focal fund's value (drawn as a vertical marker)
// direction: "higher" | "lower" | "neutral" — which end is "better"
//
// Axis: min-max normalized to [0, 100] using the peer distribution's actual
// min/max. This gives every PeerDensity in a band the SAME x-axis vocabulary
// (0 = lowest peer, 100 = highest), so quartile cutoffs and fund markers are
// directly comparable across metrics. Quartile boundaries are drawn as thin
// vertical guides inside the chart (not as Q1/Q4 text labels, which collided
// with the calendar-quarter convention used elsewhere on the page).
function PeerDensity({
  peers, value, direction = "higher", T, ticker = "",
  w = 320, h = 64, padding = { l: 4, r: 4, t: 4, b: 14 },
  showQuartileLabels = true, showTickerLabel = true,
}) {
  const v = peers.filter((x) => x != null);
  if (v.length < 3) {
    return (
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block" }}>
        <text x={w / 2} y={h / 2} textAnchor="middle" fontSize="10" fill={T.ink3}>—</text>
      </svg>
    );
  }
  const sorted = v.slice().sort((a, b) => a - b);
  const lo = sorted[0], hi = sorted[sorted.length - 1];
  const range = (hi - lo) || (Math.abs(lo) * 0.1 + 1);
  // Min-max normalize peers and fund to [0, 100]
  const norm = (x) => ((x - lo) / range) * 100;
  const normed = v.map(norm);
  const valueNorm = norm(value);

  // KDE over a slightly padded [0, 100] domain so the curve has breathing room
  const xMin = -4, xMax = 104;
  const { xs, ys } = pq_kde(normed, { xMin, xMax, grid: 96 });
  const cw = w - padding.l - padding.r;
  const ch = h - padding.t - padding.b;
  const xAt = (x) => padding.l + ((x - xMin) / (xMax - xMin)) * cw;
  const yAt = (y) => padding.t + ch - y * ch;
  const baseY = padding.t + ch;

  // Build closed path for filled area under curve
  const linePts = xs.map((x, i) => `${xAt(x).toFixed(2)},${yAt(ys[i]).toFixed(2)}`);
  const areaPath = `M ${xAt(xMin).toFixed(2)},${baseY.toFixed(2)} L ${linePts.join(" L ")} L ${xAt(xMax).toFixed(2)},${baseY.toFixed(2)} Z`;
  const linePath = `M ${linePts.join(" L ")}`;

  // Tail-beyond-fund shaded region (the "still better than me" tail)
  const fundX = xAt(valueNorm);
  const showTail = direction === "higher" || direction === "lower";
  const tailClipId = `pd-tail-${Math.random().toString(36).slice(2, 9)}`;
  const tailX = direction === "higher" ? fundX : padding.l;
  const tailW = direction === "higher" ? (w - padding.r) - fundX : fundX - padding.l;

  // Anchor positions for the 0 / 100 axis ticks (drawn at the true 0 and 100, not the padded extents)
  const zeroX = xAt(0);
  const hundredX = xAt(100);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block", overflow: "visible" }}>
      <defs>
        {showTail && (
          <clipPath id={tailClipId}>
            <rect x={tailX} y={0} width={tailW} height={h} />
          </clipPath>
        )}
      </defs>
      {/* Light fill under the whole curve */}
      <path d={areaPath} fill={T.ink3} opacity="0.10" />
      {/* Darker shaded tail beyond the fund (the "still better than me" zone) */}
      {showTail && (
        <path d={areaPath} fill={T.ink} opacity="0.22" clipPath={`url(#${tailClipId})`} />
      )}
      {/* The density curve itself */}
      <path d={linePath} fill="none" stroke={T.ink} strokeWidth="1.2" opacity="0.55" />
      {/* Baseline */}
      <line x1={padding.l} x2={w - padding.r} y1={baseY} y2={baseY} stroke={T.ink3} strokeOpacity="0.5" strokeWidth="0.75" />
      {/* 0 and 100 anchor ticks on the baseline */}
      <line x1={zeroX} x2={zeroX} y1={baseY - 3} y2={baseY + 3} stroke={T.ink3} strokeOpacity="0.7" strokeWidth="0.75" />
      <line x1={hundredX} x2={hundredX} y1={baseY - 3} y2={baseY + 3} stroke={T.ink3} strokeOpacity="0.7" strokeWidth="0.75" />
      {/* Fund marker */}
      <line x1={fundX} x2={fundX} y1={padding.t} y2={baseY}
        stroke={T.accent} strokeWidth="1.5" />
      {showTickerLabel && ticker && (
        <text x={fundX} y={padding.t + 8} textAnchor={
          fundX > (padding.l + cw * 0.78) ? "end" :
          fundX < (padding.l + cw * 0.22) ? "start" : "middle"
        }
          dx={fundX > (padding.l + cw * 0.78) ? -4 : fundX < (padding.l + cw * 0.22) ? 4 : 0}
          fontSize="9.5" fontFamily={T.displayFont} fontWeight="600" fill={T.accent}
          letterSpacing="0.02em">
          {ticker}
        </text>
      )}
      {/* 0 / 100 axis labels along the bottom (consistent across every chart in the band) */}
      {showQuartileLabels && (
        <>
          <text x={zeroX} y={h - 2} textAnchor="middle" fontSize="8.5" fill={T.ink3} fontFamily={T.bodyFont} letterSpacing="0.06em">0</text>
          <text x={hundredX} y={h - 2} textAnchor="middle" fontSize="8.5" fill={T.ink3} fontFamily={T.bodyFont} letterSpacing="0.06em">100</text>
        </>
      )}
    </svg>
  );
}

// ── QuartileBadge: glanceable rank callout w/ embedded density curve ────────
// distribution: full peer-universe numeric array. Renders PeerDensity inline.
// If omitted, falls back to the legacy 4-block quartile bar.
function QuartileBadge({
  metric, q, rank, total, totalLabel, value, valueFmt = (v) => v, note, T,
  compact = false, distribution, direction = "higher", ticker = "",
  densityW, densityH,
}) {
  const quartile = q ?? pq_quartileOf(rank, total);
  const fills = [T.accent, T.accent, T.ink2, T.ink3];
  const big = compact ? 22 : 32;
  const hasDensity = Array.isArray(distribution) && distribution.length > 3;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {metric && <div style={{ textTransform: "uppercase", letterSpacing: "0.18em", fontSize: 10, fontWeight: 600, color: T.ink3 }}>{metric}</div>}
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontFamily: T.displayFont, fontSize: big, lineHeight: 1, color: T.ink, letterSpacing: "-0.01em", fontWeight: 500 }}>{valueFmt(value)}</span>
      </div>
      {/* Quartile label sits above the curve, like Capture.png */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", fontSize: 10, color: T.ink3 }}>
        <span style={{ color: quartile <= 2 ? T.accent : T.ink2, fontWeight: 600, letterSpacing: "0.04em" }}>
          {quartile === 1 ? "TOP QUARTILE" : quartile === 2 ? "2ND QUARTILE" : quartile === 3 ? "3RD QUARTILE" : "BOTTOM QUARTILE"}
        </span>
        {note && <span style={{ fontStyle: "italic", textAlign: "right", maxWidth: "60%", lineHeight: 1.3 }}>{note}</span>}
      </div>
      {hasDensity ? (
        <div style={{ marginTop: 2 }}>
          <PeerDensity
            peers={distribution}
            value={value}
            direction={direction}
            ticker={ticker}
            T={T}
            w={densityW ?? (compact ? 240 : 320)}
            h={densityH ?? (compact ? 56 : 68)}
          />
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 2, marginTop: 2 }}>
          {[1, 2, 3, 4].map((qi) => (
            <div key={qi} style={{ height: 5, background: qi === quartile ? fills[quartile - 1] : T.rule2 }} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── PeerStrip: horizontal axis with all peers as dots, fund highlighted ──────
// Used to show distribution + position. Pass `peers` as [{ticker, value, highlight?}].
function PeerStrip({
  peers, valueFmt = (v) => v.toFixed(1), title, direction = "higher", T,
  w = 540, h = 92, padding = { l: 14, r: 14, t: 22, b: 28 },
  trimOutliers = false,
}) {
  const sorted = [...peers].map((p) => p.value).sort((a, b) => a - b);
  // For "neutral", display full range. For others, trim is optional.
  let domain;
  if (trimOutliers && sorted.length >= 6) {
    // Use 5th–95th to keep MAIN/HTGC-style outliers from dominating
    domain = [sorted[1], sorted[sorted.length - 2]];
  } else {
    const min = sorted[0], max = sorted[sorted.length - 1];
    const pad = (max - min) * 0.08;
    domain = [min - pad, max + pad];
  }
  const [xMin, xMax] = domain;
  const xAt = (v) => {
    const clamped = Math.max(xMin, Math.min(xMax, v));
    return padding.l + (clamped - xMin) / (xMax - xMin) * (w - padding.l - padding.r);
  };

  // Quartile boundaries from the actual peer set, in display direction.
  const q1 = sorted[Math.floor(sorted.length * 0.25)];
  const med = sorted[Math.floor(sorted.length * 0.5)];
  const q3 = sorted[Math.floor(sorted.length * 0.75)];

  const baseY = padding.t + (h - padding.t - padding.b) / 2;

  // For "higher better": top quartile = right side. For "lower": left side.
  const topBetterRight = direction === "higher";
  const topShade = T.accent;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block" }}>
      {/* Quartile bands — light shaded background */}
      <rect x={padding.l} y={baseY - 10} width={xAt(q1) - padding.l} height={20}
        fill={direction === "lower" ? topShade : T.rule} opacity={direction === "lower" ? 0.18 : 0.5} />
      <rect x={xAt(q1)} y={baseY - 10} width={xAt(med) - xAt(q1)} height={20} fill={T.rule} opacity={0.35} />
      <rect x={xAt(med)} y={baseY - 10} width={xAt(q3) - xAt(med)} height={20} fill={T.rule} opacity={0.35} />
      <rect x={xAt(q3)} y={baseY - 10} width={(w - padding.r) - xAt(q3)} height={20}
        fill={direction === "higher" ? topShade : T.rule} opacity={direction === "higher" ? 0.18 : 0.5} />

      {/* Center axis */}
      <line x1={padding.l} x2={w - padding.r} y1={baseY} y2={baseY} stroke={T.ink3} strokeOpacity="0.4" strokeWidth="1" />

      {/* Quartile dividers */}
      {[q1, med, q3].map((v, i) => (
        <line key={i} x1={xAt(v)} x2={xAt(v)} y1={baseY - 11} y2={baseY + 11} stroke={T.ink3} strokeOpacity="0.55" strokeWidth="1" strokeDasharray="2 2" />
      ))}

      {/* Peer dots — non-highlighted */}
      {peers.filter((p) => !p.highlight).map((p, i) => (
        <g key={p.ticker + i}>
          <circle cx={xAt(p.value)} cy={baseY} r={4} fill={T.ink2} opacity="0.7" />
          <text x={xAt(p.value)} y={baseY - 14} textAnchor="middle" fontSize="9"
            fill={T.ink3} fontFamily={T.monoFont}>{p.ticker}</text>
        </g>
      ))}

      {/* Highlighted fund — bigger gold dot */}
      {peers.filter((p) => p.highlight).map((p, i) => (
        <g key={"hl" + i}>
          <circle cx={xAt(p.value)} cy={baseY} r={9} fill="none" stroke={T.accent} strokeWidth="1.5" opacity="0.4" />
          <circle cx={xAt(p.value)} cy={baseY} r={6} fill={T.accent} stroke="#fff" strokeWidth="1.5" />
          <text x={xAt(p.value)} y={baseY + 22} textAnchor="middle" fontSize="11"
            fill={T.ink} fontFamily={T.displayFont} fontWeight="600">
            {p.ticker} · {valueFmt(p.value)}
          </text>
        </g>
      ))}

      {/* Quartile labels (Q1..Q4) along the bottom */}
      {[
        { l: "Q4", x: (padding.l + xAt(q1)) / 2 },
        { l: "Q3", x: (xAt(q1) + xAt(med)) / 2 },
        { l: "Q2", x: (xAt(med) + xAt(q3)) / 2 },
        { l: "Q1", x: (xAt(q3) + (w - padding.r)) / 2 },
      ].map((t, i) => {
        // Flip Q-labels for "lower better"
        const lab = direction === "lower"
          ? (["Q1","Q2","Q3","Q4"][i])
          : t.l;
        return (
          <text key={i} x={t.x} y={h - 6} textAnchor="middle" fontSize="9"
            fill={T.ink3} fontFamily={T.bodyFont} letterSpacing="0.08em">{lab}</text>
        );
      })}
    </svg>
  );
}

// ── PeerStandingBand: card+grid showing 4-6 metrics at once ──────────────────
// Each item: { key, label, value, valueFmt, rank, total, direction, note,
//              distribution }
// distribution = numeric array of the full peer universe for that metric.
function PeerStandingBand({ items, T, eyebrow, title, subtitle, footnote, ticker }) {
  return (
    <div style={{ padding: "0 72px 56px" }}>
      <div style={{ background: T.surface, border: `1px solid ${T.rule}` }}>
        <div style={{ padding: "28px 36px 18px", borderBottom: `1px solid ${T.rule2}`, display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div>
            <div style={{ textTransform: "uppercase", letterSpacing: "0.18em", fontSize: 10, fontWeight: 600, color: T.accent }}>{eyebrow}</div>
            <h2 style={{ fontFamily: T.displayFont, fontWeight: 500, fontSize: 30, margin: "6px 0 0", letterSpacing: "-0.015em" }}>{title}</h2>
            {subtitle && <div style={{ fontSize: 13, color: T.ink2, marginTop: 8, maxWidth: 720 }}>{subtitle}</div>}
          </div>
          <div style={{ fontSize: 11, color: T.ink3, fontStyle: "italic", textAlign: "right", maxWidth: 220 }}>
            {footnote}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${items.length >= 4 ? 4 : items.length}, 1fr)` }}>
          {items.map((it, i) => (
            <div key={it.key} style={{
              padding: "24px 28px 26px",
              borderRight: i < items.length - 1 && (i + 1) % 4 !== 0 ? `1px solid ${T.rule2}` : "none",
              borderBottom: items.length > 4 && i < items.length - 4 ? `1px solid ${T.rule2}` : "none",
            }}>
              <QuartileBadge
                metric={it.label}
                rank={it.rank}
                total={it.total}
                totalLabel={it.totalLabel}
                value={it.value}
                valueFmt={it.valueFmt}
                note={it.note}
                direction={it.direction}
                distribution={it.distribution}
                ticker={ticker}
                T={T}
                densityW={320}
                densityH={74}
              />
            </div>
          ))}
        </div>
        {/* Axis legend — the x-axis is normalized identically on every card so cross-metric reads are direct */}
        <div style={{ padding: "12px 36px 18px", borderTop: `1px solid ${T.rule2}`, fontSize: 11, color: T.ink3, display: "flex", gap: 24, flexWrap: "wrap" }}>
          <span><span style={{ fontWeight: 600, color: T.ink2 }}>0</span> = lowest peer · <span style={{ fontWeight: 600, color: T.ink2 }}>100</span> = highest peer (min–max normalized)</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <svg width="18" height="10" style={{ display: "inline-block", verticalAlign: "middle" }}>
              <line x1="9" x2="9" y1="0" y2="10" stroke={T.accent} strokeWidth="1.6" />
            </svg>
            {ticker || "Fund"} position
          </span>
        </div>
      </div>
    </div>
  );
}

// ── SpreadBandChart: time series with fund line + peer median band ────────────
// BDC-only — premium / discount to NAV over time, with peer p25–p75 band.
function SpreadBandChart({
  labels, fund, peerMed, peerP25, peerP75, T, w = 720, h = 240,
  padding = { t: 16, r: 16, b: 28, l: 44 },
}) {
  const all = [...fund, ...peerMed, ...peerP25, ...peerP75];
  const min = Math.min(...all), max = Math.max(...all);
  const yPad = (max - min) * 0.15;
  const yMin = Math.floor((min - yPad) / 2) * 2;
  const yMax = Math.ceil((max + yPad) / 2) * 2;
  const cw = w - padding.l - padding.r, ch = h - padding.t - padding.b;
  const xAt = (i) => padding.l + i / (labels.length - 1) * cw;
  const yAt = (v) => padding.t + ch - (v - yMin) / (yMax - yMin) * ch;
  const zeroY = yAt(0);

  // Build band path (p75 forward, p25 reversed)
  const bandTop = peerP75.map((v, i) => `${i ? "L" : "M"} ${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`).join(" ");
  const bandBot = peerP25.map((v, i) => `L ${xAt(peerP25.length - 1 - i).toFixed(1)} ${yAt(peerP25[peerP25.length - 1 - i]).toFixed(1)}`).join(" ");
  // Actually re-build bottom in reverse to close the polygon
  const bandPath =
    peerP75.map((v, i) => `${i ? "L" : "M"} ${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`).join(" ") +
    " " +
    [...peerP25].reverse().map((v, i) => `L ${xAt(peerP25.length - 1 - i).toFixed(1)} ${yAt(v).toFixed(1)}`).join(" ") +
    " Z";

  const yTicks = Array.from({ length: 5 }, (_, i) => yMin + i / 4 * (yMax - yMin));

  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block", fontFamily: "inherit" }}>
      {/* Y grid */}
      {yTicks.map((t, i) => (
        <g key={i}>
          <line x1={padding.l} x2={w - padding.r} y1={yAt(t)} y2={yAt(t)} stroke={T.ink3} strokeOpacity={i === 0 ? 0.25 : 0.08} strokeWidth="1" strokeDasharray={t === 0 ? "0" : "2 4"} />
          <text x={padding.l - 8} y={yAt(t) + 3} textAnchor="end" fontSize="10" fill={T.ink3} fontFamily={T.monoFont}>
            {t > 0 ? "+" : ""}{t.toFixed(0)}%
          </text>
        </g>
      ))}
      {/* Zero line emphasized */}
      <line x1={padding.l} x2={w - padding.r} y1={zeroY} y2={zeroY} stroke={T.ink2} strokeOpacity="0.5" strokeWidth="1" />
      <text x={w - padding.r - 4} y={zeroY - 4} textAnchor="end" fontSize="9" fill={T.ink3} fontStyle="italic">NAV parity</text>

      {/* Peer band */}
      <path d={bandPath} fill={T.ink2} opacity="0.10" />
      {/* Peer median */}
      <path
        d={peerMed.map((v, i) => `${i ? "L" : "M"} ${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`).join(" ")}
        fill="none" stroke={T.ink2} strokeWidth="1.4" strokeDasharray="3 3" opacity="0.7"
      />
      {/* Fund line */}
      <path
        d={fund.map((v, i) => `${i ? "L" : "M"} ${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`).join(" ")}
        fill="none" stroke={T.accent} strokeWidth="2.2"
      />
      {/* Fund last-point dot */}
      <circle cx={xAt(fund.length - 1)} cy={yAt(fund[fund.length - 1])} r={4.5} fill={T.accent} stroke="#fff" strokeWidth="1.5" />

      {/* X labels — every other */}
      {labels.map((lab, i) => i % 2 === 0 || i === labels.length - 1 ? (
        <text key={i} x={xAt(i)} y={h - 8} textAnchor="middle" fontSize="9" fill={T.ink3}>{lab}</text>
      ) : null)}
    </svg>
  );
}

// ── PeerScatter: 2D scatter (e.g. distribution rate vs premium) ──────────────
function PeerScatter({
  peers, xKey, yKey, xLabel, yLabel, xFmt = (v) => v.toFixed(1), yFmt = (v) => v.toFixed(1),
  T, w = 360, h = 280, padding = { t: 16, r: 16, b: 36, l: 44 },
}) {
  const xs = peers.map((p) => p[xKey]).filter((v) => v != null);
  const ys = peers.map((p) => p[yKey]).filter((v) => v != null);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const xPad = (xMax - xMin) * 0.12, yPad = (yMax - yMin) * 0.12;
  const cw = w - padding.l - padding.r, ch = h - padding.t - padding.b;
  const xAt = (v) => padding.l + (v - (xMin - xPad)) / ((xMax + xPad) - (xMin - xPad)) * cw;
  const yAt = (v) => padding.t + ch - (v - (yMin - yPad)) / ((yMax + yPad) - (yMin - yPad)) * ch;

  // Linear regression line through points (least squares) for trend
  const xMean = xs.reduce((a, b) => a + b, 0) / xs.length;
  const yMean = ys.reduce((a, b) => a + b, 0) / ys.length;
  let num = 0, den = 0;
  xs.forEach((x, i) => { num += (x - xMean) * (ys[i] - yMean); den += (x - xMean) ** 2; });
  const slope = den === 0 ? 0 : num / den;
  const intercept = yMean - slope * xMean;
  const trendX1 = xMin - xPad, trendX2 = xMax + xPad;
  const trendY1 = intercept + slope * trendX1;
  const trendY2 = intercept + slope * trendX2;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block", fontFamily: "inherit" }}>
      {/* Grid */}
      {[0, 0.25, 0.5, 0.75, 1].map((t, i) => (
        <g key={i}>
          <line x1={padding.l} x2={w - padding.r} y1={padding.t + ch * t} y2={padding.t + ch * t} stroke={T.ink3} strokeOpacity="0.08" />
          <line x1={padding.l + cw * t} x2={padding.l + cw * t} y1={padding.t} y2={padding.t + ch} stroke={T.ink3} strokeOpacity="0.08" />
        </g>
      ))}
      {/* Trend */}
      <line
        x1={xAt(trendX1)} y1={yAt(trendY1)} x2={xAt(trendX2)} y2={yAt(trendY2)}
        stroke={T.ink3} strokeOpacity="0.55" strokeWidth="1" strokeDasharray="3 4"
      />
      {/* Peer dots — label only the highlighted fund + flagged outliers */}
      {peers.map((p, i) => p[xKey] != null && p[yKey] != null ? (
        <g key={p.ticker + i}>
          <circle cx={xAt(p[xKey])} cy={yAt(p[yKey])} r={p.highlight ? 6 : 3}
            fill={p.highlight ? T.accent : T.ink2}
            stroke={p.highlight ? "#fff" : "none"}
            strokeWidth={p.highlight ? 1.5 : 0}
            opacity={p.highlight ? 1 : 0.55} />
          {(p.highlight || p.label) && (
            <text x={xAt(p[xKey]) + (p.highlight ? 10 : 6)} y={yAt(p[yKey]) + 3}
              fontSize={p.highlight ? 11 : 9} fontFamily={T.monoFont}
              fill={p.highlight ? T.ink : T.ink3}
              fontWeight={p.highlight ? 600 : 400}>
              {p.ticker}
            </text>
          )}
        </g>
      ) : null)}
      {/* Axis labels */}
      <text x={(padding.l + w - padding.r) / 2} y={h - 6} textAnchor="middle" fontSize="10"
        fill={T.ink3} letterSpacing="0.04em">{xLabel}</text>
      <text x={12} y={(padding.t + h - padding.b) / 2} fontSize="10" fill={T.ink3}
        letterSpacing="0.04em" transform={`rotate(-90 12 ${(padding.t + h - padding.b) / 2})`} textAnchor="middle">{yLabel}</text>
    </svg>
  );
}

Object.assign(window, { QuartileBadge, PeerStrip, PeerDensity, PeerStandingBand, SpreadBandChart, PeerScatter, pq_quartileOf, pq_ordinal, pq_kde });
