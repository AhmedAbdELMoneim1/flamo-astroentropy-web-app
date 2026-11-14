// Pure text helpers for everything the dashboard prints. No React, no DOM, no data of its own.
// Rules (decisions 6.1, display audit): never "None" / "null" / "undefined" / "NaN"; ligatures normalised (NFKC);
// chemical and unit symbols (O₂, CO₂, µm); numbers exactly as flameo gave them (never re-rounded); "1 test" / "1 finding".

const SUBSCRIPT = { 2: '₂', 3: '₃', 4: '₄', 6: '₆' };
const SPECIES = /\b(O|CO|N|H|SF|CH|C2H)(\d)\b/g;   // O2 CO2 N2 SF6 CH4 ...: whole tokens only, so ids like "PSI-101" and "XO2" stay as they are

export const NO_VALUE = '–';

/** Normalise one string for display. */
export function clean(s) {
    if (s == null) return '';
    // NFKC for the ligatures only (ﬂ ﬁ ﬀ ﬃ ...): a full NFKC would also turn the "…" of a cut into "..." and "m²" into "m2"
    return String(s)
        .replace(/[\ufb00-\ufb06]/g, (c) => c.normalize('NFKC'))
        .replace(SPECIES, (m, el, n) => el + (SUBSCRIPT[n] ?? n));
}

/** A unit, with the symbols the decisions fix (um -> µm). */
export function unitText(u) {
    if (!u) return '';
    return clean(String(u).replace(/\bum\b/g, '\u00b5m'));   // U+00B5 micro sign
}

/** A value exactly as given: a number keeps its own digits, a missing value is an en dash, text is cleaned. */
export function valueText(v) {
    if (v == null || (typeof v === 'number' && !Number.isFinite(v)) || v === 'None' || v === 'null' || v === 'undefined' || v === 'NaN') return NO_VALUE;
    if (typeof v === 'number') return String(v);
    // "0.012 to 2.1" -> "0.012–2.1" (a range of two plain numbers reads with an en dash)
    return clean(String(v).replace(/^(-?\d+(?:\.\d+)?)\s+to\s+(-?\d+(?:\.\d+)?)$/, '$1\u2013$2'));
}

/** "1 test" / "3 tests": only used when a count and a noun are both given separately. */
export const count = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;

/** Axis tick labels are computed positions, not data: a short rounded form is fine there. */
export const tick = (v) => (Number.isInteger(v) ? String(v) : String(+v.toFixed(Math.abs(v) < 10 ? 2 : 1)));

/** Number plus its unit, as the two pieces a tile prints (big number, small unit). */
export function kpiParts(k) {
    return { label: clean(k.label), value: valueText(k.value), unit: unitText(k.unit), basis: clean(k.basis), from: clean(k.from) };
}

export function summaryParts(s) {
    return { value: valueText(s.main), unit: unitText(s.unit), text: clean(s.text), note: clean(s.note) };
}

/** One row of the ranking panel. rank/name left, bar with its label right, tier chip. */
export function rankRowParts(x, top) {
    const ranked = !!x.rank;
    const w = ranked ? Math.max(0, Math.min(100, ((+x.tests || 0) / (top || 1)) * 100)) : 0;
    return { ranked, rank: ranked ? String(x.rank) : '', name: clean(x.name), tier: x.tier == null ? '' : `tier ${x.tier}`, label: clean(x.tests_label), width: w };
}

/** Table cell text. */
export const cellText = (v) => valueText(v);

/** Every string a view-model would print, in order. The display audit runs its rules over this list. */
export function viewStrings(v) {
    const out = [];
    const add = (s) => { if (s !== '' && s != null) out.push(s); };
    (v.badges || []).forEach((b) => add(clean(b.text)));
    if (v.summary) { const s = summaryParts(v.summary); [s.value, s.unit, s.text, s.note].forEach(add); }
    if (v.question) add(clean(v.question));
    (v.speak || []).forEach((x) => add(clean(x)));
    (v.kpis || []).forEach((k) => { const p = kpiParts(k); [p.label, p.value, p.unit, p.basis].forEach(add); });
    (v.charts || []).forEach((c) => {
        add(clean(c.title)); add(clean(c.xLabel)); add(clean(c.yLabel)); add(clean(c.shown));
        (c.series || []).forEach((s) => { add(clean(s.name)); (s.points || []).forEach((p) => { add(clean(p.label)); if (c.type === 'bar') { add(clean(p.x)); add(valueText(p.y)); } }); });
    });
    if (v.ranking) {
        const top = Math.max(1, ...v.ranking.rows.filter((x) => x.rank).map((x) => +x.tests || 0));
        v.ranking.rows.forEach((x) => { const p = rankRowParts(x, top); [p.name, p.tier, p.label].forEach(add); });
        [v.ranking.divider, v.ranking.footer, v.ranking.note, v.ranking.tierLabel].forEach((s) => add(clean(s)));
    }
    if (v.table) {
        v.table.columns.forEach((c) => { add(clean(c.label)); add(unitText(c.unit)); });
        v.table.rows.forEach((r) => v.table.columns.forEach((c) => add(cellText(r[c.key]))));
        add(clean(v.table.footer));
    }
    (v.cards || []).forEach((c) => { add(clean(c.statement)); add(clean(c.wording)); add(clean(c.paper)); });
    (v.gaps || []).forEach((g) => add(clean(g)));
    (v.sources || []).forEach((x) => { add(clean(x.label)); add(clean(x.title)); add(clean(x.evidence)); add(clean(x.quote)); });
    (v.suggestions || []).forEach((q) => add(clean(q)));
    return out;
}
