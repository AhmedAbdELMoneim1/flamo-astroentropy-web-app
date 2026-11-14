// Pure chart geometry: round ("nice") ticks, a padded domain, an optional log axis, and label placement without overlaps.
// No DOM, no data of its own (Round 10 §10.3). Tested in chartAxis.test.js.

/** One "nice" step (1, 2, 2.5, 5 x 10^n) for a span split into about `count` intervals. */
export function niceStep(span, count = 4) {
    if (!(span > 0)) return 1;
    const raw = span / count, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
    const m = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
    return m * p;
}

/** Round ticks covering [lo, hi]; the domain is padded out to the first and last tick so no tick is clipped. */
export function niceScale(lo, hi, count = 4) {
    if (lo === hi) { lo -= 1; hi += 1 }
    const step = niceStep(hi - lo, count), d0 = Math.floor(lo / step + 1e-9) * step, d1 = Math.ceil(hi / step - 1e-9) * step;
    const dec = Math.max(0, -Math.floor(Math.log10(step)) + (String(step).includes('.5') ? 1 : 0));
    const ticks = [];
    for (let v = d0; v <= d1 + step / 1e6; v += step) ticks.push(+v.toFixed(dec + 2));
    return { min: ticks[0], max: ticks[ticks.length - 1], ticks, step };
}

/** Ticks for a log axis: 1, 2, 5 x 10^n inside the padded domain. */
export function logScale(lo, hi) {
    const ticks = [];
    for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) for (const m of [1, 2, 5]) { const v = m * Math.pow(10, e); if (v >= lo / 1.0001 && v <= hi * 1.0001) ticks.push(v) }
    const min = Math.min(lo, ticks[0] ?? lo), max = Math.max(hi, ticks[ticks.length - 1] ?? hi);
    return { min, max, ticks, log: true };
}

const hit = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/**
 * Place small label boxes next to their anchor points so no two boxes (or any `blocked` box) overlap.
 * items: [{ x, y, w, h }] anchors; returns [{ x, y, w, h, ax, ay }] (box top-left + the anchor, for a leader line).
 */
export function placeLabels(items, blocked = [], bounds = { x0: 0, y0: 0, x1: 1e9, y1: 1e9 }) {
    const placed = [], taken = [...blocked];
    for (const it of items) {
        const r = 9, cand = [];
        for (const k of [1, 2, 3, 4]) {
            const d = r + k * 9;
            cand.push([d, -d - it.h], [d, d], [-d - it.w, -d - it.h], [-d - it.w, d], [0 - it.w / 2, -d - it.h], [0 - it.w / 2, d]);
        }
        let box = null;
        for (const [dx, dy] of cand) {
            const b = { x: it.x + dx, y: it.y + dy, w: it.w, h: it.h };
            if (b.x < bounds.x0 || b.y < bounds.y0 || b.x + b.w > bounds.x1 || b.y + b.h > bounds.y1) continue;
            if (taken.some(t => hit(b, t))) continue;
            box = b; break;
        }
        box = box || { x: it.x + r, y: it.y - r - it.h, w: it.w, h: it.h };
        taken.push(box);
        placed.push({ ...box, ax: it.x, ay: it.y });
    }
    return placed;
}

export const boxesOverlap = hit;
