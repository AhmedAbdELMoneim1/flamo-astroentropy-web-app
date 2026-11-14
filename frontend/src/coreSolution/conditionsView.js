// "Your conditions and the evidence" (Round 11 §11.3): pure builders for the oxygen ladder, the live spread-rate chart, the nearest-tests list and the map overlay.
// Input is ONLY what GET /api/nearest returned (flameo's nearest_tests, trimmed) plus the two slider values. Nothing here computes a number the screen shows as a result:
// counts, the partial pressure, its formula, the tested ranges and the markers all arrive from flameo. The geometry (positions, ticks) is drawing, not data.
import { niceScale, placeLabels } from './chartAxis.js';
import { clean, valueText, tick } from './display.js';

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const tx = s => esc(clean(s));

export const SPREAD_W = { v: 420 };
export const LADDER = { W: 640, L: 22, R: 22, BW: 28, BH: 26, gap: 6 };

/** Horizontal oxygen ladder: the 0..100 % scale runs left to right. Scenario atmospheres sit above the axis, sourced markers below it, each a numbered badge
 *  put in the first free lane so no two badges overlap. Only the badges are drawn; the text of a marker appears when the user selects it. */
export function ladderModel(cond, o2, width) {
    const { L, R, BW, BH, gap } = LADDER, W = Math.max(320, Math.min(1000, width || LADDER.W));
    const X = v => L + (Math.max(0, Math.min(100, v)) / 100) * (W - L - R);
    const items = [];
    (cond.scenarios || []).forEach(s => items.push({ kind: 'scenario', o2: s.o2_pct, text: `${s.label}: ${s.o2_pct} % at ${s.p_psi} psi`, label: s.label, ref: s.id, tip: s.formula, p_psi: s.p_psi }));
    (cond.markers || []).forEach(m => items.push({ kind: 'evidence', o2: m.o2_pct, text: m.label, ref: m.ref, page: m.page, source: m.source_title }));
    items.sort((a, b) => a.o2 - b.o2);
    items.forEach((it, i) => { it.n = i + 1; it.x = X(it.o2) });
    const lanes = { scenario: [], evidence: [] };                  // per side: the right edge of the last badge in each lane
    items.forEach(it => {
        const side = lanes[it.kind]; let k = side.findIndex(r => it.x - BW / 2 >= r + 4);
        if (k < 0) { side.push(0); k = side.length - 1 }
        side[k] = it.x + BW / 2; it.lane = k;
    });
    const top = 34, laneH = BH + gap, nS = Math.max(1, lanes.scenario.length), nE = Math.max(1, lanes.evidence.length);
    const axisY = top + nS * laneH + 12, H = axisY + 34 + nE * laneH + 30;
    items.forEach(it => {
        const y = it.kind === 'scenario' ? axisY - 14 - BH - it.lane * laneH : axisY + 34 + it.lane * laneH;
        it.y = axisY; it.box = { x: it.x - BW / 2, y, w: BW, h: BH };
    });
    const user = { x: X(o2), label: `${valueText(o2)} %`, w: 74, h: 20 };
    const band = cond.ranges && cond.ranges.o2_min != null ? { x0: X(cond.ranges.o2_min), x1: X(cond.ranges.o2_max), o2_min: cond.ranges.o2_min, o2_max: cond.ranges.o2_max } : null;
    return { W, H, L, axisY, X, ticks: [0, 25, 50, 75, 100].map(v => ({ v, x: X(v) })), markers: items, user, band };
}

