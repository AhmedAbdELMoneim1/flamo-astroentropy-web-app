// Mirror of src/bridge.py — keep the two in sync.
// Every packet (both directions): { v, type, payload, ts }

export const PROTOCOL_VERSION = 1;

export const TOPIC_COMMAND = 'ui.command'; // agent    -> frontend
export const TOPIC_EVENT = 'ui.event'; //     frontend -> agent

export const CMD = {
  CATEGORY_OPEN: 'category.open',
  CONDITIONS_SET: 'conditions.set',
  ALERT_SET: 'alert.set',
  NOTE_ADD: 'note.add',
};

export const EVT = {
  STATE_SYNC: 'state.sync',
  MISSION_LOADED: 'mission.loaded',
  CATEGORY_SELECTED: 'category.selected',
  CONDITIONS_CHANGED: 'conditions.changed',
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
