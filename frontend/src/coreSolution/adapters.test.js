import { describe, it, expect } from 'vitest';
import { inputsToSliders, valuesChangeToInputs, scenarioToBg, bgToScenario, overviewToView, answerToView, coverageBadges } from './adapters.js';

const texts = { no_coverage: 'Spacesuit atmosphere: none tested', rank_materials_title: 'Flame spread in the tested materials (not a safety ranking)', rank_agents_title: 'Gases added in the experiments' };

describe('units', () => {
    it('the pressure slider is in psi: nothing is converted', () => expect(inputsToSliders({ pressure_psi: 14.7 }).pressure).toBe(14.7));
    it('slider psi goes back as psi', () => expect(valuesChangeToInputs('flammability', { pressure: 4.3 }, 'pressure')).toEqual({ pressure_psi: 4.3 }));
    it('spacesuit round trip stays at 4.3 psi', () => {
        const v = inputsToSliders({ pressure_psi: 4.3 }).pressure;
        expect(valuesChangeToInputs('flammability', { pressure: v }, 'pressure').pressure_psi).toBe(4.3);
    });
    it('only oxygen and pressure are inputs', () => {
        expect(inputsToSliders({ oxygen_pct: 30, airflow_cm_s: 10, gravity: 'lunar', material: 'pmma' })).toEqual({ oxygen: 30 });
        expect(valuesChangeToInputs('prevention', { heatFlux: 30 }, 'heatFlux')).toBeNull();
        expect(valuesChangeToInputs('prevention', { chip: 'PMMA' }, 'chip')).toBeNull();
        expect(valuesChangeToInputs('flammability', { oxygen: 21, heatFlux: 30 }, 'reset')).toEqual({ oxygen_pct: 21 });
    });
});

describe('scenario <-> background', () => {
    it('maps both ways', () => {
        expect(scenarioToBg('moon_base')).toBe('habitat');
        expect(scenarioToBg('spacesuit')).toBe('suit');
        expect(bgToScenario('cabin')).toBe('iss');
    });
    it('custom (null) keeps the current background', () => expect(scenarioToBg(null, 'suit')).toBe('suit'));
});

describe('coverage badges', () => {
    it('named scenarios', () => {
        expect(coverageBadges('High', null)[0].text).toBe('Data coverage: High');
        expect(coverageBadges('Medium', null)[0].text).toBe('Data coverage: Medium');
    });
    it('the spacesuit atmosphere is never "Data coverage: None"', () => {
        const b = coverageBadges('None', { label: 'Oxygen-rich flames (burner stream, not the atmosphere)', level: 'Medium' }, texts);
        expect(b.map((x) => x.text)).toEqual(['Spacesuit atmosphere: none tested', 'Oxygen-rich flames (burner stream, not the atmosphere): Medium']);
        expect(b.some((x) => /Data coverage: None/.test(x.text))).toBe(false);
    });
    it('custom conditions', () => expect(coverageBadges(null, null)[0].text).toBe('Custom conditions'));
});

const payload = (over = {}) => ({
    pillar: 'suppression', view: 'suppression', scenario: 'iss', coverage: 'High', headline: 'Suppression: diluent in the atmosphere',
    dashboard: {
        view: 'suppression', headline: 'Suppression: diluent in the atmosphere',
        kpis: [{ id: 'a', label: 'tests with added CO2', value: 50, unit: '', basis: '50 of 221 tests', trust: 'table' }],
        charts: [{ id: 'ext_co2', type: 'scatter', title: 'Extinction diameter vs CO2', x: { label: 'CO2', unit: '%' }, y: { label: 'extinction diameter', unit: 'mm' }, series: [{ name: 'PSI-69', points: [{ x: 5, y: 2 }, { x: 1, y: 3 }] }] }],
        table: { columns: [{ key: 'test', label: 'test' }], rows: [{ test: 'PSI-69 A1' }], footer: '1 of 20 rows' },
        gaps: ['A gap'], cards: [{ statement: 'S', wording: 'W' }], note: '',
    },
    ranking: { rows: [{ rank: 1, group: 'ranked', name: 'FLEX (PSI-69)', tier: 'A', tests: 36, tests_label: '36 tests near the ISS cabin', findings: 66 }], tier_label: 'relevance tier (from the official PSI description)' },
    suggestions: ['Which gases did the experiments add?'], ...over,
});

