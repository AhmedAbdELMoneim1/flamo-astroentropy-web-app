// Display audit (Round 11 §11.5 item 4): no number on the conditions panel or its sections that is not in a flameo answer (the REST sample) or typed by the user (the slider values).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { conditionStrings, ladderModel, nearHtml, spreadModel } from './conditionsView.js';

const load = n => JSON.parse(readFileSync(new URL(`./fixtures/nearest_${n}.json`, import.meta.url), 'utf8'));
const CASES = [['iss', 21, 14.7], ['moon', 34, 8.2], ['suit', 100, 4.3], ['none', 60, 2]];
const nums = s => (String(s).match(/-?\d+(?:\.\d+)?/g) || []).map(Number);

describe('conditions panel display audit', () => {
    CASES.forEach(([name, o2, psi]) => {
        it(`${name}: every number printed is in the flameo answer or is a slider value`, () => {
            const cond = load(name);
            const allowed = new Set([...nums(JSON.stringify(cond)), o2, psi, 0, 25, 50, 75, 100, 1, 2, 3, 4, 5, 6, 7, 8, 9]);      // ladder ticks and marker numbers are drawing
            conditionStrings(cond, o2, psi).forEach(str => nums(str).forEach(n => expect(allowed.has(n), `${n} in "${str}"`).toBe(true)));
        });
        it(`${name}: ladder boxes never overlap`, () => {
            const m = ladderModel(cond_(name), o2), b = m.markers.map(k => k.box);
            for (let i = 0; i < b.length; i++) for (let j = i + 1; j < b.length; j++) expect(b[i].x < b[j].x + b[j].w && b[j].x < b[i].x + b[i].w && b[i].y < b[j].y + b[j].h && b[j].y < b[i].y + b[i].h).toBe(false);
        });
    });
    it('no test near: the list says so and shows the nearest tested points, and the chart has no extrapolation', () => {
        const cond = load('none');
        expect(cond.n_near).toBe(0);
        expect(nearHtml(cond)).toContain('No PSI test at these conditions');
        expect(spreadModel(cond, 60).inside).toBe(false);
    });
    it('never rates: no safe / dangerous / zone wording anywhere', () => {
        CASES.forEach(([name, o2, psi]) => conditionStrings(load(name), o2, psi).forEach(s => expect(/\b(safe|dangerous|danger zone|hazard)\b/i.test(s.replace(/does not set a single safe or dangerous/gi, ''))).toBe(false)));
    });
});
function cond_(n) { return load(n); }
