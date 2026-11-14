/**
 * FlameDashboard.jsx
 * React wrapper around the "Flame in Freefall" HUD dashboard.
 *
 * Styles live in ./FlameDashboard.css (imported below).
 *
 * The dashboard engine (HUD SVG frames, resizable panels, sliders…) is imperative, so it is mounted and
 * disposed from a React component via useEffect. It holds NO content of its own: every number, table, chart,
 * ranking and sentence arrives from the agent (view.open -> setData, answer.show -> showAnswer).
 *
 * One layout for all four categories, two states each:
 *   overview  summary, KPIs, chart, "Most relevant investigations", table, "What the authors report", open questions, "Ask me"
 *   answer    the answer replaces the overview panels; the ranking panel stays; a chip goes back to the overview
 *
 * Imperative API (via ref): setCategory, addMessage, setData, showAnswer, setCoverage, setTexts, setValues, setLoading,
 * setError, setVoiceState, setVoiceAmplitude, setTranscript, setAccent, setSuitActive, setHabitatActive, setViews, setView.
 */
import { niceScale, logScale, placeLabels } from './chartAxis.js';
import { SPREAD_W, ladderModel, ladderSvg, ladderDetail, ladderKey, spreadModel, spreadSvg, nearHtml } from './conditionsView.js';
import React, { useEffect, useImperativeHandle, useRef, forwardRef, useState } from 'react';
import './FlameDashboard.css';
import { createPortal } from 'react-dom';
import EmberHead from '../siAssistant/EmberHead.jsx';
import { CATEGORIES, CATEGORY_ORDER, HOME_ACCENT, ENVIRONMENTS, ENV_ORDER } from './categories';
import { clean, unitText, valueText, kpiParts, summaryParts, rankRowParts, cellText, tick } from './display.js';
import { createChatLog, nearBottom } from './chatLog.js';

/* ============ engine ============ */
/* ============ CONFIG ============ */
// Only the two conditions inputs remain (oxygen, pressure): they set custom conditions. Everything else on screen
// (tables, charts, rankings, text) comes from the agent's view.open / answer.show packets.
const SL = { oxygen: [0, 100, .5], pressure: [0, 75, .1] };          // pressure in psi, as in the challenge text
const SLIDERS = [
    { key: 'oxygen', label: 'Oxygen', unit: '%', min: SL.oxygen[0], max: SL.oxygen[1], step: SL.oxygen[2], fireRole: 'intensity' },
    { key: 'pressure', label: 'Pressure', unit: 'psi', min: SL.pressure[0], max: SL.pressure[1], step: SL.pressure[2], fireRole: 'intensity' },
];
const CAT_ICON = { prevention: 'prev', flammability: 'spread', detection: 'smoke', suppression: 'ext' };
const CONFIG = {
    colors: { home: '#7fb8ff', warn: '#ff4d6d', ok: '#46f0a0' },
    timing: { out: 300, in: 700, typeMs: 12, decodeMs: 300, glitchMs: 120 },
    order: CATEGORY_ORDER,
    cats: {},
};
CONFIG.colors.home = HOME_ACCENT;
CATEGORY_ORDER.forEach((id) => { CONFIG.cats[id] = { id, icon: CAT_ICON[id], sliders: SLIDERS, ...CATEGORIES[id] }; });
const IC = {
    home: 'M12 48L50 14L88 48M22 42V86H78V42Z',
    env: 'M50 10A40 40 0 1 0 50 90A40 40 0 1 0 50 10M10 50H90M50 10C20 35 20 65 50 90M50 10C80 35 80 65 50 90',
    spread: 'M50 8C95 45 85 92 50 92C15 92 8 60 30 38C34 55 44 55 46 48C52 32 44 20 50 8Z',
    mat: 'M50 8L88 29V71L50 92L12 71V29Z M12 29L50 50L88 29M50 50V92',
    smoke: 'M25 78H76A18 18 0 0 0 74 42A22 22 0 0 0 32 46A16 16 0 0 0 25 78Z',
    ign: 'M58 6L20 56H48L40 94L80 40H52Z',
    ext: 'M50 6C78 42 86 56 86 66A36 36 0 0 1 14 66C14 56 22 42 50 6Z',
    prev: 'M50 6L86 20V50C86 72 70 87 50 94C30 87 14 72 14 50V20Z',
    suit: 'M20 60A30 30 0 0 1 80 60V78H20Z M30 52H70V68H30Z',
    hab: 'M16 74A34 34 0 0 1 84 74Z M8 74H92 M50 40V56M36 74V60M64 74V60',
    iss: 'M38 36H62V64H38Z M38 50H22 M62 50H78 M6 38H22V62H6Z M78 38H94V62H78Z',
    srcPaper: 'M24 8H62L78 24V92H24Z M62 8V24H78 M34 44H68M34 58H68M34 72H58',
    srcDoc: 'M8 24H40L48 34H92V84H8Z',
    srcFind: 'M50 10L90 30V70L50 90L10 70V30Z M30 50L45 65L72 36',
    srcTable: 'M10 18H90V82H10Z M10 40H90M10 62H90M40 18V82',
    srcChal: 'M50 8L62 40L96 42L70 64L80 94L50 76L20 94L30 64L4 42L38 40Z'
};
const ic = k => `<svg viewBox="0 0 100 100" aria-hidden="true"><path d="${IC[k]}"/></svg>`;

/* ============ helpers ============ */
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x)), lerp = (a, b, k) => a + (b - a) * k;
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
// visible text: normalised (ligatures, O₂, µm) and escaped. esc() alone is for attributes.
const tx = s => esc(clean(s));
// slider and axis positions are computed, not data: a short rounded form
const fmt = v => typeof v === 'number' ? (v % 1 ? +v.toFixed(Math.abs(v) < 10 ? 2 : 1) : v) : (v == null ? '' : v);

// panels of the one layout, per state. A panel with nothing to show is skipped.
const SECS_OVERVIEW = ['sum', 'cmap', 'cspread', 'cnear', 'kpi', 'chart', 'rank', 'table', 'cards', 'gaps', 'ask'];
const SECS_ANSWER = ['back', 'ans', 'open', 'kpi', 'chart', 'rank', 'table', 'cards', 'gaps', 'src', 'ask'];
const secOn = (k, d) => k === 'kpi' ? !!d.kpis?.length
    : k === 'cmap' || k === 'cspread' || k === 'cnear' ? true
    : k === 'open' ? !!d.openQuestion          // the open-question state only when nothing was found (an answer never shows it)
    : k === 'src' ? !!d.sources?.length
    : k === 'gaps' ? !!d.gaps?.length && !d.openQuestion
        : k === 'chart' ? !!d.charts?.length
            : k === 'rank' ? !!d.ranking
                : k === 'table' ? !!d.table
                    : k === 'cards' ? !!d.cards?.length
                        : k === 'ask' ? !!d.suggestions?.length
                            : k === 'ans' ? !!(d.question || d.speak?.length)
                                : true;

