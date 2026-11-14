// DashboardContext.jsx — the ONE place that talks to the agent and holds state.
//
//  - Incoming ui.command packets go straight into the reducer
//    (action.type === command type), so the agent drives the same state the UI uses.
//  - Components call one function (selectPillar, selectView, setScenario, changeInputs,
//    goHome, loadMission). Each updates state locally AND sends a ui.event packet.
//
// Must be rendered INSIDE <LiveKitRoom>.
import { createContext, useCallback, useContext, useEffect, useReducer, useRef } from 'react';
import { useRoomContext, useVoiceAssistant } from '@livekit/components-react';
import { RoomEvent } from 'livekit-client';
import {
    CMD, EVT, TOPIC_COMMAND, TOPIC_EVENT, encodeEnvelope, decodeEnvelope,
} from './protocol.js';

const API_URL = import.meta.env.VITE_API_URL || '';
let catPromise = null;           // one GET /api/categories per page load (Round 12 item 9)
const sharedCategories = () => catPromise || (catPromise = fetch(`${API_URL}/api/categories`).then((r) => r.json()).catch((e) => { catPromise = null; throw e; }));
const Ctx = createContext(null);
export const useDashboard = () => useContext(Ctx);

const initial = {
    // catalog (GET /api/categories)
    pillars: [], views: [], scenarios: [], specs: {}, texts: {},
    // what is on screen
    pillar: null, view: null, focus: null,
    scenario: null, coverage: null, coverageNote: null, // coverage: 'High' | 'Medium' | 'Low' | 'None' | null
    headline: '', keyPoints: [],
    dashboard: null, // Dashboard object from the last view.open
    overview: null, // the whole last view.open payload (dashboard + ranking + suggestions)
    answers: [], // answer.show payloads, newest first, max 5
    lastAction: '', // interaction.ack text: the last thing the user did on screen
    inputs: {},
    alert: null, // { title, steps } while an emergency is active
    notes: [],
    mission: null,
    log: [], // last packets in and out
};

function reducer(state, action) {
    const p = action.payload;
    switch (action.type) {
        case 'bootstrap': {
            const inputs = Object.fromEntries(
                Object.entries(p.conditions).map(([k, spec]) => [k, spec.default]),
            );
            return {
                ...state, pillars: p.pillars, views: p.views, scenarios: p.scenarios,
                scenario: p.default_scenario, specs: p.conditions, inputs, texts: p.texts || {},
            };
        }
        case CMD.VIEW_OPEN:
            return {
                ...state,
                pillar: p.pillar,
                view: p.view,
                focus: p.focus ?? null,
                scenario: p.scenario ?? null,
                coverage: p.coverage ?? null,
                coverageNote: p.coverage_note ?? null,
                headline: p.headline ?? '',
                keyPoints: p.key_points ?? [],
                dashboard: p.dashboard ?? null,
                overview: p.dashboard ? p : null,
            };
        case CMD.CONDITIONS_SET: {
            const scenario = p.scenario ?? null;
            const next = { ...state, scenario, inputs: { ...state.inputs, ...p.inputs }, conditionsSource: p.source ?? null };
            if (scenario === state.scenario) return next;
            // The scenario changed: the old text no longer applies. A view.open with the new text follows.
            const sc = state.scenarios.find((s) => s.id === scenario);
            next.coverage = sc?.coverage ?? null;
            next.coverageNote = sc?.coverage_note ?? null;
            next.headline = '';
            next.keyPoints = [];
            next.dashboard = null;
            next.overview = null;
            return next;
        }
        case CMD.ALERT_SET:
            return { ...state, alert: p.level === 'emergency' ? { title: p.title, steps: p.steps, location: p.location, lang: p.lang, footer: p.footer, at: Date.now() } : null };   // `at` is new on every alert.set, so a repeated emergency shows (and animates) again
        case 'alert.dismiss':
            return { ...state, alert: null };
        case CMD.INTERACTION_ACK:
            return { ...state, lastAction: p.text ?? '' };
        case CMD.NOTE_ADD: return { ...state, notes: [p.text, ...state.notes] };
        case 'home':
            return { ...state, pillar: null, view: null, focus: null, headline: '', keyPoints: [], dashboard: null, overview: null };
        case CMD.ANSWER_SHOW:
            return { ...state, answers: [p, ...state.answers.filter((a) => a.request_id !== p.request_id)].slice(0, 5) };
        case 'answer.dismiss':
            return { ...state, answers: state.answers.filter((a) => a.request_id !== p) };
        case 'mission.set':
            return { ...state, mission: p };
        case 'log':
            return { ...state, log: [p, ...state.log].slice(0, 8) };
        default:
            return state;
    }
}