/** opts: { sel: number | null (the selected badge), scenario: id | null (the atmosphere the sliders are on) } */
export function ladderSvg(m, opts = {}) {
    const { W, H, axisY, L } = m, { sel = null, scenario = null } = opts;
    let g = '';
    if (m.band) g += `<rect x="${m.band.x0.toFixed(1)}" y="${axisY - 6}" width="${(m.band.x1 - m.band.x0).toFixed(1)}" height="12" rx="3" fill="#7fb8ff" opacity=".25"><title>tested range of the PSI tests: ${m.band.o2_min}–${m.band.o2_max} %</title></rect>`;
    g += `<line x1="${L}" x2="${W - LADDER.R}" y1="${axisY}" y2="${axisY}" stroke="currentColor" opacity=".55" stroke-width="1.5"/>`;
    m.ticks.forEach(t => { g += `<line x1="${t.x.toFixed(1)}" x2="${t.x.toFixed(1)}" y1="${axisY - 5}" y2="${axisY + 5}" stroke="currentColor" opacity=".6"/><text class="lt" x="${Math.max(10, Math.min(W - 14, t.x)).toFixed(1)}" y="${axisY + 24}" text-anchor="middle">${tick(t.v)}${t.v === 100 ? ' %' : ''}</text>` });
    m.markers.forEach(k => {
        const b = k.box, on = k.n === sel, act = k.kind === 'scenario' && scenario && k.ref === scenario;
        const covered = m.band && k.o2 >= m.band.o2_min && k.o2 <= m.band.o2_max, col = k.kind === 'scenario' ? (act ? 'var(--accent, #ffe14d)' : covered ? '#7fb8ff' : '#c9d3dc') : '#ffb347', cy = b.y + (k.kind === 'scenario' ? b.h : 0);
        g += `<line x1="${k.x.toFixed(1)}" y1="${axisY}" x2="${k.x.toFixed(1)}" y2="${cy.toFixed(1)}" stroke="${col}" stroke-width="${on || act ? 1.6 : 1}" opacity="${on || act ? .95 : .5}"/><circle cx="${k.x.toFixed(1)}" cy="${axisY}" r="${on || act ? 6 : 4}" style="fill:${col}"/>` +
            `<g class="lm${on ? ' on' : ''}${act ? ' act' : ''}" data-n="${k.n}" data-kind="${k.kind}" tabindex="0" role="button" aria-label="${tx(k.text)}"><rect x="${b.x.toFixed(1)}" y="${b.y.toFixed(1)}" width="${b.w}" height="${b.h}" rx="5" style="fill:${on || act ? col : '#04101c'}" stroke="${col}" stroke-width="${on || act ? 2.4 : 1.4}"/><text x="${(b.x + b.w / 2).toFixed(1)}" y="${(b.y + b.h / 2 + 5).toFixed(1)}" text-anchor="middle" style="fill:${on || act ? '#04101c' : col}" font-weight="700">${k.n}</text><title>${tx(k.text)}</title></g>`;
    });
    const ux = Math.max(m.user.w / 2, Math.min(W - m.user.w / 2, m.user.x));
    g += `<g class="lu"><line x1="${m.user.x.toFixed(1)}" x2="${m.user.x.toFixed(1)}" y1="22" y2="${axisY + 8}" stroke="#fff" stroke-width="1.6" stroke-dasharray="4 3" opacity=".8"/><path d="M${(m.user.x - 7).toFixed(1)},${axisY - 1}l7,-12l7,12z" fill="#fff"/><text x="${ux.toFixed(1)}" y="14" text-anchor="middle" style="fill:#fff" font-weight="700">YOU ${tx(m.user.label)}</text></g>`;
    const key = m.band ? `<text class="lt" x="${L}" y="${H - 4}" style="fill:#7fb8ff">■ blue: oxygen inside the tested range, ${esc(m.band.o2_min)}–${esc(m.band.o2_max)} %</text><text class="lt" x="${W - LADDER.R}" y="${H - 4}" text-anchor="end" style="fill:#c9d3dc">□ grey: outside it</text>` : '';
    return `<svg class="ladder" viewBox="0 0 ${W} ${H.toFixed(0)}" width="${W}" role="group" aria-label="Oxygen ladder, 0 to 100 percent: your value, the scenario atmospheres above the line and sourced markers below it. Select a numbered badge to read it.">${g}${key}</svg>`;
}

/** What the selected badge says (nothing is listed until the user selects one). */
export function ladderDetail(m, sel) {
    const k = m.markers.find(x => x.n === sel);
    if (!k) return `<p class="ldh">Select a numbered badge on the ladder to read what it says. Atmospheres are above the line, sourced oxygen markers below it.</p>`;
    const src = k.kind === 'evidence' && k.source ? `<small class="nt">${tx(k.source)}${k.page ? ', page ' + esc(k.page) : ''}</small>` : '';
    const ask = k.kind === 'evidence' ? `<button type="button" class="chip" data-askm="${k.n}">Ask Flamo about this source</button>` : '';
    return `<div class="ldc ${k.kind}"><b class="bd">${k.n}</b><div><p>${tx(k.text)}</p>${src}${k.tip ? `<small class="nt">${tx(k.tip)}</small>` : ''}${ask}</div></div>`;
}

