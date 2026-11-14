// Display audit (decisions 6.1): every string the dashboard would print for the 20 overviews (5 views x ISS / Moon base /
// spacesuit / custom) and for every golden answer, checked against the display rules.
// Fixtures: scripts/gen_display_fixtures.py (the packets exactly as the agent sends them, from serving.db).
import { describe, it, expect } from 'vitest';
import fx from './fixtures/display.json';
import { overviewToView, answerToView } from './adapters.js';
import { viewStrings, kpiParts, rankRowParts, valueText, unitText, clean, count } from './display.js';

const texts = { no_coverage: 'Spacesuit atmosphere: none tested', rank_materials_title: 'Flame spread in the tested materials (not a safety ranking)', rank_agents_title: 'Gases added in the experiments' };
const overviews = fx.overviews.map((o) => ({ name: o.name, view: overviewToView(o.payload, texts) }));
const answers = fx.answers.map((a) => ({ name: a.name, view: answerToView(a.answer, texts) }));
const all = [...overviews, ...answers];
const strings = (e) => viewStrings(e.view);

describe('fixtures', () => {
    it('cover 20 overviews and every golden answer', () => {
        expect(overviews).toHaveLength(20);
        expect(answers.length).toBeGreaterThanOrEqual(43);
        overviews.forEach((o) => expect(o.view, o.name).not.toBeNull());
    });
});