const short = (payload) => JSON.stringify(payload).slice(0, 90);

export function DashboardProvider({ children }) {
    const room = useRoomContext();
    const { agent } = useVoiceAssistant(); // undefined until the agent joins
    const [state, dispatch] = useReducer(reducer, initial);
    const stateRef = useRef(state);
    stateRef.current = state;
    const timer = useRef(null);
    const pendingInputs = useRef({}); // input changes waiting to be sent to the agent

    const log = (msg) => dispatch({ type: 'log', payload: msg });

    // ── static catalog from the backend ──────────────────────────────────────
    useEffect(() => {
        sharedCategories()
            .then((payload) => dispatch({ type: 'bootstrap', payload }))
            .catch((e) => log(`x catalog: ${e.message}`));
    }, []);

    // ── frontend -> agent ────────────────────────────────────────────────────
    const sendEvent = useCallback(
        async (type, payload) => {
            if (!room?.localParticipant || room.state !== 'connected') return;
            const opts = { reliable: true, topic: TOPIC_EVENT };
            if (agent?.identity) opts.destinationIdentities = [agent.identity];
            log(`-> ${type} ${short(payload)}`);
            try {
                await room.localParticipant.publishData(encodeEnvelope(type, payload), opts);
            } catch (e) {
                log(`x send ${type}: ${e.message}`);
            }
        },
        [room, agent],
    );

    // ── agent -> frontend ────────────────────────────────────────────────────
    useEffect(() => {
        if (!room) return;
        const onData = (bytes, participant, _kind, topic) => {
            if (topic !== TOPIC_COMMAND) return;
            if (participant?.identity === room.localParticipant?.identity) return;
            const msg = decodeEnvelope(bytes);
            if (!msg) return;
            log(`<- ${msg.type} ${short(msg.payload)}`);
            dispatch({ type: msg.type, payload: msg.payload });
        };
        room.on(RoomEvent.DataReceived, onData);
        return () => room.off(RoomEvent.DataReceived, onData);
    }, [room]);

    // ── data packets aren't stored: re-sync when the agent joins ─────────────
    const syncPayload = () => {
        const s = stateRef.current;
        return {
            pillar: s.pillar, view: s.view, focus: s.focus, scenario: s.scenario,
            inputs: s.inputs, mission: s.mission,
        };
    };
    const catalogReady = state.pillars.length > 0;
    useEffect(() => {
        if (!agent?.identity || !catalogReady) return;
        sendEvent(EVT.STATE_SYNC, syncPayload());
    }, [agent?.identity, catalogReady]); // eslint-disable-line react-hooks/exhaustive-deps

    // ── user actions (same state the agent drives) ───────────────────────────
    const selectView = useCallback(
        (view, focus = null, source = 'user_tap') => {
            const { views, scenarios, scenario } = stateRef.current;
            const pillar = views.find((v) => v.id === view)?.pillar ?? null;
            const sc = scenarios.find((s) => s.id === scenario);
            // The text (headline, key_points) arrives from the agent as a view.open reply.
            dispatch({ type: CMD.VIEW_OPEN, payload: { pillar, view, focus, scenario, coverage: sc?.coverage ?? null, coverage_note: sc?.coverage_note ?? null, headline: '', key_points: [] } });
            sendEvent(EVT.VIEW_SELECTED, { pillar, view, focus, scenario, source });
        },
        [sendEvent],
    );

    // A pillar opens its first view.
    const selectPillar = useCallback(
        (pillar, source = 'user_tap') => {
            const first = stateRef.current.pillars.find((p) => p.id === pillar)?.views[0];
            if (first) selectView(first, null, source);
        },
        [selectView],
    );

    // Back to the entry view. There is no dedicated event: a silent state.sync tells the agent.
    const goHome = useCallback(() => {
        dispatch({ type: 'home' });
        sendEvent(EVT.STATE_SYNC, { ...syncPayload(), pillar: null, view: null, focus: null });
    }, [sendEvent]); // eslint-disable-line react-hooks/exhaustive-deps

    const setScenario = useCallback(
        (id) => {
            const preset = stateRef.current.scenarios.find((s) => s.id === id);
            if (!preset) return;
            clearTimeout(timer.current); // a pending slider edit must not overrule the preset
            pendingInputs.current = {};
            dispatch({ type: CMD.CONDITIONS_SET, payload: { scenario: id, inputs: preset.inputs } });
            sendEvent(EVT.CONDITIONS_CHANGED, { scenario: id });
        },
        [sendEvent],
    );

    const changeInputs = useCallback(
        (inputs, delay = 250) => {
            dispatch({ type: CMD.CONDITIONS_SET, payload: { scenario: null, inputs } }); // manual edit = custom

            // Collect changes so quick edits to different inputs aren't lost
            pendingInputs.current = { ...pendingInputs.current, ...inputs };
            clearTimeout(timer.current);

            const flush = () => {
                const batch = pendingInputs.current;
                pendingInputs.current = {};
                sendEvent(EVT.CONDITIONS_CHANGED, { inputs: batch });
            };

            if (delay === 0) flush();                      // instant (dropdowns)
            else timer.current = setTimeout(flush, delay); // short wait (sliders, typing)
        },
        [sendEvent],
    );

    // An "Ask me" chip: sent as a question the agent answers like a spoken one.
    // the banner's x button: the screen clears at once and the agent hears emergency.cleared
    const dismissAlert = useCallback(() => { dispatch({ type: 'alert.dismiss' }); sendEvent(EVT.EMERGENCY_CLEARED, {}); }, [sendEvent]);

    const askQuestion = useCallback((text) => {
        const t = String(text ?? '').trim();
        if (t) sendEvent(EVT.QUESTION_ASKED, { text: t });
    }, [sendEvent]);

    // Charts that carry a `ref` (the full O2-vs-pressure scatter) are fetched once from the API.
    const chartCache = useRef(new Map());
    const loadChart = useCallback((ref) => {
        if (!ref) return Promise.resolve(null);
        if (!chartCache.current.has(ref)) {
            chartCache.current.set(ref, fetch(`${API_URL}${ref}`).then((r) => {
                if (!r.ok) throw new Error(`chart ${r.status}`);
                return r.json();
            }).catch((e) => { chartCache.current.delete(ref); log(`x chart: ${e.message}`); return null; }));
        }
        return chartCache.current.get(ref);
    }, []);

    const dismissAnswer = useCallback((id) => dispatch({ type: 'answer.dismiss', payload: id }), []);

    // Move an older answer to the top (same reducer path as an incoming answer.show).
    const showAnswer = useCallback((answer) => dispatch({ type: CMD.ANSWER_SHOW, payload: answer }), []);

    const loadMission = useCallback(async () => {
        try {
            const res = await fetch(`${API_URL}/api/mission`);
            if (!res.ok) throw new Error(`backend ${res.status}`);
            const mission = await res.json();
            dispatch({ type: 'mission.set', payload: mission });
            sendEvent(EVT.MISSION_LOADED, { mission });
        } catch (e) {
            log(`x mission: ${e.message}`);
        }
    }, [sendEvent]);

    return (
        <Ctx.Provider value={{ ...state, apiUrl: API_URL, selectPillar, selectView, goHome, setScenario, changeInputs, loadMission, dismissAnswer, showAnswer, askQuestion, loadChart, dismissAlert }}>
            {children}
        </Ctx.Provider>
    );
}