/** Kept for compatibility: the full numbered key. The screen no longer prints it. */
export function ladderKey(m) {
    return m.markers.map(k => `<li><b class="bd">${k.n}</b><span>${tx(k.text)}${k.kind === 'evidence' && k.source ? ` <small class="nt">${tx(k.source)}${k.page ? ', page ' + esc(k.page) : ''}</small>` : ''}</span></li>`).join('');
}

/** Spread-rate-vs-oxygen chart with a vertical line at the user's oxygen. Inside the tested range the points near your conditions are highlighted; outside it there is no line through the data and no extrapolation. */
export function spreadModel(cond, o2) {
    const pts = cond.spread_points || [];
    if (!pts.length) return null;
    const W = Math.max(320, Math.min(900, SPREAD_W.v)), H = Math.round(Math.max(300, Math.min(420, W * .55))), L = 56, R = 18, T = 40, B = 52;
    // the axes come from the measured points alone, so moving the oxygen slider never rescales the chart: only the line moves (and sticks to the edge, marked, when you are outside the measured range)
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
    const xsc = niceScale(Math.min(...xs), Math.max(...xs)), ysc = niceScale(0, Math.max(...ys));
    const X = x => L + (x - xsc.min) / ((xsc.max - xsc.min) || 1) * (W - L - R), Y = y => H - B - (y - ysc.min) / ((ysc.max - ysc.min) || 1) * (H - T - B);
    const r = cond.ranges || {};
    const inside = r.spread_o2_min != null && o2 >= r.spread_o2_min && o2 <= r.spread_o2_max;
    const side = o2 < xsc.min ? 'left' : o2 > xsc.max ? 'right' : null;
    const line = X(Math.max(xsc.min, Math.min(xsc.max, o2)));
    return { W, H, L, R, T, B, X, Y, xsc, ysc, pts, inside, line, o2, side };
}

const SPREAD_COLORS = ['#46f0a0', '#ffb347', '#7fb8ff', '#ff6a8a', '#c9a0ff', '#f0e046', '#5ee0e0', '#ff8f5a'];
export function spreadSeries(m) {
    const names = [...new Set(m.pts.map(p => p.investigation || 'other'))];
    return names.map((n, i) => ({ name: n, color: SPREAD_COLORS[i % SPREAD_COLORS.length] }));
}

