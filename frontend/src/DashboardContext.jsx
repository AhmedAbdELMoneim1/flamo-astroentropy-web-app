// DashboardContext.jsx — the ONE place that talks to the agent.
//
//  - Incoming ui.command packets are dispatched straight into the reducer
//    (action.type === command type), so the agent drives the same state the UI uses.
//  - Outgoing user actions (tap a category, edit an input) update state locally
//    AND are sent to the agent as ui.event packets.
//
// Must be rendered INSIDE <LiveKitRoom>.
import { createContext, useCallback, useContext, useEffect, useReducer, useRef } from 'react';
import { useRoomContext, useVoiceAssistant } from '@livekit/components-react';
import { RoomEvent } from 'livekit-client';
import {
  CMD, EVT, TOPIC_COMMAND, TOPIC_EVENT, encodeEnvelope, decodeEnvelope,
} from './protocol.js';

const API_URL = import.meta.env.VITE_API_URL || '';
const Ctx = createContext(null);
export const useDashboard = () => useContext(Ctx);

const initial = {
  categories: [],
  specs: {},
  category: null,
  focus: null,
  headline: '',
  keyPoints: [],
  inputs: {},
  alert: null, // { title, steps } while an emergency is active
  notes: [],
  mission: null,
  log: [],
};

function reducer(state, action) {
  const p = action.payload;
  switch (action.type) {
    case 'bootstrap': {
      const inputs = Object.fromEntries(
        Object.entries(p.conditions).map(([k, spec]) => [k, spec.default]),
      );
      return { ...state, categories: p.categories, specs: p.conditions, inputs };
    }
    case CMD.CATEGORY_OPEN:
      return {
        ...state,
        category: p.category,
        focus: p.focus ?? null,
        headline: p.headline ?? '',
        keyPoints: p.key_points ?? [],
      };
    case CMD.CONDITIONS_SET:
      return { ...state, inputs: { ...state.inputs, ...p.inputs } };
    case CMD.ALERT_SET:
      return { ...state, alert: p.level === 'emergency' ? { title: p.title, steps: p.steps } : null };
    case CMD.NOTE_ADD:
      return { ...state, notes: [p.text, ...state.notes] };
    case 'mission.set':
      return { ...state, mission: p };
    case 'log':
      return { ...state, log: [p, ...state.log].slice(0, 6) };
    default:
      return state;
  }
}

export function DashboardProvider({ children }) {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant(); // undefined until the agent joins
  const [state, dispatch] = useReducer(reducer, initial);
  const stateRef = useRef(state);
  stateRef.current = state;
  const timer = useRef(null);
  const pendingInputs = useRef({}); // changes waiting to be sent to the agent

  const log = (msg) => dispatch({ type: 'log', payload: msg });

  // ── static catalog from the backend ──────────────────────────────────────
  useEffect(() => {
    fetch(`${API_URL}/api/categories`)
      .then((r) => r.json())
      .then((payload) => dispatch({ type: 'bootstrap', payload }))
      .catch((e) => log(`✗ categories: ${e.message}`));
  }, []);

  // ── frontend -> agent ────────────────────────────────────────────────────
  const sendEvent = useCallback(
    async (type, payload) => {
      if (!room?.localParticipant) return;
      const opts = { reliable: true, topic: TOPIC_EVENT };
      if (agent?.identity) opts.destinationIdentities = [agent.identity];
      await room.localParticipant.publishData(encodeEnvelope(type, payload), opts);
      log(`→ ${type}`);
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
      log(`← ${msg.type}`);
      dispatch({ type: msg.type, payload: msg.payload });
    };
    room.on(RoomEvent.DataReceived, onData);
    return () => room.off(RoomEvent.DataReceived, onData);
  }, [room]);

  // ── data packets aren't stored: re-sync when the agent joins ─────────────
  useEffect(() => {
    if (!agent?.identity) return;
    const s = stateRef.current;
    sendEvent(EVT.STATE_SYNC, {
      category: s.category, focus: s.focus, inputs: s.inputs, mission: s.mission,
    });
  }, [agent?.identity]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── user actions (manual control, same state the agent drives) ───────────
  const selectCategory = useCallback(
    (category, focus = null) => {
      dispatch({ type: CMD.CATEGORY_OPEN, payload: { category, focus, headline: '', key_points: [] } });
      sendEvent(EVT.CATEGORY_SELECTED, { category, focus, source: 'user_tap' });
    },
    [sendEvent],
  );

  const changeInputs = useCallback(
    (inputs, delay = 250) => {
      dispatch({ type: CMD.CONDITIONS_SET, payload: { inputs } });

      // Collect changes so quick edits to different inputs aren't lost
      pendingInputs.current = { ...pendingInputs.current, ...inputs };
      clearTimeout(timer.current);

      const flush = () => {
        const batch = pendingInputs.current;
        pendingInputs.current = {};
        sendEvent(EVT.CONDITIONS_CHANGED, { inputs: batch });
      };

      if (delay === 0) flush();                    // instant (dropdowns)
      else timer.current = setTimeout(flush, delay); // short wait (sliders, typing)
    },
    [sendEvent],
  );

  const loadMission = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/mission`);
      if (!res.ok) throw new Error(`backend ${res.status}`);
      const mission = await res.json();
      dispatch({ type: 'mission.set', payload: mission });
      sendEvent(EVT.MISSION_LOADED, { mission });
    } catch (e) {
      log(`✗ mission: ${e.message}`);
    }
  }, [sendEvent]);

  return (
    <Ctx.Provider value={{ ...state, selectCategory, changeInputs, loadMission }}>
      {children}
    </Ctx.Provider>
  );
}
