import React, { useEffect, useRef, useState } from 'react';
import {
    useVoiceAssistant, useTrackVolume, useTrackTranscription, useChat, useRoomContext, useLocalParticipant,
} from '@livekit/components-react';
import { Track } from 'livekit-client';
import { useAgentState } from '../siAssistant/useAgentState.js';
import { useNavigate, useLocation } from 'react-router-dom';
import FlameDashboard from './FlameDashboard';
import { useCategoryParam } from './categoryParam';
import { useDashboard } from './DashboardContext.jsx';
import { overviewToView, answerToView, coverageBadges, valuesChangeToInputs, inputsToSliders, scenarioToBg, DASH_ENV } from './adapters.js';
import { CATEGORIES, HOME_ACCENT } from './categories';
import SpaceCraftScene from '../spaceCraftScene/SpaceCraftScene';
import SuitHelmetScene from '../suitHelmetScene/SuitHelmetScene';
import MoonHabitatScene from '../moonHabitatScene/MoonHabitatScene';
import { readEnvUrl, writeEnvUrl, DEFAULT_SCENARIO } from './envParam.js';
import { useDeafen } from './DeafenContext.jsx';
import './EmergencyAlert.css';

// If the agent never answers a view request (e.g. it joined after state.sync), stop the spinner and say there is no data.
const LOADING_TIMEOUT_MS = 4000;