describe('overviewToView', () => {
    it('keeps what the agent sent and invents nothing', () => {
        const v = overviewToView(payload(), texts);
        expect(v.kind).toBe('overview');
        expect(v.summary.main).toBe(50);
        expect(v.table.footer).toBe('1 of 20 rows');
        expect(v.ranking.rows[0].tests_label).toBe('36 tests near the ISS cabin');
        expect(v.suggestions).toEqual(['Which gases did the experiments add?']);
        expect(v.gaps).toEqual(['A gap']);
    });
    it('chart points keep the order and the count the agent sent (never sorted)', () => {
        const v = overviewToView(payload(), texts);
        expect(v.charts[0].series[0].points.map((p) => p.x)).toEqual([5, 1]);
    });
    it('a bar chart does not become a ranking', () => {
        const p = payload();
        p.ranking = null;
        p.dashboard.charts = [{ id: 'b', type: 'bar', title: 'Bars', x: { label: 'm' }, y: { label: 'v' }, series: [{ name: 'a', points: [{ x: 'a', y: 1 }, { x: 'b', y: 9 }] }] }];
        const v = overviewToView(p, texts);
        expect(v.ranking).toBeNull();
        expect(v.charts[0].series[0].points.map((q) => q.x)).toEqual(['a', 'b']);
    });
    it('a chart with a ref keeps the ref and no series', () => {
        const p = payload();
        p.dashboard.charts = [{ id: 'o2_vs_pressure', type: 'scatter', ref: '/api/charts/o2_vs_pressure', title: 't', x: { label: 'pressure', unit: 'kPa' }, y: { label: 'oxygen', unit: '%' } }];
        expect(overviewToView(p, texts).charts[0]).toMatchObject({ ref: '/api/charts/o2_vs_pressure', series: [] });
    });
    it('nothing to show without a dashboard', () => expect(overviewToView({ pillar: 'x' }, texts)).toBeNull());
});

describe('answerToView', () => {
    it('fixed titles for the two tools that must not read as rankings', () => {
        expect(answerToView({ tool: 'rank_materials', request_id: 'a' }, texts).tableTitle).toBe('Flame spread in the tested materials (not a safety ranking)');
        expect(answerToView({ tool: 'rank_agents', request_id: 'b' }, texts).tableTitle).toBe('Gases added in the experiments');
        expect(answerToView({ tool: 'search_text', request_id: 'c' }, texts).tableTitle).toBe('');
    });
    it('carries pillar, speak and the ranking of rank_investigations', () => {
        const a = answerToView({ tool: 'rank_investigations', request_id: 'r', pillar: 'detection', question: 'q', speak: ['x'], ranking: payload().ranking }, texts);
        expect(a.pillar).toBe('detection');
        expect(a.speak).toEqual(['x']);
        expect(a.ranking.rows).toHaveLength(1);
    });
    it('null in, null out', () => expect(answerToView(null)).toBeNull());
});

describe('sources on an answer (Round 9, 6.3)', () => {
    const a = {
        request_id: 'r1', tool: 'ask_sources', question: 'What oxygen level allows steady flames?', speak: ['Oxygen levels of 26 % and above can allow steady flames.', 'Another line.'], speak_refs: [[1], [1, 2]],
        sources: [{ n: 1, label: 'NASA document', title: 'PSI-20_Reports_Dissertation', page: 31, link: 'https://psi.nasa.gov/x', link_kind: 'nasa_psi_download', viewable: true, doc_id: 'fa457b0458af' },
                  { n: 2, label: 'Paper', title: 'A paper', page: 6, link: 'https://doi.org/10.1/x', link_kind: 'doi', viewable: false }],
    };
    it('keeps the sources and the source numbers of each spoken line', () => {
        const v = answerToView(a, texts);
        expect(v.sources).toHaveLength(2);
        expect(v.speakRefs).toEqual([[1], [1, 2]]);
        expect(v.sources[0]).toMatchObject({ doc_id: 'fa457b0458af', viewable: true, page: 31 });
    });
    it('an answer without sources has none', () => expect(answerToView({ request_id: 'r', tool: 'gaps', speak: [] }, texts).sources).toEqual([]));
    it('keeps a clarify question', () => expect(answerToView({ request_id: 'r', tool: 'ask_sources', clarify: { question: 'Which?', options: ['A', 'B'] } }, texts).clarify.options).toEqual(['A', 'B']));
});
