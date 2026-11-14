import { describe, it, expect } from 'vitest';
import { niceScale, niceStep, logScale, placeLabels, boxesOverlap } from './chartAxis.js';

describe('nice ticks', () => {
    it('uses 1, 2, 2.5, 5 x 10^n steps', () => {
        expect(niceStep(10)).toBe(2.5); expect(niceStep(100)).toBe(25); expect(niceStep(88)).toBe(25); expect(niceStep(480)).toBe(200);
        expect([0.5, 1].includes(niceStep(2))).toBe(true);
    });
    it('oxygen 12..100 gives round ticks, padded to cover the data', () => {
        const s = niceScale(12, 100);
        expect(s.min).toBeLessThanOrEqual(12); expect(s.max).toBeGreaterThanOrEqual(100);
        s.ticks.forEach(t => expect(Number.isInteger(t)).toBe(true));
    });
    it('pressure 29.6..506.6 gives round ticks, last tick not clipped', () => {
        const s = niceScale(29.6, 506.6);
        expect(s.max).toBeGreaterThanOrEqual(506.6); expect(s.ticks.every(t => t % 25 === 0 || t % 50 === 0 || t % 100 === 0)).toBe(true);
    });
    it('O2 18..22.2 has no 19.1 style ticks', () => {
        const s = niceScale(18, 22.2); expect(s.ticks.every(t => (t * 2) % 1 === 0 || (t * 4) % 1 === 0)).toBe(true); expect(s.max).toBeGreaterThanOrEqual(22.2);
    });
    it('log scale ticks are 1/2/5 x 10^n', () => { const s = logScale(30, 520); expect(s.ticks).toEqual([50, 100, 200, 500]); expect(s.min).toBeLessThanOrEqual(30); expect(s.max).toBeGreaterThanOrEqual(520); });
});

describe('label placement', () => {
    it('crowded anchors get boxes that do not overlap each other', () => {
        const items = [{ x: 100, y: 100, w: 60, h: 12 }, { x: 104, y: 98, w: 60, h: 12 }, { x: 108, y: 102, w: 60, h: 12 }, { x: 96, y: 104, w: 60, h: 12 }];
        const out = placeLabels(items, [], { x0: 0, y0: 0, x1: 640, y1: 260 });
        for (let i = 0; i < out.length; i++) for (let j = i + 1; j < out.length; j++) expect(boxesOverlap(out[i], out[j])).toBe(false);
    });
    it('keeps clear of blocked boxes such as the axis title', () => {
        const blocked = [{ x: 0, y: 0, w: 120, h: 14 }];
        const [p] = placeLabels([{ x: 40, y: 20, w: 60, h: 12 }], blocked, { x0: 0, y0: 0, x1: 640, y1: 260 });
        expect(boxesOverlap(p, blocked[0])).toBe(false);
    });
});
