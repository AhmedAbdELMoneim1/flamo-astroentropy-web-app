// Mirror of src/bridge.py — keep the two in sync. bridge.py is the spec.
// Every packet (both directions): { v, type, payload, ts }
//
// Commands (agent -> frontend)
//   view.open        { pillar, view, focus, scenario, coverage, coverage_note, headline, key_points, dashboard, ranking, suggestions }
//                    dashboard: { kpis, charts, table, gaps, cards, note, source, ... } (see CONTRACT.md); may be absent
//                    focus: string|null; scenario: string|null (null = custom);
//                    coverage: 'High'|'Medium'|'Low'|'None'|null ('None' = a named scenario with no test: the spacesuit atmosphere);
//                    coverage_note: { label, level } | null (spacesuit: the oxygen-rich burner-stream flames);
//                    ranking: the "Most relevant investigations" panel (rank_investigations); suggestions: "Ask me" chips
//   conditions.set   { scenario, inputs }   inputs = ONLY changed values; scenario null = custom
//   answer.show      { request_id, metric, question, speak, kpis, charts, table, gaps, cards, source, pillar, ranking? }
//                    a chart may carry `ref` (a path under /api) instead of series
//   alert.set        { level: 'emergency'|'clear', title, steps, location?: 'cabin'|'suit', lang?: 'en'|'ar', footer? }
//   note.add         { text }
// Events (frontend -> agent)
//   state.sync           { pillar, view, focus, scenario, inputs, mission }   (silent; sent when the agent joins,
//                        and with pillar/view null when the user returns to the entry view)
//   mission.loaded       { mission }                                          (silent)
//   view.selected        { pillar, view, focus, scenario, source }   (view optional; agent answers with view.open)
//   conditions.changed   { scenario?, inputs? }   scenario = preset id to apply; omit for a manual edit
//   question.asked       { text }   an "Ask me" chip was tapped; the agent answers it like a spoken question

export const PROTOCOL_VERSION = 1;

export const TOPIC_COMMAND = 'ui.command'; // agent    -> frontend
export const TOPIC_EVENT = 'ui.event'; //     frontend -> agent

export const CMD = {
  VIEW_OPEN: 'view.open',
  CONDITIONS_SET: 'conditions.set',
  ALERT_SET: 'alert.set',
  NOTE_ADD: 'note.add',
  ANSWER_SHOW: 'answer.show',
  INTERACTION_ACK: 'interaction.ack',
};

export const EVT = {
  STATE_SYNC: 'state.sync',
  MISSION_LOADED: 'mission.loaded',
  VIEW_SELECTED: 'view.selected',
  CONDITIONS_CHANGED: 'conditions.changed',
  QUESTION_ASKED: 'question.asked',
  EMERGENCY_CLEARED: 'emergency.cleared',   // the banner's x button
};

const encoder = new TextEncoder();
const decoder = new TextDecoder();

export function encodeEnvelope(type, payload = {}) {
  return encoder.encode(
    JSON.stringify({ v: PROTOCOL_VERSION, type, payload, ts: Date.now() }),
  );
}

// Returns { type, payload } or null if the packet is malformed / wrong version.
export function decodeEnvelope(bytes) {
  try {
    const env = JSON.parse(decoder.decode(bytes));
    if (env.v !== PROTOCOL_VERSION || typeof env.type !== 'string') return null;
    return { type: env.type, payload: env.payload ?? {} };
  } catch {
    return null;
  }
}
