import { describe, it, expect } from 'vitest';
import { ladderModel, ladderSvg, ladderDetail, spreadModel, nearHtml } from './conditionsView.js';
import { boxesOverlap } from './chartAxis.js';

const cond = {
    scenarios: [{ id: 'iss', label: 'ISS cabin', o2_pct: 21, p_psi: 14.7, formula: 'computed: 21 % × 14.7 psi' }, { id: 'moon_base', label: 'Moon base habitat', o2_pct: 30, p_psi: 10.2 },
        { id: 'exploration_10_2', label: 'Exploration 10.2 psia', o2_pct: 26.5, p_psi: 10.2 }, { id: 'exploration_8_2', label: 'Exploration 8.2 psia', o2_pct: 34, p_psi: 8.2 }, { id: 'spacesuit', label: 'the spacesuit atmosphere', o2_pct: 100, p_psi: 4.3 }],
    markers: [{ o2_pct: 17, label: 'flames still spread at 17 % in microgravity', ref: 'F1', page: 6 }, { o2_pct: 26, label: '26 % and above can allow steady flames', ref: 'R1', page: 31 }, { o2_pct: 40, label: 'cool flames not observed below about 40 %', ref: 'F2', page: 7 }],
    ranges: { o2_min: 12, o2_max: 40, spread_o2_min: 17.9, spread_o2_max: 22.2 },
    spread_points: [{ x: 17.9, y: 0.05, near: true }, { x: 22.2, y: 0.07, near: false }],
    n_near: 29, n_psis: 1, n_spread: 0, rows: [{ investigation: 'ACME BRE (PSI-20)', material: 'PMMA', flight: 'flight', o2_pct: 34, p_psi: 8.2, p_kpa: 56.5, outcome: 'ignited' }], gaps: [],
};

describe('oxygen ladder', () => {
    it('no two marker boxes overlap, even when the user sits on a marker', () => {
        for (const o2 of [21, 26.5, 34, 40, 100, 0]) {
            const m = ladderModel(cond, o2), boxes = m.markers.map(k => k.box);
            for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) expect(boxesOverlap(boxes[i], boxes[j])).toBe(false);
        }
    });
    it('is horizontal: scenarios above the axis, sourced markers below, numbered in oxygen order, no red or green zones', () => {
        const m = ladderModel(cond, 34);
        expect(m.markers.map(k => k.o2)).toEqual([...m.markers.map(k => k.o2)].sort((a, b) => a - b));
        m.markers.forEach(k => expect(k.kind === 'scenario' ? k.box.y < m.axisY : k.box.y > m.axisY).toBe(true));
        const svg = ladderSvg(m);
        expect(svg).toContain('Oxygen ladder') && expect(svg).not.toMatch(/#ff0000|#00ff00|danger|safe/i);
    });
    it('prints a marker text only for the selected badge and highlights the chosen scenario', () => {
        const m = ladderModel(cond, 21);
        expect(ladderDetail(m, null)).not.toContain('ISS cabin');
        const iss = m.markers.find(k => k.ref === 'iss');
        expect(ladderDetail(m, iss.n)).toContain('ISS cabin');
        expect(ladderSvg(m, { scenario: 'iss' })).toContain('class="lm act"');
    });
});

describe('spread chart', () => {
    it('is inside the tested range only when flameo says so', () => {
        expect(spreadModel(cond, 20).inside).toBe(true);
        expect(spreadModel(cond, 34).inside).toBe(false);
    });
    it('keeps the same axes whatever the oxygen slider says', () => {
        const a = spreadModel(cond, 20), b = spreadModel(cond, 60);
        expect(b.xsc).toEqual(a.xsc) && expect(b.ysc).toEqual(a.ysc) && expect(b.side).toBe('right');
    });
});

describe('nearest list', () => {
    it('prints flameo counts and the psi value with kPa in small text', () => {
        const h = nearHtml(cond);
        expect(h).toContain('<b>29</b> tests near your point in <b>1</b> investigation') && expect(h).toContain('8.2 psi') && expect(h).toContain('(56.5 kPa)');
    });
    it('says so when no test is near', () => { expect(nearHtml({ ...cond, n_near: 0, rows: [] })).toContain('No PSI test at these conditions'); });
});