describe('display audit: what is printed', () => {
    it('never prints None, null, undefined or NaN', () => {
        for (const e of all) for (const s of strings(e)) expect(s, e.name).not.toMatch(/\b(None|null|undefined|NaN)\b/);
    });
    it('missing values read as an en dash, never empty', () => {
        expect(valueText(null)).toBe('–'); expect(valueText(undefined)).toBe('–'); expect(valueText(NaN)).toBe('–'); expect(valueText('None')).toBe('–');
        for (const e of overviews) if (e.view.table) for (const r of e.view.table.rows) for (const c of e.view.table.columns) expect(valueText(r[c.key]), `${e.name} ${c.key}`).not.toBe('');
    });
    it('normalises ligatures (NFKC): no ﬂ ﬁ ﬀ ﬃ left', () => {
        for (const e of all) for (const s of strings(e)) expect(s, e.name).not.toMatch(/[ﬀ-ﬆ]/);
        expect(clean('ﬂow velocities of the ﬁre')).toBe('flow velocities of the fire');
    });
    it('truncation shows an ellipsis, never a tilde', () => {
        for (const e of all) for (const s of strings(e)) {
            expect(s, e.name).not.toMatch(/(^|\s)~|~(\s|$)/);        // a tilde as a cut mark
            if (s.length > 100) expect(s.endsWith('~'), e.name).toBe(false);
        }
        const cut = all.flatMap(strings).filter((s) => s.endsWith('…'));
        expect(cut.length).toBeGreaterThan(0);                        // the adapter's 80-character cut is the only kind of cut
        cut.forEach((s) => expect(s).not.toMatch(/\.\.\.$/));
    });
    it('value ranges use an en dash, never a hyphen', () => {
        const range = /^-?\d+(?:\.\d+)?\s?[-–]\s?-?\d+(?:\.\d+)?/;
        for (const e of overviews) {
            const vals = [...e.view.kpis.map((k) => kpiParts(k).value), valueText(e.view.summary.main)];
            vals.forEach((v) => { if (range.test(v)) expect(v, e.name).toContain('–'); expect(v, e.name).not.toMatch(/^\d[\d.]*-\d/); });
        }
        for (const e of all) if (e.view.ranking) for (const r of e.view.ranking.rows) expect(r.tests_label ?? '', e.name).not.toMatch(/\d-\d/);
    });
    it('a range of two numbers reads "a–b", not "a to b"', () => {
        expect(valueText('0.012 to 2.6')).toBe('0.012\u20132.6'); expect(valueText('12 to 34')).toBe('12\u201334');
        for (const e of overviews) for (const k of e.view.kpis) expect(kpiParts(k).value, e.name).not.toMatch(/^\d[\d.]* to \d/);
    });
    it('numbers keep exactly the digits flameo gave', () => {
        for (const e of overviews) {
            e.view.kpis.forEach((k) => { const v = kpiParts(k).value; if (typeof k.value === 'number') expect(v).toBe(String(k.value)); });
            if (e.view.table) for (const r of e.view.table.rows) for (const c of e.view.table.columns) if (typeof r[c.key] === 'number') expect(valueText(r[c.key])).toBe(String(r[c.key]));
        }
        expect(valueText(0.012)).toBe('0.012'); expect(valueText(2.6)).toBe('2.6'); expect(valueText(221)).toBe('221'); expect(valueText(0.0004)).toBe('0.0004');
    });
    it('units use symbols: O₂, CO₂, µm, kPa, psia', () => {
        expect(unitText('um')).toBe('\u00b5m'); expect(unitText('kPa')).toBe('kPa'); expect(unitText('psia')).toBe('psia'); expect(unitText('mm/s')).toBe('mm/s');
        expect(clean('tests with added CO2 and ambient O2')).toBe('tests with added CO₂ and ambient O₂');
        expect(clean('PSI-101 and XO2')).toBe('PSI-101 and XO2');      // ids and the papers' own notation are not touched
        for (const e of all) for (const s of strings(e)) {
            expect(s, e.name).not.toMatch(/\b(O2|CO2|N2|SF6)\b/);
            expect(s, e.name).not.toMatch(/\bKPA\b|\bkpa\b|\bPSIA\b/);
        }
        for (const e of all) { e.view.kpis.forEach((k) => expect(unitText(k.unit), e.name).not.toBe('um')); }
    });
    it('"1 test" and "1 finding", never "1 tests" or "1 findings"', () => {
        expect(count(1, 'test')).toBe('1 test'); expect(count(2, 'test')).toBe('2 tests'); expect(count(1, 'finding')).toBe('1 finding');
        for (const e of all) for (const s of strings(e)) expect(s, e.name).not.toMatch(/\b1 (tests|findings|investigations|PSIs|materials)\b/);
    });
    it('every ranking row has a name and a label; ranked rows have a width inside the track', () => {
        for (const e of all) if (e.view.ranking) {
            const top = Math.max(1, ...e.view.ranking.rows.filter((x) => x.rank).map((x) => +x.tests || 0));
            for (const x of e.view.ranking.rows) {
                const p = rankRowParts(x, top);
                expect(p.name, e.name).not.toBe(''); expect(p.label, e.name).not.toBe('');
                if (p.ranked) { expect(p.width).toBeGreaterThanOrEqual(0); expect(p.width).toBeLessThanOrEqual(100); }
            }
        }
    });
    it('every KPI has a label and a value', () => {
        for (const e of all) for (const k of e.view.kpis) { const p = kpiParts(k); expect(p.label, e.name).not.toBe(''); expect(p.value, e.name).not.toBe(''); }
    });
});

describe('display audit: nothing overflows a tile', () => {
    it('no single unbroken word longer than 60 characters outside URLs and DOIs', () => {
        for (const e of all) for (const s of strings(e)) for (const w of s.split(/\s+/)) {
            if (/^(https?:|10\.\d{4,}\/)/.test(w)) continue;
            expect(w.length, `${e.name}: ${w}`).toBeLessThanOrEqual(60);
        }
    });
    it('table cells are at most 80 characters (the adapter cut) and KPI tiles carry at most 4 entries', () => {
        for (const e of overviews) {
            if (e.view.table) for (const r of e.view.table.rows) for (const c of e.view.table.columns) expect(String(valueText(r[c.key])).length, e.name).toBeLessThanOrEqual(81);
        }
    });
});