export function spreadSvg(m) {
    let g = '';
    const col = Object.fromEntries(spreadSeries(m).map(x => [x.name, x.color]));
    m.ysc.ticks.forEach(v => { g += `<line class="gr" x1="${m.L}" x2="${m.W - m.R}" y1="${m.Y(v).toFixed(1)}" y2="${m.Y(v).toFixed(1)}"/><text x="${m.L - 8}" y="${(m.Y(v) + 5).toFixed(1)}" text-anchor="end">${tick(v)}</text>` });
    m.xsc.ticks.forEach(v => { g += `<line class="gr" x1="${m.X(v).toFixed(1)}" x2="${m.X(v).toFixed(1)}" y1="${m.T}" y2="${m.H - m.B}"/><text x="${m.X(v).toFixed(1)}" y="${m.H - m.B + 22}" text-anchor="middle">${tick(v)}</text>` });
    const dots = m.pts.map(p => `<circle cx="${m.X(p.x).toFixed(1)}" cy="${m.Y(p.y).toFixed(1)}" r="${p.near && m.inside ? 7 : 5}" style="fill:${col[p.investigation || 'other']}" fill-opacity=".92" stroke="${p.near && m.inside ? '#fff' : '#04101c'}" stroke-width="${p.near && m.inside ? 2 : 1}"><title>${tx(p.investigation || '')}: ${esc(valueText(p.y))} mm/s at ${esc(valueText(p.x))} %</title></circle>`).join('');
    const edge = m.side === 'left' ? '◄ ' : m.side === 'right' ? ' ►' : '', anchorEnd = m.line > m.W - 190, lab = `your oxygen ${valueText(m.o2)} %${m.side ? ' (outside the measured range)' : ''}`;
    const line = `<line x1="${m.line.toFixed(1)}" x2="${m.line.toFixed(1)}" y1="${m.T - 8}" y2="${m.H - m.B}" stroke="#fff" stroke-width="2" stroke-dasharray="5 4"/><text x="${(anchorEnd ? m.line - 6 : m.line + 6).toFixed(1)}" y="${m.T - 14}" style="fill:#fff" font-weight="700" text-anchor="${anchorEnd ? 'end' : 'start'}">${m.side === 'left' ? edge : ''}${tx(lab)}${m.side === 'right' ? edge : ''}</text>`;
    return `<svg class="chart" data-geo='${JSON.stringify({ k: 'spread', W: m.W, H: m.H, L: m.L, R: m.R, T: m.T, B: m.B, log: false, a0: m.xsc.min, a1: m.xsc.max })}' viewBox="0 0 ${m.W} ${m.H}" role="img" aria-label="spread rate versus oxygen, with your oxygen marked">${g}${dots}${line}<text x="${((m.L + m.W - m.R) / 2).toFixed(1)}" y="${m.H - 8}" text-anchor="middle">oxygen (%)</text><text x="6" y="16" text-anchor="start">spread rate (mm/s)</text></svg><div class="lgs lgx">${spreadSeries(m).map(x => `<span class="lg"><i style="background:${x.color};border:1.5px solid ${x.color}"></i>${tx(x.name)}</span>`).join('')}</div>`;
}

/** What the map adds to the base chart: the tests within tolerance (ringed) and the user's point. */
export function mapExtras(cond, o2, psi) {
    return { near: (cond.map_points || []).map(p => ({ x: p.x, y: p.y })), mine: { x: psi, y: o2 } };
}

/** The nearest tests as a compact list: investigation, material, conditions (psi first, kPa small), outcome. */
export function nearHtml(cond) {
    const rows = cond.rows || [];
    const head = cond.n_near > 0
        ? `<p class="yn"><b>${esc(cond.n_near)}</b> tests near your point in <b>${esc(cond.n_psis)}</b> ${cond.n_psis === 1 ? 'investigation' : 'investigations'}${cond.n_spread != null ? `; <b>${esc(cond.n_spread)}</b> of them have a measured flame spread rate` : ''}</p>`
        : `<p class="yn">No PSI test at these conditions. The nearest tested points:</p>`;
    const body = rows.map(r => `<tr><td>${tx(r.investigation)}<br><small class="nt">${tx(r.material || '')}${r.flight ? ' · ' + esc(r.flight) : ''}</small></td><td>${esc(valueText(r.o2_pct))} %<br>${esc(valueText(r.p_psi))} psi${r.p_kpa != null ? ` <small class="nt">(${esc(valueText(r.p_kpa))} kPa)</small>` : ''}</td><td>${tx(r.outcome || '')}</td></tr>`).join('');
    return head + (rows.length ? `<div class="tw"><table class="yt"><thead><tr><th>investigation</th><th>conditions</th><th>outcome</th></tr></thead><tbody>${body}</tbody></table></div>` : '') +
        (cond.rows_limit_note ? `<p class="nt">${esc(cond.rows_limit_note)}</p>` : '') + (cond.gaps || []).map(g => `<p class="nt">${tx(g)}</p>`).join('');
}

/** Every string the panel and its sections would print (the display audit runs over this). */
export function conditionStrings(cond, o2, psi) {
    const out = [];
    if (!cond) return out;
    const lm = ladderModel(cond, o2);
    lm.markers.forEach(k => out.push(k.text));
    out.push(cond.po2 ? `${cond.po2.value_psi} psi` : '', cond.po2?.formula || '', cond.source || '', ...(cond.gaps || []), ...(cond.speak || []));
    out.push(nearHtml(cond).replace(/<[^>]+>/g, ' '));
    return out.filter(Boolean);
}