// scatter: every series in its own colour (8+), hollow markers for series with marker "hollow" (burner stream),
// crosses with labels for "cross" (scenario points), and the astronaut's own point (custom conditions) from the sliders.
const PALETTE = ['#46f0a0', '#ffb347', '#7fb8ff', '#ff6a8a', '#c9a0ff', '#f0e046', '#5ee0e0', '#ff8f5a', '#a4e05e'];
const MAP_UI = { inv: null, legend: null, tol: null, nearest: [] };   // tol: flameo's {o2_pts, p_rel}; nearest: the tests to point at when none is within it   // inv: the PSI code the map is narrowed to; legend: every investigation series name (so the legend stays whole while narrowed)
let CHART_W = 600;   // drawn at the real pixel width, so a 12 px label is 12 px on screen
function scatterSvg(series, xl, yl, mine, near = []) {
    const all = series.filter(s => s.points?.length);
    if (!all.length) return '';
    const W = Math.max(300, Math.min(900, CHART_W)), H = Math.round(Math.max(280, Math.min(400, W * .6))), L = 46, R = 16, T = 34, B = 50, pts = all.flatMap(s => s.points);   // the axes come from the tests alone: moving your point never rescales the map
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    const xsc = lo > 0 && hi / lo > 4 ? logScale(lo, hi) : niceScale(lo, hi), ysc = niceScale(Math.min(...ys), Math.max(...ys));
    const fx = xsc.log ? (v => Math.log(v)) : (v => v), a0 = fx(xsc.min), a1 = fx(xsc.max);
    const X = x => L + (fx(x) - a0) / ((a1 - a0) || 1) * (W - L - R), Y = y => H - B - (y - ysc.min) / ((ysc.max - ysc.min) || 1) * (H - T - B);
    let g = '';
    ysc.ticks.forEach(v => { g += `<line class="gr" x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text x="${L - 6}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${tick(v)}</text>` });
    xsc.ticks.forEach(v => { g += `<line class="gr" x1="${X(v).toFixed(1)}" x2="${X(v).toFixed(1)}" y1="${T}" y2="${H - B}"/><text x="${X(v).toFixed(1)}" y="${H - B + 16}" text-anchor="middle">${tick(v)}</text>` });
    let ci = 0, dots = '', marks = [];
    const legend = [];
    const items = (MAP_UI.legend || all.filter(x => x.marker !== 'cross').map(x => ({ name: x.name, marker: x.marker })));
    const colOf = n => { const i = items.findIndex(x => x.name === n); return PALETTE[(i >= 0 ? i : 0) % PALETTE.length] };
    let sel = '';
    all.forEach(s => {
        const col = colOf(s.name);
        if (s.marker === 'cross') {
            s.points.forEach(p => marks.push(p));
            dots += s.points.map(p => `<path d="M${(X(p.x) - 5).toFixed(1)},${(Y(p.y) - 5).toFixed(1)}l10,10m0,-10l-10,10" stroke="#fff" stroke-width="2.4" fill="none"/>`).join('');
            s.points.filter(p => p.selected).forEach(p => {
                const cx = X(p.x), cy = Y(p.y), right = cx > W - 190;
                sel += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="14" fill="none" stroke="var(--accent,#ffe14d)" stroke-width="3"/><circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="20" fill="none" stroke="var(--accent,#ffe14d)" stroke-width="1" opacity=".5"/><text x="${(right ? cx - 26 : cx + 26).toFixed(1)}" y="${(cy + 5).toFixed(1)}" text-anchor="${right ? 'end' : 'start'}" style="fill:var(--accent,#ffe14d)" font-weight="700">${tx(p.label || 'selected atmosphere')}</text>`;
            });
        } else if (s.marker === 'hollow') {
            dots += s.points.map(p => `<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="3" style="fill:none" stroke="${col}" stroke-width="1.2" opacity=".55"/>`).join('');
        } else {
            dots += s.points.map(p => `<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="3.6" style="fill:${col}" fill-opacity=".9" stroke="#04101c" stroke-width=".8"/>`).join('');
        }
    });
    items.forEach(it => {
        const col = colOf(it.name), code = (it.name.match(/\((PSI-\d+)\)/) || [])[1] || (it.marker === 'hollow' ? 'burner' : /^other PSIs/i.test(it.name) ? 'other' : null), sw = `<i style="background:${it.marker === 'hollow' ? 'transparent' : col};border:1.5px solid ${col}"></i>`;
        legend.push(code ? `<button type="button" class="lg lgb${MAP_UI.inv === code ? ' on' : ''}" data-inv="${code}" aria-pressed="${MAP_UI.inv === code}" title="Show only ${code}">${sw}${tx(it.name)}</button>` : `<span class="lg">${sw}${tx(it.name)}</span>`);
    });
    // scenario points: a numbered badge (placed without overlaps) and a numbered legend line, instead of long text on the plot
    let me = '', badges = '', key = '';
    const boxes = marks.map((p, i) => ({ x: X(p.x), y: Y(p.y), w: 14, h: 14, i }));
    const blocked = [{ x: 0, y: 0, w: 220, h: T - 2 }];
    placeLabels(boxes, blocked, { x0: L, y0: T, x1: W - R, y1: H - B }).forEach((b, k) => {
        badges += `<line x1="${b.ax.toFixed(1)}" y1="${b.ay.toFixed(1)}" x2="${(b.x + 7).toFixed(1)}" y2="${(b.y + 7).toFixed(1)}" stroke="#fff" stroke-width=".8" opacity=".7"/><rect x="${b.x.toFixed(1)}" y="${b.y.toFixed(1)}" width="14" height="14" rx="3" fill="#04101c" stroke="#fff" stroke-width="1"/><text x="${(b.x + 7).toFixed(1)}" y="${(b.y + 11).toFixed(1)}" text-anchor="middle" fill="#fff" font-size="10">${k + 1}</text>`;
        key += `<span class="lg"><b class="bd">${k + 1}</b>${tx(marks[k].label || '')}</span>`;
    });
    near.forEach(p => { me += `<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="7" fill="none" stroke="#fff" stroke-width="1" stroke-dasharray="2 2" opacity=".6"/>` });
    if (mine && MAP_UI.tol) {                                  // the box that decides "near": drawn so you can see why a test counts or not
        const t = MAP_UI.tol, bx0 = Math.max(L, X(mine.x * (1 - t.p_rel))), bx1 = Math.min(W - R, X(mine.x * (1 + t.p_rel))), by0 = Math.max(T, Y(mine.y + t.o2_pts)), by1 = Math.min(H - B, Y(mine.y - t.o2_pts));
        if (bx1 > bx0 && by1 > by0) me += `<rect x="${bx0.toFixed(1)}" y="${by0.toFixed(1)}" width="${(bx1 - bx0).toFixed(1)}" height="${(by1 - by0).toFixed(1)}" rx="3" fill="#fff" fill-opacity=".07" stroke="#fff" stroke-width="1.2" stroke-dasharray="5 3" opacity=".8"><title>A test counts as near when it is inside this box: within ${esc(t.o2_pts)} oxygen points and ${esc(t.p_rel * 100)} percent of the pressure.</title></rect>`;
    }
    (MAP_UI.nearest || []).forEach(q => { me += `<circle cx="${Math.max(L, Math.min(W - R, X(q.x))).toFixed(1)}" cy="${Math.max(T, Math.min(H - B, Y(q.y))).toFixed(1)}" r="9" fill="none" stroke="var(--accent,#ffe14d)" stroke-width="2" stroke-dasharray="3 2"/>` });
    if (mine) {
        const mx = Math.max(L, Math.min(W - R, X(mine.x))), my = Math.max(T, Math.min(H - B, Y(mine.y))), right = mx > W - 170;
        me += `<g class="you"><line x1="${L}" x2="${mx.toFixed(1)}" y1="${my.toFixed(1)}" y2="${my.toFixed(1)}" stroke="#fff" stroke-width=".8" stroke-dasharray="3 3" opacity=".5"/><line x1="${mx.toFixed(1)}" x2="${mx.toFixed(1)}" y1="${my.toFixed(1)}" y2="${H - B}" stroke="#fff" stroke-width=".8" stroke-dasharray="3 3" opacity=".5"/><circle cx="${mx.toFixed(1)}" cy="${my.toFixed(1)}" r="9" style="fill:#04101c" fill-opacity=".6" stroke="#fff" stroke-width="2"/><circle cx="${mx.toFixed(1)}" cy="${my.toFixed(1)}" r="3" style="fill:#fff"/><text class="yl" x="${(right ? mx - 14 : mx + 14).toFixed(1)}" y="${(my - 10).toFixed(1)}" text-anchor="${right ? 'end' : 'start'}" fill="#fff" font-size="12" font-weight="700">YOU ${esc(valueText(mine.y))} % · ${esc(valueText(mine.x))} psi</text></g>`;
    }
    const geo = mine ? ` data-geo='${JSON.stringify({ k: 'map', W, H, L, R, T, B, log: !!xsc.log, a0, a1, y0: ysc.min, y1: ysc.max })}'` : '';
    return `<svg class="chart"${geo} viewBox="0 0 ${W} ${H}" role="img" aria-label="${tx(yl)} versus ${tx(xl)}">${g}${dots}${sel}${badges}${me}<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle">${tx(xl)}${xsc.log ? ' (log scale)' : ''}</text><text x="4" y="14" font-size="11" text-anchor="start">${tx(yl)}</text></svg><div class="lgs lgx">${legend.join('')}</div>${key ? `<div class="lgs lgk">${key}</div>` : ''}`;
}

// bars in the order the agent sent them: never sorted, never a ranking
function barsHtml(series) {
    const pts = (series[0] && series[0].points) || [], mx = Math.max(...pts.map(p => +p.y || 0), 1e-9);
    return pts.map(p => `<div class="rk bars"><span class="nm">${tx(p.x)}</span><div class="val"><div class="bt"><i style="width:${clamp((+p.y || 0) / mx * 100, 0, 100)}%"></i></div><b class="vl">${tx(valueText(p.y))}</b></div></div>`).join('');
}


/* stepped HUD outline: two small steps per corner, small notches on edges */
function stepPath(w, h, s, i, n) {
    const a = i, b = w - i, c = i, d = h - i, p = [], v = n && h > 160;
    p.push([a, c + 2 * s], [a + s, c + 2 * s], [a + s, c + s], [a + 2 * s, c + s], [a + 2 * s, c]);
    if (n) { const x = w * .32; p.push([x, c], [x + 6, c + 5], [x + 34, c + 5], [x + 40, c]) }
    p.push([b - 2 * s, c], [b - 2 * s, c + s], [b - s, c + s], [b - s, c + 2 * s], [b, c + 2 * s]);
    if (v) { const y = h * .4; p.push([b, y], [b - 5, y + 6], [b - 5, y + 34], [b, y + 40]) }
    p.push([b, d - 2 * s], [b - s, d - 2 * s], [b - s, d - s], [b - 2 * s, d - s], [b - 2 * s, d]);
    if (n) { const x = w * .6; p.push([x + 40, d], [x + 34, d - 5], [x + 6, d - 5], [x, d]) }
    p.push([a + 2 * s, d], [a + 2 * s, d - s], [a + s, d - s], [a + s, d - 2 * s], [a, d - 2 * s]);
    if (v) { const y = h * .65; p.push([a, y + 40], [a + 5, y + 34], [a + 5, y + 6], [a, y]) }
    return 'M' + p.map(q => q[0].toFixed(1) + ',' + q[1].toFixed(1)).join('L') + 'Z';
}
let UID = 0;
/* v: 'A' tab left, 'B' tab right, 'C' no tab */
function buildHudFrame(pn, v, title, watch) {
    const id = 'f' + (++UID), svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'fr'); pn.prepend(svg);
    let tt = null; if (v !== 'C') { tt = document.createElement('span'); tt.className = 'tt dc'; tt.textContent = title; pn.appendChild(tt) }
    watch(pn, () => {
        const w = pn.clientWidth, h = pn.clientHeight; if (!w || !h) return;
        const B = false, mx = (x, wd = 0) => B ? w - x - wd : x, tw = tt ? tt.offsetWidth + 36 : 0;
        const out = stepPath(w, h, 7, 0, true), inn = stepPath(w, h, 4, 6, false), R = (x, y, ww, hh, cls = 'a') => `<rect class="${cls}" x="${mx(x, ww)}" y="${y}" width="${ww}" height="${hh}"/>`;
        const bw = Math.min(120, w * .3), hs = Math.min(60, h * .15), vs = Math.min(70, h * .2);
        let blocks = R(24, h - 4, bw, 4) + R(0, h * .55, 4, hs) + R(w - 4, h * .2, 4, vs);
        blocks += v === 'C' ? R(w / 2 - 40, 0, 80, 4) : R(w - 90, 0, 50, 4);
        const tab = tt ? `<polygon class="a" points="${[[18, 0], [tw, 0], [tw + 10, 9], [tw + 24, 9], [tw + 34, 24], [18, 24]].map(q => mx(q[0]) + ',' + q[1]).join(' ')}"/>` : '';
        svg.innerHTML = `<defs><pattern id="${id}" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect class="a" width="3" height="7"/></pattern><linearGradient id="${id}g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--accent);stop-opacity:.16"/><stop offset="1" style="stop-color:var(--accent);stop-opacity:0"/></linearGradient></defs><path class="bgf" d="${out}" fill="rgba(4,18,28,.64)"/><path class="bgf" d="${out}" fill="url(#${id}g)"/><path class="o l" pathLength="1" d="${out}" stroke-width="1.5"/><path class="o l" pathLength="1" d="${inn}" stroke-opacity=".5"/>${blocks.replace('class="h"', `fill="url(#${id})"`)}${tab}`;
    });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => pn.isConnected && pn.dispatchEvent(new Event('fd-redraw')));
    pn.addEventListener('fd-redraw', () => watch(pn, null, true));
}

/* ============ CSS ============ */

/* ============ mountDashboard ============ */
function mountDashboard(container, options) {
    const o = Object.assign({ category: 'prevention', environment: 'spacecraft', valuesDebounceMs: 600 }, options || {}), C = CONFIG;
    const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const timers = new Set(), offs = [];
    const later = (f, ms) => { const t = setTimeout(() => { timers.delete(t); f() }, ms); timers.add(t); return t };
    const every = (f, ms) => { const t = setInterval(f, ms); timers.add(t); return t };
    const clr = t => { clearTimeout(t); clearInterval(t); timers.delete(t) };
    const on = (el, ev, fn, op) => { el.addEventListener(ev, fn, op); offs.push(() => el.removeEventListener(ev, fn, op)) };
    const CB = { environmentchange: 'onEnvironmentChange', categorychange: 'onCategoryChange', ask: 'onAsk', valueschange: 'onValuesChange', retry: 'onRetry', home: 'onHome', about: 'onAbout', mictoggle: 'onMicToggle', deafentoggle: 'onDeafenToggle', chatsend: 'onChatSend', suit: 'onSuit', habitat: 'onHabitat', iss: 'onIss', viewchange: 'onViewChange', answerdismiss: 'onAnswerDismiss', loadchart: 'loadChart' };
    const emit = (n, d) => { const f = o[CB[n]]; f && f(d); container.dispatchEvent(new CustomEvent('dashboard:' + n, { detail: d })) };

    let deafened = false;
    let env = ENVIRONMENTS[o.environment] ? o.environment : 'spacecraft';
    let cat = C.cats[o.category] ? o.category : 'prevention', data = {}, ans = null, texts = {}, charts = new Map(), vals = {}, loading = false, error = null, vState = 'idle', amp = 0, ampS = 0, muted = false, accentOv = null;
    const D = () => data[env + ':' + cat];
    const A = () => (ans && ans.cat === cat ? ans : null);   // the answer on screen, if it belongs to this category
    const inVals = {}, viewsBy = {}, viewOf = {};   // values set by the agent / views per category / active view per category
    let sort = { k: null, d: 1 }, valT = 0, swapT = 0, rafId = 0, disposed = false;
    const cfg = () => C.cats[cat];
    const root = document.createElement('div'); root.className = 'fd pwr'; container.appendChild(root);

    const fns = new Map(), RO = new ResizeObserver(es => es.forEach(e => { const f = fns.get(e.target); f && f() }));
    const watch = (el, fn, again) => { if (again) { const f = fns.get(el); f && f(); return } fns.set(el, fn); RO.observe(el); fn() };

    function decode(el) {
        if (RM) return;
        el.querySelectorAll('.dc').forEach(n => {
            const full = n.textContent, t0 = performance.now(), ch = 'ABCDEF0123456789#%&*<>';
            const id = every(() => { const k = (performance.now() - t0) / C.timing.decodeMs; if (k >= 1 || disposed) { n.textContent = full; clr(id); return } n.textContent = [...full].map((c, i) => c === ' ' || i < k * full.length ? c : ch[(i * 7 + Math.floor(k * 40)) % ch.length]).join('') }, 40)
        });
    }
    function mkPanel(tag, v, title, cls, inner, delay) {
        const p = document.createElement(tag); p.className = 'pn ' + cls; p.style.setProperty('--d', delay + 's');
        p.innerHTML = `<div class="in">${inner}</div>`; buildHudFrame(p, v, title, watch); later(() => decode(p), (delay + .45) * 1000); return p;
    }

    /* ---- top bar ---- */
    let tabs, envsEl, atmEl, suitBtn, habBtn, issBtn;
    function buildTopbar() {
        const p = mkPanel('header', 'C', '', '', `<button class="home" aria-label="Back to cabin" title="Home">${ic('home')}</button>
 <div class="envb" role="group" aria-label="Environment">
   <button class="eb iss" aria-label="Spacecraft" title="Spacecraft" aria-pressed="false">${ic('iss')}<span>Craft</span></button>
   <button class="eb habitat" aria-label="Moon base" title="Moon base" aria-pressed="false">${ic('hab')}<span>Base</span></button>
   <button class="eb suit" aria-label="Space suit" title="Space suit" aria-pressed="false">${ic('suit')}<span>Suit</span></button>
 </div>
 <div class="tabs" role="tablist" aria-label="Category">${C.order.map(id => `<button class="tab" role="tab" data-id="${id}" style="--ta:${C.cats[id].accent}" aria-selected="false" tabindex="-1">${ic(C.cats[id].icon)}<span class="dc">${C.cats[id].short}</span></button>`).join('')}</div>
<button class="hu-btn ab" type="button" aria-label="About" title="About the team and the solution"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9.5"/><path d="M12 11v5.5"/><path d="M12 7.6h.01"/></svg><span>About</span></button>
<div class="hu"></div>`, 0);
        p.classList.add('top');
        tabs = p.querySelector('.tabs');
        suitBtn = p.querySelector('.suit');
        habBtn = p.querySelector('.habitat');
        issBtn = p.querySelector('.iss');
        on(issBtn, 'click', () => emit('iss'));
        on(p.querySelector('.ab'), 'click', () => emit('about'));
        on(suitBtn, 'click', () => emit('suit'));
        on(habBtn, 'click', () => emit('habitat'));
        envsEl = p.querySelector('.envs'); atmEl = p.querySelector('.atm');
        if (envsEl) {   // the environment tabs are optional (not in the current top bar template)
            on(envsEl, 'click', e => { const b = e.target.closest('.etab'); if (b) pickEnv(b.dataset.e) });
            on(envsEl, 'keydown', e => {
                const i = ENV_ORDER.indexOf(env), d = { ArrowRight: 1, ArrowLeft: -1 }[e.key]; if (d == null) return;
                e.preventDefault(); const j = (i + d + ENV_ORDER.length) % ENV_ORDER.length; pickEnv(ENV_ORDER[j]); envsEl.children[j].focus();
            });
        }
        on(p.querySelector('.home'), 'click', () => emit('home'));   // first .home = the home button
        on(tabs, 'click', e => { const b = e.target.closest('.tab'); if (b) pick(b.dataset.id) });
        on(tabs, 'pointerdown', e => { const b = e.target.closest('.tab'); if (b) { b.classList.add('gl'); later(() => b.classList.remove('gl'), C.timing.glitchMs) } });
        on(tabs, 'keydown', e => {
            const i = C.order.indexOf(cat), d = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
            const n = C.order.length;
            const j = d != null ? (i + d + n) % n : e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : -1; if (j < 0) return;
            e.preventDefault(); pick(C.order[j]); tabs.children[j].focus();
        });
        return p;
    }
    const pick = id => { if (id !== cat) { ans = null; emit('categorychange', id) } setCategory(id) };
    function markTabs() { [...tabs.children].forEach(b => { const a = b.dataset.id === cat; b.setAttribute('aria-selected', a); b.tabIndex = a ? 0 : -1 }) }
    const pickEnv = id => { if (id !== env) emit('environmentchange', id); setEnvironment(id) };
    function markEnvs() {
        if (!envsEl) return;
        [...envsEl.children].forEach(b => { const a = b.dataset.e === env; b.setAttribute('aria-selected', a); b.tabIndex = a ? 0 : -1 });
        if (atmEl) { const E = ENVIRONMENTS[env]; atmEl.textContent = `${E.o2}% O₂ · ${E.psi} psi`; }
    }

    /* ---- voice ---- */
    let bars, stEl, trn, micBtn, deafBtn, msgsEl, chatIn, lensEl, headEl;
    function paintMic() {
        micBtn.setAttribute('aria-pressed', muted);
        const t = muted ? 'Unmute microphone' : 'Mute microphone';
        micBtn.setAttribute('aria-label', t); micBtn.title = t;
    }
    function paintDeaf() {
        deafBtn.setAttribute('aria-pressed', deafened);
        const t = deafened ? 'Hear Flamo again' : 'Silence Flamo';
        deafBtn.setAttribute('aria-label', t); deafBtn.title = t;
    }
    function buildVoicePanel() {
        const p = mkPanel('section', 'A', 'Voice', '', `<div class="vbox"><div class="eh"></div><canvas class="lv"></canvas><div class="lcw cabin-host"><div class="cs"><div class="lc"></div></div></div><span class="ll"></span></div><div class="vs"><span class="led"></span><span class="st dc">IDLE</span><button class="mic" aria-pressed="false" aria-label="Mute microphone" title="Mute microphone"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM6 11a6 6 0 0 0 12 0M12 17v4"/><path class="slash" d="M4 4L20 20"/></svg></button><button class="mic df" aria-pressed="false" aria-label="Silence Flamo" title="Silence Flamo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 14v-2a9 9 0 0 1 18 0v2M3 14h3v6H4a1 1 0 0 1-1-1v-5zM21 14h-3v6h2a1 1 0 0 0 1-1v-5z"/><path class="slash" d="M4 4L20 20"/></svg></button></div><div class="trn" aria-live="polite"><span></span></div><div class="chat"><div class="msgs" role="log" aria-live="polite" aria-label="Chat"></div><form class="cf"><textarea class="ci" rows="1" maxlength="500" placeholder="Message Flamo…" aria-label="Chat message" autocomplete="off"></textarea><button class="btn" type="submit">SEND</button></form></div>`, .12);
        bars = [...p.querySelectorAll('.vb')]; stEl = p.querySelector('.st'); trn = p.querySelector('.trn span');
        micBtn = p.querySelector('.mic:not(.ab):not(.df)');
        deafBtn = p.querySelector('.mic.df');
        const paintMic = () => {
            micBtn.setAttribute('aria-pressed', muted);
            const t = muted ? 'Unmute microphone' : 'Mute microphone';
            micBtn.setAttribute('aria-label', t); micBtn.title = t;
        };
        const paintDeaf = () => {
            deafBtn.setAttribute('aria-pressed', deafened);
            const t = deafened ? 'Hear Flamo again' : 'Silence Flamo';
            deafBtn.setAttribute('aria-label', t); deafBtn.title = t;
        };
        // paintMic = paintMic; // (keep both reachable from the public API below)
        on(micBtn, 'click', () => { muted = !muted; paintMic(); emit('mictoggle', muted) });
        on(deafBtn, 'click', () => { deafened = !deafened; paintDeaf(); emit('deafentoggle', deafened) });
        lensEl = { canvas: p.querySelector('.lv'), host: p.querySelector('.lcw .lc'), label: p.querySelector('.ll') };
        headEl = p.querySelector('.eh');
        msgsEl = p.querySelector('.msgs'); chatIn = p.querySelector('.ci');
        const fit = () => { chatIn.style.height = 'auto'; chatIn.style.height = Math.min(chatIn.scrollHeight, 150) + 'px'; chatIn.style.overflowY = chatIn.scrollHeight > 150 ? 'auto' : 'hidden' };
        const sendChat = () => { const t = chatIn.value.trim(); if (!t) return; chatIn.value = ''; fit(); addMessage('me', t); emit('chatsend', { text: t }) };
        on(p.querySelector('.cf'), 'submit', e => { e.preventDefault(); sendChat() });
        on(chatIn, 'input', fit);
        on(chatIn, 'keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendChat() } });
        return p;
    }
    // One DOM bubble per chat-log key (chatLog.js decides: create, update or ignore). Earlier bubbles never move or clear.
    const chat = createChatLog({ debug: typeof localStorage !== 'undefined' && (() => { try { return localStorage.getItem('flame.debugChat') === '1' } catch { return false } })() });
    const bubbleEls = new Map();
    function pushBubble(role, text) {
        const near = nearBottom(msgsEl);
        const m = document.createElement('div');
        m.className = 'msg ' + (role === 'me' ? 'me' : 'ai'); m.textContent = text;
        msgsEl.appendChild(m);
        while (msgsEl.children.length > 100) msgsEl.firstChild.remove();
        if (near || role === 'me') msgsEl.scrollTop = msgsEl.scrollHeight;   // my own message always shows; speech follows only if the reader is at the bottom
        return m;
    }
    function addMessage(role, text) { pushBubble(role, text); }
    function upsertMessage(id, role, text, final = false) {
        const r = chat.upsert(role, id, text, final);
        if (r.action === 'create') bubbleEls.set(r.key, pushBubble(role, text));
        else if (r.action === 'update') {
            const m = bubbleEls.get(r.key);
            if (m && m.isConnected) { const near = nearBottom(msgsEl); m.textContent = text; if (near) msgsEl.scrollTop = msgsEl.scrollHeight }
            else bubbleEls.set(r.key, pushBubble(role, text));
        }
    }
    function voiceStep(dt, T) {
        ampS += (amp - ampS) * Math.min(1, dt * 10);
        bars.forEach((b, i) => {
            const idle = (vState === 'listening' ? .16 : .07) + .05 * Math.sin(T * 2.2 + i * .7);
            const live = ampS * (.55 + .45 * Math.abs(Math.sin(T * 8 + i * .8)));
            b.style.height = (10 + Math.min(1, Math.max(idle, live)) * 90) + '%';
        });
    }

    /* ---- parameters: the two conditions inputs, the coverage badges and the fixed gravity text ---- */
    let par, covEl, cov2El, slsEl, grEl, fxPar;
    let covState = { badges: [], custom: false };
    function buildParamsPanel() {
        const p = mkPanel('section', 'B', 'Your conditions', 'pbk', `<div class="fxw fx"><span class="bd cov" hidden></span><span class="bd cov cov2" hidden></span><div class="rl">YOUR CONDITIONS</div><p class="ycsrc nt"></p><div class="sls"></div><div class="ycpo"></div><div class="ycn"></div><div class="ycl" hidden></div><ol class="yck" hidden></ol><div class="ycc"></div><div class="ycb"><button type="button" class="chip" data-cmp>Compare with ISS / Moon base / suit</button><button type="button" class="chip" data-askc>Ask Flamo about these conditions</button></div><p class="grv"></p></div>`, .45);
        par = p; covEl = p.querySelector('.cov'); cov2El = p.querySelector('.cov2'); slsEl = p.querySelector('.sls'); grEl = p.querySelector('.grv');
        on(p, 'click', e => {
            const t = e.target;
            if (t.closest('[data-cmp]')) compareScenarios();
            else if (t.closest('[data-askc]')) emit('ask', { text: `What does the data say at ${vals.oxygen} percent oxygen and ${vals.pressure} psi?` });
            else { const g = t.closest('.lm'); if (g && cond) { const mk = ladderModel(cond, vals.oxygen).markers.find(k => String(k.n) === g.dataset.n); if (mk && mk.kind === 'evidence') emit('ask', { text: `What does ${mk.source || 'the source'}, page ${mk.page}, say about oxygen?` }) } }
        });
        on(slsEl, 'pointerdown', e => { const t = e.target.closest('.trk'); if (!t || loading) return; drag = t; t.setPointerCapture(e.pointerId); t.focus(); move(e) });
        on(slsEl, 'pointermove', e => { if (drag) move(e) });
        on(slsEl, 'pointerup', () => { drag = null }); on(slsEl, 'pointercancel', () => { drag = null });
        on(slsEl, 'keydown', e => {
            const t = e.target.closest('.trk'); if (!t || loading) return; const s = slider(t.parentNode.dataset.k), v = vals[s.key];
            const d = { ArrowRight: s.step, ArrowUp: s.step, ArrowLeft: -s.step, ArrowDown: -s.step, PageUp: s.step * 10, PageDown: -s.step * 10 }[e.key];
            if (d != null) setVal(s.key, v + d, 1); else if (e.key === 'Home') setVal(s.key, s.min, 1); else if (e.key === 'End') setVal(s.key, s.max, 1); else return; e.preventDefault();
        });
        return p;
    }
    /* ---- Round 11: the conditions panel and the evidence sections. Data = GET /api/nearest (flameo nearest_tests), refreshed 0.5 s after a slider stops: no model call ---- */
    let cond = null, condSource = '', condT = 0, cmp = null, invFilter = null, lsel = null, lastMap = null;
    const activeScen = () => (cond && (cond.scenarios || []).find(sc => Math.abs(sc.o2_pct - vals.oxygen) < .01 && Math.abs(sc.p_psi - vals.pressure) < .01)) || null;
    const setInv = code => { invFilter = code || null; MAP_UI.inv = invFilter; refresh(['cmap']); queueNearest() };
    const NEAR_MS = o.nearestDebounceMs ?? 500;
    function loadNear(o2, psi, source, inv) {
        const url = `${o.apiUrl || ''}/api/nearest?o2=${encodeURIComponent(o2)}&p=${encodeURIComponent(Math.max(psi, .1))}${inv ? '&investigation=' + encodeURIComponent(inv) : ''}`;
        return (o.fetchNearest ? o.fetchNearest(o2, psi) : fetch(url).then(r => r.ok ? r.json() : null)).catch(() => null);
    }
    let nearSeq = 0;   // an older, slower /api/nearest answer never replaces a newer one
    function queueNearest() { clr(condT); condT = later(async () => { const seq = ++nearSeq, r = await loadNear(vals.oxygen, vals.pressure, undefined, invFilter); if (r && !disposed && seq === nearSeq) { const first = !cond; cond = r; paintConditions(); if (first && !A()) renderDash(); else refresh(['cmap', 'cspread', 'cnear', 'chart']) } }, NEAR_MS) }
    async function compareScenarios() {
        if (!cond) return;
        const rs = await Promise.all((cond.scenarios || []).filter(s => ['iss', 'moon_base', 'spacesuit'].includes(s.id)).map(async s => ({ s, r: await loadNear(s.o2_pct, s.p_psi) })));
        cmp = rs.filter(x => x.r); paintConditions();
    }
    function paintConditions() {
        if (!par) return;
        par.querySelector('.ycsrc').textContent = condSource || '';
        const po = par.querySelector('.ycpo'), n = par.querySelector('.ycn'), l = par.querySelector('.ycl'), k = par.querySelector('.yck'), c = par.querySelector('.ycc');
        if (!cond) { po.innerHTML = n.innerHTML = l.innerHTML = k.innerHTML = c.innerHTML = ''; return }
        po.innerHTML = cond.po2 ? `<span class="nt">oxygen partial pressure</span> <b>${esc(cond.po2.value_psi)} psi</b> <small class="nt">${tx(cond.po2.formula)}</small>` : '';
        n.innerHTML = nearCount(cond);
        l.innerHTML = ''; k.innerHTML = '';                        // the ladder lives next to the map (Round 12 item 3)
        c.innerHTML = cmp ? `<ul class="cmp">${cmp.map(x => `<li><b>${tx(x.s.label)}</b> ${esc(x.s.o2_pct)} % at ${esc(x.s.p_psi)} psi: ${x.r.n_near > 0 ? `${esc(x.r.n_near)} tests in ${esc(x.r.n_psis)} ${x.r.n_psis === 1 ? 'investigation' : 'investigations'}` : 'no test near'}</li>`).join('')}</ul>` : '';
        paintTicks();
    }
    const nearCount = d => d.n_near > 0 ? `<b>${esc(d.n_near)}</b> tests near your point in <b>${esc(d.n_psis)}</b> ${d.n_psis === 1 ? 'investigation' : 'investigations'}` : `No PSI test at these conditions`;
    function paintTicks() {                                      // the scenario pressures (the challenge's own psi numbers, from flameo) on the pressure slider
        const el = slsEl && slsEl.querySelector('.sl[data-k="pressure"] .trk'); if (!el || !cond) return;
        el.querySelectorAll('u').forEach(u => u.remove());
        const s = slider('pressure'), seen = new Set();
        (cond.scenarios || []).forEach(sc => { if (seen.has(sc.p_psi)) return; seen.add(sc.p_psi); const u = document.createElement('u'); u.className = 'tkm'; u.style.left = (sc.p_psi - s.min) / (s.max - s.min) * 100 + '%'; u.title = `${sc.label}: ${sc.p_psi} psi`; u.dataset.v = sc.p_psi; el.appendChild(u) });
    }
    function condSections(k, d) {
        if (!cond) return '';
        if (k === 'cmap') {
            const sc = activeScen(), qs = [invFilter && 'investigation=' + encodeURIComponent(invFilter), sc && 'scenario=' + encodeURIComponent(sc.id)].filter(Boolean).join('&');
            const mapC = { id: 'o2_vs_pressure', ref: '/api/charts/o2_vs_pressure' + (qs ? '?' + qs : ''), type: 'scatter', title: 'Where your conditions sit among the tests', xLabel: 'pressure (psi)', yLabel: 'oxygen (%)' };
            MAP_UI.tol = cond.tolerance || null; MAP_UI.nearest = cond.n_near === 0 ? (cond.nearest_points || []).filter(q => q.p_kpa != null).map(q => ({ x: q.p_kpa / 6.894757, y: q.o2_pct })) : [];
            const lm = ladderModel(cond, vals.oxygen, CHART_W);
            return `<h3 class="sh">Where you are</h3><p class="nt">Click the map to place your point (white). ${cond.tolerance ? `A test counts as near when it is inside the dashed box: within ${esc(cond.tolerance.o2_pts)} oxygen points and ${esc(cond.tolerance.p_rel * 100)} percent of your pressure; those tests are ringed.` : 'The ringed tests are the ones near your point.'}${cond.n_near === 0 ? ' None is inside the box: the dashed gold rings mark the nearest tested points.' : ''} Select an investigation in the list to show only its tests. No zone is marked safe or dangerous.</p>${invFilter ? `<p class="flt">Showing only <b>${esc(invFilter === 'other' ? 'other PSIs' : invFilter === 'burner' ? 'the burner stream' : invFilter)}</b> <button type="button" class="chip" data-clearinv>Show all investigations</button></p>` : ''}<div class="wym">${chartBody(mapC, d)}</div><h4 class="sh ls">Oxygen ladder${sc ? ` <small class="nt">on ${tx(sc.label)}</small>` : ''}</h4><div class="lad">${ladderSvg(lm, { sel: lsel, scenario: sc && sc.id })}</div><div class="ldbox" aria-live="polite">${ladderDetail(lm, lsel)}</div>`;
        }
        if (k === 'cspread') { const m = spreadModel(cond, vals.oxygen); return `<h3 class="sh">Spread rate at your oxygen</h3>${m ? spreadSvg(m) : ''}${m && !m.inside ? `<p class="nt">${(cond.gaps || []).filter(g => g.startsWith('No spread-rate')).map(tx).join(' ')}</p>` : ''}` }
        if (k === 'cnear') return `<h3 class="sh">What happened in the nearest tests</h3>${nearHtml(cond)}`;
        return '';
    }

    let drag = null;
    const slider = k => cfg().sliders.find(s => s.key === k);
    function move(e) { const r = drag.getBoundingClientRect(), s = slider(drag.parentNode.dataset.k); setVal(s.key, s.min + clamp((e.clientX - r.left) / r.width) * (s.max - s.min), 1) }
    function setVal(k, v, user) {
        const s = slider(k); v = +clamp(Math.round(v / s.step) * s.step, s.min, s.max).toFixed(3); if (vals[k] === v) return;
        vals[k] = v; paintSlider(s); if (user) { queueValues(k); queueNearest(); refresh(['chart']) }
    }
    function queueValues(k) {
        clr(valT);
        valT = later(() => emit('valueschange', { environment: env, category: cat, values: { ...vals }, changedKey: k }), o.valuesDebounceMs)
    }
    function paintSlider(s) {
        const el = slsEl.querySelector(`.sl[data-k="${s.key}"]`); if (!el) return;
        const n = clamp((vals[s.key] - s.min) / (s.max - s.min)), t = el.querySelector('.trk'), txt = fmt(vals[s.key]) + (s.unit ? ' ' + s.unit : '');
        [...t.querySelectorAll('i')].forEach((i, x) => i.classList.toggle('f', x < Math.round(n * 24)));
        t.querySelector('.hd').style.left = n * 100 + '%'; el.querySelector('.vl').innerHTML = `<b>${esc(fmt(vals[s.key]))}</b>${s.unit ? '<small>' + esc(s.unit) + '</small>' : ''}`;
        t.setAttribute('aria-valuenow', vals[s.key]); t.setAttribute('aria-valuetext', txt);
    }
    function defaults() {
        const v = {}; cfg().sliders.forEach(s => { v[s.key] = +(Math.round((s.min + (s.max - s.min) * .5) / s.step) * s.step).toFixed(3) });
        const E = ENVIRONMENTS[env];
        v.oxygen = clamp(E.o2, SL.oxygen[0], SL.oxygen[1]); v.pressure = clamp(E.psi, SL.pressure[0], SL.pressure[1]);
        cfg().sliders.forEach(s => { if (inVals[s.key] != null) v[s.key] = +clamp(Math.round(inVals[s.key] / s.step) * s.step, s.min, s.max).toFixed(3) });
        return v;
    }
    function renderParams() {
        const c = cfg();
        slsEl.innerHTML = c.sliders.map(s => `<div class="sl" data-k="${s.key}"><div class="h"><span>${s.label}</span><span class="vl"></span></div><div class="trk" role="slider" tabindex="0" aria-label="${s.label}" aria-valuemin="${s.min}" aria-valuemax="${s.max}">${'<i></i>'.repeat(24)}<div class="hd"></div></div></div>`).join('');
        c.sliders.forEach(paintSlider); slsEl.classList.toggle('dis', loading);
        grEl.textContent = texts.gravity || '';
    }
    function paintCoverage() {
        [[covEl, covState.badges[0]], [cov2El, covState.badges[1]]].forEach(([el, b]) => { if (!el) return; el.hidden = !b; if (b) { el.className = 'bd cov ' + (el === cov2El ? 'cov2 ' : '') + (b.cls || ''); el.textContent = b.text } });
    }

    /* ---- the document viewer: a side drawer with the NASA document (its local copy) at the cited page ---- */
    let viewer = null;
    function closeViewer() { if (viewer) { viewer.remove(); viewer = null } }
    function openViewer(id, page, title) {
        closeViewer();
        const v = document.createElement('aside');
        v.className = 'dv'; v.setAttribute('role', 'dialog'); v.setAttribute('aria-label', 'Document viewer');
        const src = `${o.apiUrl || ''}/api/docs/${encodeURIComponent(id)}#page=${encodeURIComponent(page || 1)}`;
        v.innerHTML = `<div class="dvh"><span class="dvt">${esc(title || 'Document')}, page ${esc(page || 1)}</span><button type="button" class="chip" data-dvclose aria-label="Close the viewer">Close</button></div><iframe class="dvf" title="Document" src="${esc(src)}"></iframe>`;
        on(v, 'click', e => { if (e.target.closest('[data-dvclose]')) closeViewer() });
        root.appendChild(v); viewer = v;
    }
    on(document, 'keydown', e => { if (e.key === 'Escape') closeViewer() });

    /* ---- dashboard ---- */
    let dash, dsc, rail;
    function buildDashboard() {
        const p = mkPanel('section', 'A', 'Dashboard', 'dsh', `<div class="rail fx"></div><div class="dsc fx"></div>`, .3);
        dash = p; rail = p.querySelector('.rail'); dsc = p.querySelector('.dsc'); { let lw = dsc.clientWidth, rt = 0; watch(dsc, () => { if (Math.abs(dsc.clientWidth - lw) < 30) return; lw = dsc.clientWidth; clearTimeout(rt); rt = setTimeout(() => { if (!disposed && cond) refresh(['cmap', 'cspread']); else if (!disposed) refresh(['chart']) }, 150) }) }
        on(p, 'click', e => {
            const t = e.target; let b;
            if ((b = t.closest('[data-sort]'))) { sort = sort.k === b.dataset.sort ? { k: b.dataset.sort, d: -sort.d } : { k: b.dataset.sort, d: 1 }; refresh(['table']) }
            else if ((b = t.closest('[data-doc]'))) openViewer(b.dataset.doc, b.dataset.page, b.dataset.t);
            else if (t.closest('[data-back]')) back();
            else if ((b = t.closest('[data-inv]'))) setInv(invFilter === b.dataset.inv ? null : b.dataset.inv);
            else if (t.closest('[data-clearinv]')) setInv(null);
            else if ((b = t.closest('[data-askm]'))) { const mk = cond && ladderModel(cond, vals.oxygen, CHART_W).markers.find(k => String(k.n) === b.dataset.askm); if (mk) emit('ask', { text: `What does ${mk.source || 'the source'}, page ${mk.page}, say about oxygen?` }) }
            else if ((b = t.closest('.lm'))) { lsel = lsel === +b.dataset.n ? null : +b.dataset.n; refresh(['cmap']) }
            else if ((b = t.closest('[data-ask]'))) emit('ask', { text: b.dataset.ask });
            else if (t.closest('.retry')) emit('retry');
            else if ((b = t.closest('[data-view]'))) { viewOf[cat] = b.dataset.view; paintViews(); emit('viewchange', b.dataset.view) }
            else if ((b = t.closest('.mk'))) { const s = dsc.querySelector(`[data-s="${b.dataset.s}"]`); s && s.scrollIntoView({ behavior: RM ? 'auto' : 'smooth', block: 'start' }) }
        });
        // click or drag on a graph sets the sliders: the map sets oxygen and pressure, the spread chart sets oxygen
        let gdrag = null, graf = 0;
        const gsvg = () => gdrag && dsc.querySelector(`[data-k="${gdrag.sec}"] svg[data-geo]`);   // the section is redrawn while you drag: always measure the current one
        // a plain click on a dot picks that exact test (or scenario cross): the sliders jump to its oxygen and pressure
        const snapTo = (geo, px, py) => {
            const fx = v => geo.log ? Math.log(v) : v, PX = x => geo.L + (fx(x) - geo.a0) / ((geo.a1 - geo.a0) || 1) * (geo.W - geo.L - geo.R), PY = y => geo.H - geo.B - (y - geo.y0) / ((geo.y1 - geo.y0) || 1) * (geo.H - geo.T - geo.B);
            let best = null, bd = 12;
            const test = (x, y) => { const d = Math.hypot(PX(x) - px, PY(y) - py); if (d < bd) { bd = d; best = { x, y } } };
            if (geo.k === 'map') (lastMap ? lastMap.series : []).forEach(sr => sr.points.forEach(q => test(q.x, q.y)));
            return best;
        };
        const fromGraph = (e, snap) => {
            const sv = gsvg(); if (!sv) return;
            const r = sv.getBoundingClientRect(), geo = JSON.parse(sv.dataset.geo), W = geo.W, px = (e.clientX - r.left) / r.width * W, py = (e.clientY - r.top) / r.height * geo.H;
            const t = clamp((px - geo.L) / (W - geo.L - geo.R)), a = geo.a0 + t * (geo.a1 - geo.a0), x = geo.log ? Math.exp(a) : a;
            if (geo.k === 'map') { const hit = snap && snapTo(geo, px, py), y = geo.y0 + clamp((geo.H - geo.B - py) / (geo.H - geo.T - geo.B)) * (geo.y1 - geo.y0); setVal('oxygen', hit ? hit.y : y, 1); setVal('pressure', hit ? hit.x : x, 1); queueValues('reset') }   // both values changed: tell the agent both, or it answers with the old oxygen and puts the slider back
            else { const pts = (cond && cond.spread_points) || [], hit = snap && pts.map(q => ({ q, d: Math.abs((geo.L + (q.x - geo.a0) / ((geo.a1 - geo.a0) || 1) * (geo.W - geo.L - geo.R)) - px) })).filter(o => o.d < 10).sort((a, b) => a.d - b.d)[0]; setVal('oxygen', hit ? hit.q.x : x, 1) }
            cancelAnimationFrame(graf); graf = requestAnimationFrame(() => { if (!disposed) refresh(['cmap', 'cspread']) });
        };
        // one click puts the point there (or on the dot you hit); the point does not follow the mouse afterwards
        on(p, 'pointerdown', e => {
            const sv = e.target.closest && e.target.closest('svg[data-geo]'); if (!sv || e.button > 0 || loading || e.target.closest('.lm')) return;
            e.preventDefault(); getSelection().removeAllRanges();
            gdrag = { sec: sv.closest('[data-k]').dataset.k }; fromGraph(e, true); gdrag = null;
            cancelAnimationFrame(graf); graf = requestAnimationFrame(() => { if (!disposed) refresh(['cmap', 'cspread']) });
        });
        on(p, 'keydown', e => { const g = (e.key === 'Enter' || e.key === ' ') && e.target.closest && e.target.closest('.lm'); if (g) { e.preventDefault(); lsel = lsel === +g.dataset.n ? null : +g.dataset.n; refresh(['cmap']) } });
        return p;
    }
    function renderRail(n = 6) { rail.innerHTML = `<svg viewBox="0 0 100 100" aria-hidden="true"><path d="${IC[cfg().icon]}"/></svg>` + Array.from({ length: n }, (_, i) => i).map(i => `<button type="button" class="mk" data-s="${i}" aria-label="Go to section ${i + 1}"></button>`).join('') }
    /* ---- sub-view switcher (Prevention: Materials / Ignition) ---- */
    function viewsHtml() {
        const l = viewsBy[cat] || [];
        return l.length > 1 ? `<div class="vsw" role="group" aria-label="View" style="display:flex;gap:8px;margin-bottom:10px">${l.map(v => `<button type="button" class="chip${v.id === viewOf[cat] ? ' on' : ''}" data-view="${esc(v.id)}" aria-pressed="${v.id === viewOf[cat]}">${esc(v.label)}</button>`).join('')}</div>` : '';
    }
    function paintViews() {
        if (!dsc) return;
        const h = viewsHtml(), e = dsc.querySelector('.vsw');
        if (e) { if (h) e.outerHTML = h; else e.remove() } else if (h) dsc.insertAdjacentHTML('afterbegin', h);
    }

    /* ---- answer state ---- */
    function back() { const id = ans && ans.requestId; ans = null; renderDash(); emit('answerdismiss', id) }
    function showAnswer(vm) {
        if (!vm) { if (ans) { ans = null; renderDash() } return }
        const to = vm.pillar && C.cats[vm.pillar] ? vm.pillar : cat;
        ans = { ...vm, cat: to };
        if (to !== cat) swap(env, to); else renderDash();
        requestAnimationFrame(() => { const t = dsc.querySelector('.ans, .dsc h2, .dsc'); t && t.scrollIntoView && t.scrollIntoView({ behavior: RM ? 'auto' : 'smooth', block: 'start' }) });   // the new answer is brought into view
    }
    // charts that carry a `ref` are fetched by the host (loadChart) and cached here
    const asked = new Set();
    function chartBody(c, v) {
        let series = c.series;
        if (c.ref) {
            const got = charts.get(c.ref), isMap = c.id === 'o2_vs_pressure';
            if (!got) {
                if (!asked.has(c.ref) && o.loadChart) { asked.add(c.ref); Promise.resolve(o.loadChart(c.ref)).then(r => { if (r && !disposed) { charts.set(c.ref, r); refresh(['chart', 'cmap']) } else asked.delete(c.ref) }) }
                if (!(isMap && lastMap)) return `<div class="lbl" role="status">LOADING CHART...</div>`;
                series = lastMap.series;                                   // keep drawing the previous map until the narrowed one arrives: no flash
            } else {
                series = got.series;
                if (isMap) { lastMap = got; if (!(got.filter && got.filter.investigation)) MAP_UI.legend = got.series.filter(x => x.marker !== 'cross').map(x => ({ name: x.name, marker: x.marker })) }
            }
        }
        if (c.type === 'bar') return barsHtml(series);
        const mine = c.id === 'o2_vs_pressure' && cond && vals.pressure != null ? { x: vals.pressure, y: vals.oxygen } : null, near = c.id === 'o2_vs_pressure' && cond ? (cond.map_points || []) : [];
        return scatterSvg(series, c.xLabel, c.yLabel, mine, near) || `<div class="lbl">NO POINTS</div>`;
    }
    function refresh(keys) { const v = view(); if (!v) return; if (keys.includes('chart') && cond) { ['cmap', 'cspread', 'cnear'].forEach(k => { if (!keys.includes(k)) keys = [...keys, k] }) } keys.forEach(k => { const e = dsc.querySelector(`[data-k="${k}"]`); if (e) e.innerHTML = secInner(k, v) }) }
    // what is rendered: the answer (with the category's ranking and chips kept) or the category overview
    function view() {
        const d = D(), a = A();
        if (!a) return d;
        return { ...a, suggestions: (d && d.suggestions) || [], ranking: a.ranking || null };        // an answer shows its own ranking only: the category's would be stale (Round 10 §10.7)
    }
    function secInner(k, d) {
        const c = cfg();
        CHART_W = Math.round((dsc && dsc.clientWidth || 640) - 96); SPREAD_W.v = CHART_W;
        if (k === 'sum') {
            const bd = (d.badges || []).map(b => `<span class="bd ${b.cls || ''}">${tx(b.text)}</span>`).join(' ');
            const m = summaryParts(d.summary), first = (d.kpis || [])[0];
            const repeats = first && kpiParts(first).value === m.value;          // the big number is not shown twice (Round 10 §10.4 item 1)
            return `<h2>${esc(c.name)}</h2><div class="bds">${bd}</div>${repeats ? '' : `<div class="big">${esc(m.value)}${m.unit ? ' <small>' + esc(m.unit) + '</small>' : ''}</div>`}<p>${esc(m.text)}</p>${m.note ? `<p class="nt">${esc(m.note)}</p>` : ''}`;
        }
        if (k === 'cmap' || k === 'cspread' || k === 'cnear') return condSections(k, d);
        if (k === 'back') return `<button type="button" class="chip" data-back>Back to ${esc(c.name)} overview</button>`;
        if (k === 'ans') return `<h3 class="sh">${tx(d.question)}</h3>${d.scenarioLabel ? `<p class="nt scn">Atmosphere: ${tx(d.scenarioLabel)}</p>` : ''}${(d.badges || []).map(b => `<span class="bd ${b.cls || ''}">${tx(b.text)}</span>`).join(' ')}${(d.speak || []).map((x, i) => { const rf = (d.speakRefs || [])[i] || []; return `<p class="sp">${tx(x)}${rf.length ? `<sup class="sr" title="source ${rf.join(', ')}">${rf.join(',')}</sup>` : ''}</p>` }).join('')}`;
        if (k === 'src') {
            const ICON = { 'Paper': 'srcPaper', 'NASA document': 'srcDoc', 'Finding': 'srcFind', 'Experiment table': 'srcTable', 'NASA Space Apps challenge text': 'srcChal' };
            const ORDER = Object.keys(ICON), groups = {};
            d.sources.forEach(x => { const g = ICON[x.label] ? x.label : (x.label || '').startsWith('Table') || (x.label || '').startsWith('Figure') ? 'Paper' : 'Paper'; (groups[g] = groups[g] || []).push(x) });
            const item = x => {
                const lk = x.link ? `<a class="chip ln" href="${esc(x.link)}" target="_blank" rel="noopener noreferrer">${x.link_kind === 'doi' ? 'DOI' : 'NASA PSI'}</a>` : '';
                const vw = x.viewable && x.doc_id ? `<button type="button" class="chip" data-doc="${esc(x.doc_id)}" data-page="${esc(x.page || 1)}" data-t="${esc(clean(x.title))}">View</button>` : '';
                return `<li><i class="sn">${esc(x.n)}</i><span class="st">${tx(x.title || x.label)}${x.page ? `, page ${esc(x.page)}` : ''}${x.evidence ? ` <small class="nt">${tx(x.evidence)}</small>` : ''}${x.quote ? `<small class="nt q">\u201C${tx(x.quote)}\u201D</small>` : ''}</span><span class="sa">${lk}${vw}</span></li>`;
            };
            const body = Object.keys(groups).sort((a, b) => Math.min(...groups[a].map(x => x.n)) - Math.min(...groups[b].map(x => x.n)) || ORDER.indexOf(a) - ORDER.indexOf(b)).map(g => `<div class="sg"><h4>${ic(ICON[g] || 'srcPaper')}${esc(g)}${groups[g].length > 1 ? ' (' + groups[g].length + ')' : ''}</h4><ol>${groups[g].map(item).join('')}</ol></div>`).join('');
            return `<h3 class="sh">Sources</h3>${body}`;
        }
        if (k === 'open') {
            const o = d.offer, chips = (o && o.chips || []).map(q => `<button type="button" class="chip" data-ask="${esc(q)}">${tx(q)}</button>`).join('');
            return `<h3 class="sh">Open question</h3><p class="oq">${tx((d.gaps && d.gaps[0]) || "That isn't covered in the PSI data or papers yet.")}</p>${o ? `<p class="nt">I can tell you about ${tx(o.category)} instead:</p><div class="asks">${chips}</div>` : ''}`;
        }
        if (k === 'empty') return `<p class="empty">${tx(d.empty)}</p>`;
        if (k === 'kpi') return `<div class="kps">${d.kpis.slice(0, 4).map(x => { const p = kpiParts(x); return `<div class="kp" title="${esc([p.basis, x.trust && 'trust: ' + x.trust].filter(Boolean).join(' · '))}"><span class="kl">${esc(p.label)}</span><div class="big">${esc(p.value)}${p.unit ? ' <small>' + esc(p.unit) + '</small>' : ''}${p.from ? ` <small class="nt kk">(${esc(p.from)})</small>` : ''}</div>${p.basis ? `<small class="nt kb">${esc(p.basis)}</small>` : ''}</div>` }).join('')}</div>`;
        if (k === 'chart') return d.charts.slice(0, 2).map(ch => `<h3 class="sh">${tx(ch.title)}</h3>${ch.shown ? `<p class="nt">showing ${tx(ch.shown)}</p>` : ''}${chartBody(ch, d)}`).join('');
        if (k === 'rank') {
            const r = d.ranking, rows = r.rows, top = Math.max(1, ...rows.filter(x => x.rank).map(x => +x.tests || 0));
            let dv = false;
            const body = rows.map(x => {
                const head = (!x.rank && !dv && r.divider) ? (dv = true, `<div class="lbl rkdv">${tx(r.divider)}</div>`) : '';
                const p = rankRowParts(x, top), who = `<span class="who">${p.ranked ? `<i class="rn">${esc(p.rank)}</i>` : ''}<span class="nm" title="${esc(p.name)}">${esc(p.name)}</span>${p.tier ? ` <small class="tier" title="${tx(r.tierLabel)}">${esc(p.tier)}</small>` : ''}</span>`;
                if (!p.ranked) return head + `<div class="rk nr">${who}<div class="val"><b class="vl">${esc(p.label)}</b></div></div>`;
                return head + `<div class="rk rr">${who}<div class="val"><div class="bt"><i style="width:${p.width}%"></i></div><b class="vl">${esc(p.label)}</b></div></div>`;
            }).join('');
            return `<h3 class="sh">${tx(texts.ranking_title || '')}</h3>${body}${r.footer ? `<p class="nt">${tx(r.footer)}</p>` : ''}<p class="nt">Tier: ${tx(r.tierLabel)}</p><p class="nt from">from: the registry and the experiment tables of ${rows.length} investigations</p>${r.note ? `<p class="nt">${tx(r.note)}</p>` : ''}`;
        }
        if (k === 'table') {
            const t = d.table, rows = t.rows.slice(); if (sort.k) rows.sort((a, b) => { const x = a[sort.k], y = b[sort.k]; return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))) * sort.d });
            return `<h3 class="sh">${tx(d.tableTitle || 'Data table')}</h3><div class="tw"><table role="grid" aria-label="Data"><thead><tr role="row">${t.columns.map(col => `<th role="columnheader" aria-sort="${sort.k === col.key ? (sort.d > 0 ? 'ascending' : 'descending') : 'none'}"><button type="button" data-sort="${esc(col.key)}">${tx(col.label)}${col.unit ? ' (' + esc(unitText(col.unit)) + ')' : ''}${sort.k === col.key ? (sort.d > 0 ? ' ▲' : ' ▼') : ''}</button></th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr role="row">${t.columns.map(col => `<td role="gridcell">${esc(cellText(r[col.key]))}${col.from && r[col.key + '__kpa'] != null ? ` <small class="nt kk">(${esc(r[col.key + '__kpa'])} ${esc(col.from)})</small>` : ''}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${t.footer ? `<p class="nt">${tx(t.footer)}</p>` : ''}`;
        }
        if (k === 'cards') return `<h3 class="sh">${tx(texts.cards_title || '')}</h3>` + d.cards.slice(0, 3).map(x => `<div class="card"><p>${tx(x.statement)}</p><small class="nt">${tx([x.wording, x.paper && (x.paper + (x.page ? ', page ' + x.page : ''))].filter(Boolean).join(' · '))}</small></div>`).join('');
        if (k === 'gaps') return `<h3 class="sh">${esc(texts.gaps_title || '')}</h3>` + d.gaps.slice(0, 3).map(g => `<p class="gp">${tx(g)}</p>`).join('') + (texts.gaps_footer ? `<p class="nt">${esc(texts.gaps_footer)}</p>` : '');
        if (k === 'ask') return `<h3 class="sh">${esc(texts.ask_title || '')}</h3><div class="asks">${d.suggestions.map(q => `<button type="button" class="chip" data-ask="${esc(q)}">${esc(q)}</button>`).join('')}</div>`;
        return '';
    }
    function renderDash() {
        const d = D(), v = view();
        if (loading) { dsc.innerHTML = viewsHtml() + `<div class="lbl" role="status">LOADING DATA...</div>` + [70, 150, 100, 160, 90].map(h => `<div class="sk" style="height:${h}px"></div>`).join(''); return }
        if (error) { dsc.innerHTML = `<div class="err" role="alert"><b>SYSTEM ERROR</b><span>${esc(error)}</span><button type="button" class="btn retry">RETRY</button></div>`; return }
        if (!v) { dsc.innerHTML = viewsHtml() + `<div class="lbl">NO DATA</div>`; return }
        const keys = (A() ? SECS_ANSWER : SECS_OVERVIEW).filter(k => secOn(k, v));
        // friendly empty state: an overview with no numbers, chart or table (e.g. no tests at the Moon base) points to the open questions
        if (!A() && !keys.some(k => k === 'kpi' || k === 'chart' || k === 'table')) { keys.splice(keys.indexOf('sum') + 1, 0, 'empty'); v.empty = `No tests for "${clean(v.summary?.text || 'this view')}" at these conditions yet${v.gaps?.length ? ': see the open questions below.' : '.'}` }
        // the answer is one card: the question as its title, then the numbers, chart and table, then the sources
        const inCard = k => A() && ['ans', 'open', 'kpi', 'chart', 'table', 'cards', 'gaps', 'src'].includes(k);
        const cardKeys = keys.filter(inCard);
        dsc.innerHTML = viewsHtml() + keys.map((k, i) => `<section class="sec${inCard(k) ? ' cd' + (k === cardKeys[0] ? ' cd1' : '') + (k === cardKeys[cardKeys.length - 1] ? ' cdn' : '') : ''}" data-s="${i}" data-k="${k}">${secInner(k, v)}</section>`).join('');
        renderRail(keys.length);
    }

    /* ---- category switching ---- */
    const fxEls = () => [...root.querySelectorAll('.fx')];
    function applyAccent() { root.style.setProperty('--accent', accentOv || cfg().accent) }
    function swap(nextEnv, nextCat) {
        if (disposed || (nextEnv === env && nextCat === cat)) return;
        env = nextEnv; cat = nextCat; markTabs(); markEnvs(); clr(swapT); fxEls().forEach(e => e.classList.add('out'));
        swapT = later(() => {
            sort = { k: null, d: 1 }; vals = defaults(); applyAccent(); renderRail(); renderParams(); renderDash(); paintCoverage();
            fxEls().forEach(e => e.classList.remove('out'));
        }, C.timing.out);
    }
    function setCategory(id) { if (C.cats[id]) swap(env, id) }
    function setEnvironment(id) { if (ENVIRONMENTS[id]) swap(id, cat) }

    /* ---- decoration: connectors, ticks, status text ---- */
    let deco, pnTop, pnVoice;
    function drawDeco() {
        if (root.clientWidth < 1000) { deco.innerHTML = ''; return }
        const O = root.getBoundingClientRect(), r = e => { const b = e.getBoundingClientRect(); return { l: b.left - O.left, t: b.top - O.top, r: b.right - O.left, b: b.bottom - O.top } };
        const T = r(pnTop), V = r(pnVoice), D = r(dash), P = r(par), W = O.width, H = O.height;
        const ln = (d, cx, cy) => `<path d="${d}"/><circle cx="${cx}" cy="${cy}" r="3.5"/>`, k = (x, y, sx, sy) => `<path d="M${x},${y + sy * 10}V${y}H${x + sx * 10}"/>`;
        deco.innerHTML = ln(`M${T.l},${T.b + 8}H${V.r - 40}`, V.r - 40, T.b + 8) + ln(`M${T.r},${T.b + 8}H${P.l + 40}`, P.l + 40, T.b + 8) + ln(`M${V.r - 60},${V.b + 8}H${V.l + 40}`, V.l + 40, V.b + 8) + ln(`M${V.r + 8},${V.b - 130}V${V.b - 50}`, V.r + 8, V.b - 50) + ln(`M${D.r + 8},${D.t + 40}V${D.t + 120}`, D.r + 8, D.t + 120) + k(6, 6, 1, 1) + k(W - 6, 6, -1, 1) + k(6, H - 6, 1, -1) + k(W - 6, H - 6, -1, -1);
    }

    /* ---- resizable borders ---- */
    const MIN = { w1: 240, w3: 240, mid: 420, vh: 420, fh: 200 }, S = {};
    const measure = k => k === 'w1' ? pnVoice.offsetWidth : k === 'w3' ? par.offsetWidth : pnVoice.offsetHeight;
    function limits(k, o) {
        const W = root.clientWidth - 64;
        const lim = {
            w1: [MIN.w1, W - MIN.mid - (o ?? S.w3 ?? par.offsetWidth)],
            w3: [MIN.w3, W - MIN.mid - (o ?? S.w1 ?? pnVoice.offsetWidth)],
            vh: [MIN.vh, pnVoice.parentNode.clientHeight - 16 - MIN.fh]
        }[k];
        return [lim[0], Math.max(lim[0], lim[1])];
    }
    function setSize(k, v) {
        const [lo, hi] = limits(k);
        S[k] = Math.round(clamp(v, lo, hi));
        root.style.setProperty('--' + k, S[k] + 'px'); drawDeco();
    }
    function resetSize(k) {
        delete S[k]; root.style.removeProperty('--' + k); drawDeco();
    }
    let anim = 0;
    const stopAnim = () => { cancelAnimationFrame(anim); anim = 0 };
    const put = (k, v) => { S[k] = Math.round(v); root.style.setProperty('--' + k, S[k] + 'px') };
    function glide(goal, done) {
        stopAnim();
        const ks = Object.keys(goal), from = {}; ks.forEach(k => from[k] = measure(k));
        if (RM) { ks.forEach(k => put(k, goal[k])); drawDeco(); done && done(); return }
        const t0 = performance.now(), D = 450;
        const step = now => {
            const p = Math.min(1, (now - t0) / D), e = 1 - Math.pow(1 - p, 3);
            ks.forEach(k => put(k, lerp(from[k], goal[k], e))); drawDeco();
            if (p < 1) anim = requestAnimationFrame(step); else { anim = 0; done && done() }
        };
        anim = requestAnimationFrame(step);
    }
    function toDefault(keys) {
        const goal = {};
        keys.forEach(k => goal[k] = k === 'vh' ? pnVoice.parentNode.clientHeight * .38 : (root.clientWidth - 32) * .2);
        glide(goal, () => keys.forEach(resetSize));
    }
    function setWidths(a, b) {
        S.w1 = Math.round(a); S.w3 = Math.round(b);
        root.style.setProperty('--w1', S.w1 + 'px'); root.style.setProperty('--w3', S.w3 + 'px'); drawDeco();
    }
    function widthPlan(el) {
        const W = root.clientWidth - 64, d1 = (root.clientWidth - 32) * .2, d3 = d1, m = MIN;
        if (el === 'L') { const mx = Math.max(m.w1, W - m.mid - m.w3); return { cur: pnVoice.offsetWidth, def: d1, max: mx, goal: { w1: mx, w3: m.w3 } } }
        if (el === 'P') { const mx = Math.max(m.w3, W - m.mid - m.w1); return { cur: par.offsetWidth, def: d3, max: mx, goal: { w1: m.w1, w3: mx } } }
        return { cur: dash.offsetWidth, def: W - d1 - d3, max: W - m.w1 - m.w3, goal: { w1: m.w1, w3: m.w3 } };
    }
    function defaultPx(k) {
        const raw = k === 'vh' ? pnVoice.parentNode.clientHeight * .38 : (root.clientWidth - 32) * .2;
        const [lo, hi] = limits(k);
        return clamp(raw, lo, hi);
    }
    const rawDef = k => k === 'vh' ? pnVoice.parentNode.clientHeight * .38 : (root.clientWidth - 32) * .2;
    function addGrips(p, specs) {
        specs.forEach(([s, k, sg, gr]) => {
            const hz = s === 't' || s === 'b', g = document.createElement('button');
            g.type = 'button'; g.className = 'rz ' + s; g.setAttribute('role', 'separator');
            g.setAttribute('aria-orientation', hz ? 'horizontal' : 'vertical');
            g.setAttribute('aria-label', 'Resize ' + (hz ? 'height' : 'width'));
            p.appendChild(g);
            let st = null;
            on(g, 'pointerdown', e => { if (root.clientWidth < 1000) return; stopAnim(); e.preventDefault(); g.setPointerCapture(e.pointerId); st = { x: e.clientX, y: e.clientY, v: measure(k) }; root.classList.add('rs') });
            on(g, 'pointermove', e => { if (st) setSize(k, st.v + sg * (hz ? e.clientY - st.y : e.clientX - st.x)) });
            const end = () => { st = null; root.classList.remove('rs') };
            on(g, 'pointerup', end); on(g, 'pointercancel', end);
            on(g, 'keydown', e => {
                const d = (hz ? { ArrowDown: 20, ArrowUp: -20 } : { ArrowRight: 20, ArrowLeft: -20 })[e.key];
                if (d == null) return; e.preventDefault(); stopAnim(); setSize(k, measure(k) + sg * d);
            });
        });
    }
    on(window, 'resize', () => { if (root.clientWidth >= 1000) Object.keys(S).forEach(k => setSize(k, S[k])) });

    /* ---- assemble ---- */
    pnTop = buildTopbar(); const col = document.createElement('div'); col.className = 'col';
    pnVoice = buildVoicePanel(); col.append(pnVoice);
    buildDashboard(); buildParamsPanel();
    addGrips(pnVoice, [['r', 'w1', 1, 'L']]);
    addGrips(dash, [['l', 'w1', 1, 'D'], ['r', 'w3', -1, 'D']]);
    addGrips(par, [['l', 'w3', -1, 'P']]);
    root.append(pnTop, col, dash, par);
    deco = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); deco.setAttribute('class', 'deco'); root.appendChild(deco);
    [['LNK 0x2F · FLAME IN FREEFALL', 'top:2px;left:16px'], ['SYS 04 · TELEMETRY', 'bottom:2px;left:50%;transform:translateX(-50%)']].forEach(([t, s]) => { const d = document.createElement('div'); d.className = 'stx'; d.style.cssText = s; d.textContent = t; root.appendChild(d) });
    watch(root, drawDeco);
    applyAccent(); markTabs(); markEnvs(); renderRail(); vals = defaults(); renderParams(); renderDash();
    later(() => root.classList.remove('pwr'), 2500);

    /* ---- loop (voice + fire), paused when hidden ---- */
    let last = performance.now(), T = 0;
    function loop(now) { rafId = requestAnimationFrame(loop); const dt = Math.min((now - last) / 1000, .05); last = now; T += dt; voiceStep(dt, T); }
    const start = () => { if (!rafId && !document.hidden && !disposed) { last = performance.now(); rafId = requestAnimationFrame(loop) } };
    on(document, 'visibilitychange', () => { if (document.hidden) { cancelAnimationFrame(rafId); rafId = 0 } else start() });
    on(window, 'resize', drawDeco);
    start();

    /* ---- public API ---- */
    return {
        setCategory,
        addMessage,
        upsertMessage,
        clearChat() { msgsEl.innerHTML = '' },
        // a new overview from the agent replaces any answer shown in that category
        setData(envId, id, d) { data[envId + ':' + id] = d; if (ans && ans.cat === id) ans = null; if (envId === env && id === cat) { loading = false; error = null; renderDash(); renderParams() } },
        setTexts(t) { texts = t || {}; renderParams(); renderDash() },
        setEnvironment,
        setMuted(b) { muted = !!b; if (micBtn) paintMic(); },
        setDeafened(b) { deafened = !!b; if (deafBtn) paintDeaf(); },
        setSuitActive(b) { suitBtn.classList.toggle('on', !!b); suitBtn.setAttribute('aria-pressed', !!b); },
        setHabitatActive(b) { habBtn.classList.toggle('on', !!b); habBtn.setAttribute('aria-pressed', !!b); },
        setIssActive(b) { issBtn.classList.toggle('on', !!b); issBtn.setAttribute('aria-pressed', !!b); },
        setLoading(b) { loading = !!b; if (b) error = null; renderDash(); renderParams() },
        setError(m) { error = m || null; if (m) loading = false; renderDash(); renderParams() },
        setVoiceState(s) { vState = s; root.classList.toggle('sp', s === 'speaking'); stEl.textContent = s.toUpperCase() },
        setVoiceAmplitude(a) { amp = clamp(+a || 0) },
        setTranscript(t) { trn.style.opacity = 0; later(() => { trn.textContent = t || ''; trn.style.opacity = 1 }, RM ? 0 : 200) },
        setAccent(c) { accentOv = c || null; applyAccent() },
        getLens() { return lensEl; },
        showAnswer,
        // badges = [{ text, cls }] (the second one is the spacesuit's oxygen-rich-flames note); custom = custom conditions
        setCoverage(c) { covState = { badges: (c && c.badges) || [], custom: !!(c && c.custom) }; paintCoverage(); refresh(['chart']) },
        // slider values coming FROM the agent. Never emits valueschange, so there is no echo loop.
        setValues(v) {
            if (!v) return;
            Object.assign(inVals, v);
            cfg().sliders.forEach(s => { if (v[s.key] != null) { vals[s.key] = +clamp(Math.round(v[s.key] / s.step) * s.step, s.min, s.max).toFixed(3); paintSlider(s) } });
            refresh(['chart']); queueNearest();
        },
        setConditionSource(t) { condSource = t || ''; par && (par.querySelector('.ycsrc').textContent = condSource) },
        setViews(catId, list, active) {
            viewsBy[catId] = list || [];
            if (active) viewOf[catId] = active; else if (!viewOf[catId] && list && list[0]) viewOf[catId] = list[0].id;
            if (catId === cat) paintViews();
        },
        setView(id) {
            Object.keys(viewsBy).forEach(c => { if (viewsBy[c].some(v => v.id === id)) { viewOf[c] = id; if (c === cat) paintViews() } });
        },
        getHeadHost() { return headEl; },
        getHideHost() { return pnTop.querySelector('.hu'); },
        dispose() {
            disposed = true; stopAnim(); cancelAnimationFrame(rafId); rafId = 0;
            timers.forEach(t => { clearTimeout(t); clearInterval(t) }); timers.clear();
            offs.forEach(f => f()); offs.length = 0; RO.disconnect(); fns.clear(); container.innerHTML = '';
        }
    };
}

export { CONFIG, mountDashboard };

/* ============ React component ============ */
const FONT_ID = 'flame-dashboard-fonts';
const FONT_HREF =
    'https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Share+Tech+Mono&display=swap';

const FlameDashboard = forwardRef(function FlameDashboard(props, ref) {
    const {
        category = 'flame-spread',
        valuesDebounceMs = 600,
        data,
        loading = false,
        error = null,
        voiceState = 'idle',
        voiceAmplitude = 0,
        transcript,
        accent,
        className,
        style,
        onCategoryChange, onAsk, onValuesChange, loadChart, apiUrl,
        onRetry, onHome, onAbout, onSuit, onHabitat, onMicToggle, muted,
        deafened, onDeafenToggle, onChatSend,
        onViewChange, onAnswerDismiss,
        suit = false,
        habitat = false,
        emberAlert = false,
        iss = false,
        onIss
    } = props;

    const hostRef = useRef(null);
    const apiRef = useRef(null);

    // Always call the latest callbacks without remounting the dashboard.
    const cbRef = useRef({});
    cbRef.current = { onCategoryChange, onAsk, onValuesChange, loadChart, onRetry, onHome, onAbout, onMicToggle, onChatSend, onSuit, onHabitat, onViewChange, onAnswerDismiss, onIss, onDeafenToggle };

    // Keep the latest props available to the mount effect.
    const initRef = useRef({});
    initRef.current = { category, data, loading, error, voiceState, voiceAmplitude, transcript, accent, suit, habitat, iss, apiUrl };

    const [headHost, setHeadHost] = useState(null);
    const [vs, setVs] = useState(voiceState);
    const [amp, setAmp] = useState(voiceAmplitude);
    const [uiHidden, setUiHidden] = useState(false);
    const [hideHost, setHideHost] = useState(null);

    useImperativeHandle(ref, () => ({
        get api() { return apiRef.current; },
        setSuitActive: b => apiRef.current?.setSuitActive(b),
        setHabitatActive: b => apiRef.current?.setHabitatActive(b),
        setIssActive: b => apiRef.current?.setIssActive(b),
        setCategory: id => apiRef.current?.setCategory(id),
        setMuted: b => apiRef.current?.setMuted(b),
        setDeafened: b => apiRef.current?.setDeafened(b),
        addMessage: (role, text) => apiRef.current?.addMessage(role, text),
        upsertMessage: (id, role, text, final) => apiRef.current?.upsertMessage(id, role, text, final),
        clearChat: () => apiRef.current?.clearChat(),
        setData: (envId, id, d) => apiRef.current?.setData(envId, id, d),
        setLoading: b => apiRef.current?.setLoading(b),
        setError: m => apiRef.current?.setError(m),
        setVoiceState: s => { apiRef.current?.setVoiceState(s); setVs(s); },
        setVoiceAmplitude: a => { apiRef.current?.setVoiceAmplitude(a); setAmp(Math.min(1, Math.max(0, +a || 0))); },
        setTranscript: t => apiRef.current?.setTranscript(t),
        setAccent: c => apiRef.current?.setAccent(c),
        getLens: () => apiRef.current?.getLens(),
        showAnswer: a => apiRef.current?.showAnswer(a),
        setCoverage: c => apiRef.current?.setCoverage(c),
        setTexts: t => apiRef.current?.setTexts(t),
        setValues: v => apiRef.current?.setValues(v),
        setConditionSource: t => apiRef.current?.setConditionSource(t),
        setViews: (c, l, a) => apiRef.current?.setViews(c, l, a),
        setView: id => apiRef.current?.setView(id),
    }), []);

    // Mount once (and clean up on unmount / StrictMode double-invoke).
    useEffect(() => {
        if (!document.getElementById(FONT_ID)) {
            const l = document.createElement('link');
            l.id = FONT_ID; l.rel = 'stylesheet'; l.href = FONT_HREF;
            document.head.appendChild(l);
        }
        const init = initRef.current;
        const call = name => d => cbRef.current[name]?.(d);
        const app = mountDashboard(hostRef.current, {
            category: init.category,
            valuesDebounceMs,
            onCategoryChange: call('onCategoryChange'),
            onAsk: call('onAsk'),
            loadChart: ref => cbRef.current.loadChart?.(ref),
            apiUrl: init.apiUrl,
            onValuesChange: call('onValuesChange'),
            onRetry: call('onRetry'),
            onHome: call('onHome'),
            onAbout: call('onAbout'),
            onSuit: call('onSuit'),
            onHabitat: call('onHabitat'),
            onIss: call('onIss'),
            onMicToggle: call('onMicToggle'),
            onDeafenToggle: call('onDeafenToggle'),
            onChatSend: call('onChatSend'),
            onViewChange: call('onViewChange'),
            onAnswerDismiss: call('onAnswerDismiss'),
        });
        apiRef.current = app;
        setHeadHost(app.getHeadHost());
        setHideHost(app.getHideHost());

        if (init.data) Object.entries(init.data).forEach(([e, cats]) => Object.entries(cats || {}).forEach(([id, d]) => d && app.setData(e, id, d)));
        if (init.loading) app.setLoading(true);
        if (init.error) app.setError(init.error);
        app.setVoiceState(init.voiceState);
        app.setVoiceAmplitude(init.voiceAmplitude);
        app.setSuitActive(init.suit);
        app.setHabitatActive(init.habitat);
        app.setIssActive(init.iss);
        if (init.transcript != null) app.setTranscript(init.transcript);
        if (init.accent) app.setAccent(init.accent);

        return () => {
            setHeadHost(null);
            setHideHost(null);
            app.dispose();
            apiRef.current = null;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [valuesDebounceMs]);

    // Sync props → dashboard.
    useEffect(() => { apiRef.current?.setSuitActive(suit); }, [suit]);
    useEffect(() => { apiRef.current?.setHabitatActive(habitat); }, [habitat]);
    useEffect(() => { apiRef.current?.setIssActive(iss); }, [iss]);
    useEffect(() => { apiRef.current?.setCategory(category); }, [category]);
    useEffect(() => { if (muted !== undefined) apiRef.current?.setMuted(muted); }, [muted]);
    useEffect(() => { if (deafened !== undefined) apiRef.current?.setDeafened(deafened); }, [deafened]);
    useEffect(() => {
        const app = apiRef.current; if (!app || !data) return;
        Object.entries(data).forEach(([e, cats]) => Object.entries(cats || {}).forEach(([id, d]) => d && app.setData(e, id, d)));
    }, [data]);
    useEffect(() => { apiRef.current?.setLoading(loading); }, [loading]);
    useEffect(() => { apiRef.current?.setError(error); }, [error]);
    useEffect(() => { apiRef.current?.setVoiceState(voiceState); setVs(voiceState); }, [voiceState]);
    useEffect(() => { apiRef.current?.setVoiceAmplitude(voiceAmplitude); setAmp(voiceAmplitude); }, [voiceAmplitude]);
    useEffect(() => { if (transcript != null) apiRef.current?.setTranscript(transcript); }, [transcript]);
    useEffect(() => { apiRef.current?.setAccent(accent); }, [accent]);

    return (
        <div
            ref={hostRef}
            className={`${className || ''}${uiHidden ? ' ui-hidden' : ''}`}
            style={{ display: 'block', background: 'transparent', ...style }}
        >
            {headHost && createPortal(
                <EmberHead state={vs} amplitude={amp} alert={emberAlert} size="100%" faceOnly />,
                headHost
            )}
            {hideHost && createPortal(
                <button
                    type="button"
                    className="hu-btn"
                    onClick={() => setUiHidden(h => !h)}
                    aria-pressed={uiHidden}
                    aria-label={uiHidden ? 'Show dashboard' : 'Hide dashboard'}
                >
                    {uiHidden ? 'Show UI' : 'Hide UI'}
                </button>,
                hideHost
            )}
        </div>
    );
});

export default FlameDashboard;