export default function FlameApp() {
    const navigate = useNavigate();
    const location = useLocation();
    const bridge = useDashboard();
    const room = useRoomContext();
    const agentState = useAgentState();
    const { audioTrack, agent } = useVoiceAssistant();   // agent is undefined until it joins
    const volume = useTrackVolume(audioTrack);          // 0..1
    const { send } = useChat();
    const { segments } = useTrackTranscription(audioTrack);
    const { localParticipant, isMicrophoneEnabled, microphoneTrack } = useLocalParticipant();
    const { deafened, setDeafened } = useDeafen();
    const muted = !isMicrophoneEnabled;
    const { segments: mySegments } = useTrackTranscription(
        microphoneTrack
            ? { participant: localParticipant, publication: microphoneTrack, source: Track.Source.Microphone }
            : undefined,
    );

    const cabinRef = useRef(null);
    const dashRef = useRef(null);
    const shown = useRef(null);       // the pillar whose overview is on screen
    const seen = useRef(new Set());
    const notesSeen = useRef(0);
    const [category, setCategory] = useCategoryParam('flammability');
    const [showDash, setShowDash] = useState(true);
    const [bg, setBg] = useState('cabin');              // 'cabin' | 'suit' | 'habitat'
    const [warm, setWarm] = useState(false);            // true = all 3 worlds are mounted
    useEffect(() => { const t = setTimeout(() => setWarm(true), 800); return () => clearTimeout(t); }, []);

    /* ================= INBOUND: agent -> screen ================= */

    // pillar -> category (the cabin scan only re-runs when the category really changes)
    useEffect(() => {
        if (bridge.pillar && bridge.pillar !== category) setCategory(bridge.pillar);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bridge.pillar]);

    // fixed UI texts from the catalog
    useEffect(() => { dashRef.current?.setTexts(bridge.texts) }, [bridge.texts]);

    // overview (view.open) -> setData(adapted); null (while a pillar is open) -> loading
    useEffect(() => {
        const dash = dashRef.current;
        if (!dash || !bridge.pillar) return;
        dash.setCategory(bridge.pillar);                 // first, so setData/setLoading hit the visible category
        if (bridge.overview) {
            shown.current = bridge.pillar;
            dash.setData(DASH_ENV, bridge.pillar, overviewToView(bridge.overview, bridge.texts));
            return;
        }
        if (shown.current === bridge.pillar) return;     // a new overview is on its way (a slider moved): keep the current one on screen (Round 12 item 8)
        if (!agent) { dash.setLoading(false); return; }   // no agent: nothing to show
        dash.setLoading(true);
        const t = setTimeout(() => dash.setLoading(false), LOADING_TIMEOUT_MS);
        return () => clearTimeout(t);
    }, [bridge.overview, bridge.pillar, !!agent]);

    // scenario -> background (null = custom conditions: keep the current one)
    useEffect(() => {
        setBg((cur) => scenarioToBg(bridge.scenario, cur));
    }, [bridge.scenario]);

    /* ---------- environment <-> URL (?env=iss|moonbase|spacesuit) ---------- */
    const bridgeRef = useRef(bridge);
    bridgeRef.current = bridge;
    const wantScen = useRef(undefined);   // undefined = URL not read yet, string = waiting for this scenario to apply

    // 1) URL -> scenario, once, as soon as the scenario catalog is loaded
    useEffect(() => {
        if (wantScen.current !== undefined || !bridge.scenarios.length) return;
        const s = readEnvUrl();
        wantScen.current = s;
        if (s && s !== bridge.scenario) bridge.setScenario(s);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bridge.scenarios.length]);

    // 2) scenario -> URL (user buttons and agent changes). Custom conditions (null) leave the URL alone.
    useEffect(() => {
        if (wantScen.current === undefined) return;                     // URL not processed yet
        if (wantScen.current) {                                          // still applying the URL value
            if (bridge.scenario !== wantScen.current) return;
            wantScen.current = null;
        }
        if (bridge.scenario) writeEnvUrl(bridge.scenario);
    }, [bridge.scenario, bridge.scenarios.length]);

    // 3) browser back/forward
    useEffect(() => {
        const onPop = () => {
            const b = bridgeRef.current;
            const s = readEnvUrl() ?? DEFAULT_SCENARIO;
            wantScen.current = s;
            if (s !== b.scenario) b.setScenario(s);
        };
        window.addEventListener('popstate', onPop);
        return () => window.removeEventListener('popstate', onPop);
    }, []);

    // inputs -> sliders (agent-driven; setValues never emits, so no echo)
    useEffect(() => { dashRef.current?.setValues(inputsToSliders(bridge.inputs)) }, [bridge.inputs]);
    // where the slider values came from: the question ("From your question: 34 % O2"), a scenario definition, or the sliders themselves
    useEffect(() => {
        const sc = bridge.scenarios?.find((x) => x.id === bridge.scenario);
        dashRef.current?.setConditionSource(bridge.conditionsSource || (sc ? `${sc.label} (scenario definition)` : 'Set with the sliders'));
    }, [bridge.conditionsSource, bridge.scenario, bridge.scenarios]);

    // coverage badges (also update while the new dashboard is still loading); null coverage = custom conditions
    useEffect(() => {
        const pending = bridge.scenario != null && bridge.coverage == null;      // a scenario is chosen but its data has not arrived: no "Custom conditions" badge (Round 10 §10.4 item 6)
        dashRef.current?.setCoverage({ badges: pending ? [] : coverageBadges(bridge.coverage, bridge.coverageNote, bridge.texts), custom: bridge.scenario == null });
    }, [bridge.coverage, bridge.coverageNote, bridge.texts, bridge.scenario]);

    // sub-view switcher: only pillars with more than one view get one (Prevention)
    useEffect(() => {
        const d = dashRef.current; if (!d) return;
        bridge.pillars.forEach((p) => d.setViews(
            p.id,
            p.views.length > 1 ? p.views.map((id) => bridge.views.find((v) => v.id === id)).filter(Boolean) : [],
        ));
    }, [bridge.pillars, bridge.views]);
    useEffect(() => { if (bridge.view) dashRef.current?.setView(bridge.view) }, [bridge.view]);

    // answer state: the dashboard follows the answer's category (D3-2), locally: no event goes back to the agent
    useEffect(() => {
        const a = bridge.answers[0];
        if (a?.pillar && a.pillar !== category) setCategory(a.pillar);
        dashRef.current?.showAnswer(a ? answerToView(a, bridge.texts) : null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bridge.answers]);

    // notes -> chat log (bridge.notes is newest first; add only the new ones, oldest first)
    useEffect(() => {
        const n = bridge.notes;
        for (let i = n.length - notesSeen.current - 1; i >= 0; i--) dashRef.current?.addMessage('ai', 'Logged: ' + n[i]);
        notesSeen.current = n.length;
    }, [bridge.notes]);

    // agent speech -> chat log (unchanged)
    useEffect(() => {
        // same id -> same bubble while it grows; a final segment is frozen and a reused id never overwrites an earlier bubble (chatLog.js)
        segments.forEach((s) => dashRef.current?.upsertMessage(s.id, 'ai', s.text, s.final));
    }, [segments]);

    // my speech -> chat log (streams while I talk, same id = same bubble)
    useEffect(() => {
        mySegments.forEach((s) => dashRef.current?.upsertMessage(s.id, 'me', s.text, s.final));
    }, [mySegments]);

    // Arrived from the cabin with ?cat=...: tell the agent which pillar is open.
    const catalogReady = bridge.pillars.length > 0;
    useEffect(() => {
        if (!catalogReady || !agent || bridge.pillar) return;
        const t = setTimeout(() => bridge.selectPillar(category, 'auto'), 250);   // let state.sync go out first
        return () => clearTimeout(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [catalogReady, agent?.identity]);

    /* ================= OUTBOUND: screen -> agent ================= */
    // The dashboard only emits these on real user actions, never on prop/API changes, so there is no echo loop.

    const onCategoryChange = (id) => {          // tab click
        setCategory(id);
        bridge.selectPillar(id);
    };
    const onValuesChange = ({ category: cat, values, changedKey }) => {   // slider / chip / reset
        const inputs = valuesChangeToInputs(cat, values, changedKey);
        if (inputs) bridge.changeInputs(inputs, 0);   // the dashboard already debounced (600 ms)
    };
    // Switch the background right away (works without the backend), then sync the scenario.
    const goEnv = (nextBg, scenarioId) => {
        setBg(nextBg);
        bridge.setScenario(scenarioId);
    };
    const onSuit = () => bg === 'suit' ? goEnv('cabin', 'iss') : goEnv('suit', 'spacesuit');
    const onHabitat = () => bg === 'habitat' ? goEnv('cabin', 'iss') : goEnv('habitat', 'moon_base');
    const onIss = () => goEnv('cabin', 'iss');
    const onHome = () => { bridge.goHome(); navigate('/home'); };
    const onViewChange = (id) => bridge.selectView(id);                              // Ignition / Materials
    const onAsk = ({ text }) => { dashRef.current?.addMessage('me', text); bridge.askQuestion(text); };   // an "Ask me" chip
    const onAnswerDismiss = () => bridge.answers.forEach((a) => bridge.dismissAnswer(a.request_id));

    const alert = bridge.alert;

    const habRef = useRef(null);

    // run the habitat scan once each time the habitat scene appears
    useEffect(() => {
        if (bg !== 'habitat') return;
        habRef.current?.scan(['hologram', 'tankA', 'hatch']);   // custom order; omit the list to scan everything
    }, [bg]);

    const layer = (id) => ({
        position: 'absolute', inset: 0,
        opacity: bg === id ? 1 : 0,          // opacity hides the whole subtree, even children with visibility:visible
        pointerEvents: bg === id ? 'auto' : 'none',
    });
    const mounted = (id) => warm || bg === id;

    return (
        <div style={{ position: 'relative', width: '100vw', height: '100vh', overflow: 'hidden', background: '#000' }}>

            <div style={{ position: 'absolute', inset: 0, zIndex: 0 }}>
                <div style={{ position: 'absolute', inset: 0, zIndex: 0 }}>
                    {mounted('cabin') && (
                        <div style={layer('cabin')}>
                            <SpaceCraftScene
                                ref={cabinRef}
                                active={bg === 'cabin'}
                                category={showDash ? category : null}
                                lensTarget={() => dashRef.current?.getLens()}
                                emberState={agentState}
                                emberAmplitude={agentState === 'speaking' ? volume : 0}
                                emberAlert={!!alert}
                            />
                        </div>
                    )}
                    {mounted('suit') && (
                        <div style={layer('suit')}>
                            <SuitHelmetScene active={bg === 'suit'} alert={!!alert} />
                        </div>
                    )}
                    {mounted('habitat') && (
                        <div style={layer('habitat')}>
                            <MoonHabitatScene
                                ref={habRef}
                                active={bg === 'habitat'}
                                showDevPanel
                                accent={showDash ? (CATEGORIES[category]?.accent ?? HOME_ACCENT) : HOME_ACCENT}
                                overlay={!showDash}
                            />
                        </div>
                    )}
                </div>
            </div>

            {showDash && (
                <div style={{ position: 'absolute', inset: 0, zIndex: 1, overflowY: 'auto' }}>
                    <FlameDashboard
                        ref={dashRef}
                        category={category}
                        voiceState={agentState}
                        voiceAmplitude={agentState === 'speaking' ? volume : 0}
                        transcript={bridge.lastAction}    /* interaction.ack text */
                        emberAlert={!!alert}
                        style={{ width: '100%', height: '100%', background: 'transparent' }}
                        suit={bg === 'suit'}
                        habitat={bg === 'habitat'}
                        onCategoryChange={onCategoryChange}
                        onValuesChange={onValuesChange}
                        onHome={onHome}
                        onAbout={() => navigate('/about', { state: { backgroundLocation: location, accent: CATEGORIES[category]?.accent ?? HOME_ACCENT } })}
                        onViewChange={onViewChange}
                        onAnswerDismiss={onAnswerDismiss}
                        onAsk={onAsk}
                        loadChart={bridge.loadChart}
                        apiUrl={bridge.apiUrl}
                        onSuit={onSuit}
                        onHabitat={onHabitat}
                        iss={bg === 'cabin'}
                        onIss={onIss}
                        onChatSend={({ text }) => send(text)}
                        muted={muted}
                        onMicToggle={(m) => localParticipant?.setMicrophoneEnabled(!m).catch(() => dashRef.current?.setMuted(!isMicrophoneEnabled))}
                        deafened={deafened}
                        onDeafenToggle={() => setDeafened((d) => !d)}
                    />
                </div>
            )}

            {/* emergency banner (alert.set): top centre, over everything; `key` is the alert's own timestamp so every new emergency question replays it */}
            {alert && (
                <div key={alert.at} className="emg" role="alert" aria-live="assertive" dir={alert.lang === 'ar' ? 'rtl' : 'ltr'}>
                    <div className="emg-head">
                        <svg className="emg-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 1 21h22L12 2Zm0 6.5 1 6.5h-2l1-6.5Zm0 8.2a1.2 1.2 0 1 1 0 2.4 1.2 1.2 0 0 1 0-2.4Z" /></svg>
                        <div className="emg-t">
                            <span className="emg-k">{alert.lang === 'ar' ? 'طوارئ' : 'EMERGENCY'}</span>
                            <b>{alert.title}</b>
                        </div>
                        <button type="button" className="emg-x" aria-label="Dismiss the emergency" onClick={bridge.dismissAlert}>×</button>
                    </div>
                    <ol className="emg-steps">
                        {alert.steps.map((x) => <li key={x}><span>{x}</span></li>)}
                    </ol>
                    {alert.footer && <p className="emg-foot">{alert.footer}</p>}
                </div>
            )}

            {!showDash && (
                <button onClick={() => setShowDash(true)} style={{ position: 'absolute', right: 20, bottom: 20, zIndex: 2 }}>
                    Open dashboard
                </button>
            )}
        </div>
    );
}