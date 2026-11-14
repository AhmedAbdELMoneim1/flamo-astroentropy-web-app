// Pure functions, no React. Translates between the backend vocabulary (bridge.py / CONTRACT.md)
// and the dashboard engine's vocabulary.
//
// Rule: this file only SELECTS and ARRANGES what the agent sent. It never computes a number, never sorts a bar chart
// into a ranking, and holds no data of its own. `ranking` comes only from a rank_investigations answer.

// The dashboard has no environment tabs, so its env is always this one.
export const DASH_ENV = 'spacecraft';

/* ---------------- scenario <-> background ---------------- */
const SCEN_TO_BG = { iss: 'cabin', moon_base: 'habitat', spacesuit: 'suit' };
const BG_TO_SCEN = { cabin: 'iss', habitat: 'moon_base', suit: 'spacesuit' };
// scenario null = custom conditions: keep whatever background is showing
export const scenarioToBg = (scenario, current = 'cabin') => SCEN_TO_BG[scenario] ?? current;
export const bgToScenario = (bg) => BG_TO_SCEN[bg] ?? null;

/* ---------------- inputs <-> sliders (oxygen and pressure only) ---------------- */
const round = (v, d = 2) => +Number(v).toFixed(d);

// backend inputs -> dashboard slider values (only keys that are present)
export function inputsToSliders(inputs = {}) {
    const out = {};
    if (inputs.oxygen_pct != null) out.oxygen = inputs.oxygen_pct;
    if (inputs.pressure_psi != null) out.pressure = round(inputs.pressure_psi, 1);          // the slider is in psi: nothing is converted here
    return out;
}

const SLIDER_TO_INPUT = {
    oxygen: (v) => ({ oxygen_pct: v }),
    pressure: (v) => ({ pressure_psi: round(v, 1) }),
};

// dashboard onValuesChange -> backend inputs object, or null when there is nothing to send.
export function valuesChangeToInputs(_category, values, changedKey) {
    const keys = changedKey === 'reset' ? Object.keys(values) : [changedKey];
    const out = {};
    for (const k of keys) if (SLIDER_TO_INPUT[k] && values[k] != null) Object.assign(out, SLIDER_TO_INPUT[k](values[k]));
    return Object.keys(out).length ? out : null;
}

/* ---------------- coverage badges ---------------- */
// High / Medium / Low -> "Data coverage: High". None (the spacesuit atmosphere) never reads "Data coverage: None":
// it reads the fixed text, plus a second chip from coverage_note. null = custom conditions.
export function coverageBadges(coverage, note, texts = {}) {
    const cls = { High: 'ok', Medium: '', Low: 'hot' };
    const out = [];
    if (coverage === 'None') out.push({ text: texts.no_coverage ?? 'Spacesuit atmosphere: none tested', cls: 'hot' });
    else if (coverage in cls) out.push({ text: `Data coverage: ${coverage}`, cls: cls[coverage] });
    else out.push({ text: 'Custom conditions', cls: '' });
    if (note?.label) out.push({ text: `${note.label}: ${note.level}`, cls: cls[note.level] ?? '' });
    return out;
}

/* ---------------- shared pieces ---------------- */
const label = (a) => (a?.unit ? `${a.label} (${a.unit})` : a?.label ?? '');
// titles that the decisions fix for two tools whose rows must not read as a ranking
const TOOL_TITLE = (texts) => ({ rank_materials: texts.rank_materials_title, rank_agents: texts.rank_agents_title });

const tableVM = (table, idPrefix) =>
    table && table.rows?.length
        ? {
            columns: table.columns.filter(c => !c.hidden).map(({ key, label: l, unit, unit_from }) => ({ key, label: l, unit: unit || '', from: unit_from || '' })),
            rows: table.rows.map((row, i) => ({ ...row, id: `${idPrefix}-${i + 1}` })),
            footer: table.footer || '',
        }
        : null;

const chartVM = (c) => ({
    id: c.id, type: c.type, title: c.title, ref: c.ref || null, shown: c.shown || '',
    xLabel: label(c.x), yLabel: label(c.y), series: c.series || [],
});

const kpiVM = (k) => ({ label: k.label, value: k.value, unit: k.unit || '', basis: k.basis || '', trust: k.trust || '', from: k.unit_from && k.value_from != null ? `${k.value_from} ${k.unit_from}` : '' });

const rankingVM = (r) =>
    r && r.rows?.length
        ? {
            rows: r.rows, tierLabel: r.tier_label || '', divider: r.divider || '', note: r.note || '', footer: r.footer || '',
            scenario: r.scenario ?? null, pillar: r.pillar ?? null,
        }
        : null;

/* ---------------- view.open -> overview view-model ---------------- */
// payload = the whole view.open payload (dashboard + ranking + suggestions + coverage_note)
export function overviewToView(payload, texts = {}) {
    if (!payload?.dashboard) return null;
    const dash = payload.dashboard;
    const kpis = (dash.kpis || []).map(kpiVM);
    const k0 = kpis[0];
    const badges = coverageBadges(payload.coverage, payload.coverage_note, texts);
    return {
        kind: 'overview',
        view: dash.view,
        pillar: payload.pillar ?? dash.pillar ?? null,
        scenario: payload.scenario ?? null,
        badges,
        summary: { main: k0 ? k0.value : '–', unit: k0?.unit ?? '', text: dash.headline || '', note: dash.note || '' },
        kpis,
        charts: (dash.charts || []).map(chartVM),
        table: tableVM(dash.table, dash.view || 'view'),
        tableTitle: '',
        cards: dash.cards || [],
        gaps: dash.gaps || [],
        ranking: rankingVM(payload.ranking),
        suggestions: payload.suggestions || [],
    };
}

/* ---------------- answer.show -> answer view-model ---------------- */
const SCENARIO_LABEL = { iss: 'ISS cabin atmosphere', moon_base: 'Moon base habitat atmosphere', spacesuit: 'Spacesuit atmosphere' };

export function answerToView(a, texts = {}) {
    if (!a) return null;
    const title = TOOL_TITLE(texts)[a.tool] || '';
    return {
        kind: 'answer',
        requestId: a.request_id,
        tool: a.tool || a.metric || '',
        pillar: a.pillar ?? null,
        question: a.question || '',
        speak: a.speak || [],
        speakRefs: a.speak_refs || [],          // per spoken line: the source numbers it uses (superscripts)
        sources: (a.sources || []).slice(0, 6),
        clarify: a.clarify || null,
        openQuestion: !!a.open_question,
        offer: a.offer || null,
        scenarioLabel: SCENARIO_LABEL[a.for_scenario || a.scenario] || '',          // the atmosphere the answer is about, shown on the card (Round 10 §10.2)
        badges: a.level || a.coverage_note ? coverageBadges(a.level, a.coverage_note, texts) : [],
        kpis: (a.kpis || []).map(kpiVM),
        charts: (a.charts || []).map(chartVM),
        table: tableVM(a.table, a.request_id || 'ans'),
        tableTitle: title,
        cards: a.cards || [],
        gaps: a.gaps || [],
        ranking: rankingVM(a.ranking),
        nearest: a.nearest || null,
    };
}
