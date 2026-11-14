// DataPanel.jsx — form state via LiveKit DATA PACKETS (not text streams)
//
// Flow:
//   1. Click "Load data"  -> GET /api/mission  -> show JSON
//   2. Publish JSON as a reliable data packet (topic: form.update)
//   3. User edits a field -> debounced data packet -> agent speaks
//
// Must be rendered INSIDE <LiveKitRoom>.
import { useRef, useState, useEffect } from 'react';
import { useRoomContext, useVoiceAssistant } from '@livekit/components-react';
import { RoomEvent } from 'livekit-client';

const API_URL = import.meta.env.VITE_API_URL || '';
const TOPIC = 'form.update'; // must match agent TOPIC

const encoder = new TextEncoder();
const decoder = new TextDecoder();

export default function DataPanel() {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant(); // undefined until the agent joins

  const [data, setData] = useState(null);
  const [log, setLog] = useState([]);
  const timer = useRef(null);

  const addLog = (msg) => setLog((l) => [msg, ...l].slice(0, 8));

  // ── Publish form values as a reliable data packet ────────────────────────
  async function sendToAgent(values, source) {
    if (!room?.localParticipant) {
      addLog('⚠ room not ready, nothing sent');
      return;
    }

    const envelope = {
      v: 1,
      source,           // 'backend_fetch' | 'user_edit' | 'resync'
      values,
      ts: Date.now(),
    };
    const bytes = encoder.encode(JSON.stringify(envelope));

    const opts = {
      reliable: true,
      topic: TOPIC,
    };
    // Prefer targeting the agent only (if already in the room)
    if (agent?.identity) {
      opts.destinationIdentities = [agent.identity];
    }

    await room.localParticipant.publishData(bytes, opts);
    addLog(`→ data packet (${source})${agent?.identity ? ' → agent' : ' → room'}`);
  }

  // ── Optional: receive data packets FROM the agent (UI commands) ──────────
  useEffect(() => {
    if (!room) return;

    const onData = (payload, participant, _kind, topic) => {
      // Ignore our own packets
      if (participant?.identity === room.localParticipant?.identity) return;

      let msg;
      try {
        msg = JSON.parse(decoder.decode(payload));
      } catch {
        return;
      }

      if (topic === 'ui.command') {
        addLog(`← ui.command from ${participant?.identity ?? '?'}: ${msg.type ?? '?'}`);
        // Hook your UI handlers here, e.g.:
        // if (msg.type === 'ui.highlight') highlightField(msg.payload.field);
        // if (msg.type === 'ui.toast') showToast(msg.payload);
      }
    };

    room.on(RoomEvent.DataReceived, onData);
    return () => {
      room.off(RoomEvent.DataReceived, onData);
    };
  }, [room]);

  // ── Re-sync when the agent joins (cold-start fix for data packets) ───────
  // Data packets are NOT stored by the server, so if the agent joins late we
  // must re-send the current form state.
  useEffect(() => {
    if (!room || !data) return;

    const onParticipantConnected = (participant) => {
      if (participant.isAgent || participant.identity?.includes('agent')) {
        addLog(`agent joined (${participant.identity}) → resync`);
        sendToAgent(data, 'resync');
      }
    };

    room.on(RoomEvent.ParticipantConnected, onParticipantConnected);
    return () => {
      room.off(RoomEvent.ParticipantConnected, onParticipantConnected);
    };
  }, [room, data, agent]);

  // ── Load from FastAPI backend ────────────────────────────────────────────
  async function loadData() {
    addLog('→ GET /api/mission');
    try {
      const res = await fetch(`${API_URL}/api/mission`);
      if (!res.ok) {
        addLog(`✗ backend error ${res.status}`);
        return;
      }
      const json = await res.json();
      setData(json);
      addLog('← backend returned JSON');
      await sendToAgent(json, 'backend_fetch');
    } catch (e) {
      addLog(`✗ ${e.message}`);
    }
  }

  // ── User edits a field (debounced) ───────────────────────────────────────
  function onEdit(key, rawValue) {
    const next = {
      ...data,
      [key]: typeof data[key] === 'number' ? Number(rawValue) : rawValue,
    };
    setData(next);

    clearTimeout(timer.current);
    timer.current = setTimeout(() => sendToAgent(next, 'user_edit'), 800);
  }

  return (
    <section className="panel">
      <button className="btn" onClick={loadData}>
        Load data
      </button>

      {data && (
        <div className="fields">
          {Object.entries(data).map(([key, value]) => (
            <label key={key}>
              <span>{key}</span>
              <input
                type={
                  typeof value === 'number'
                    ? 'number'
                    : key.includes('date')
                      ? 'date'
                      : 'text'
                }
                value={value}
                onChange={(e) => onEdit(key, e.target.value)}
              />
            </label>
          ))}
        </div>
      )}

      <ul className="log">
        {log.map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ul>
    </section>
  );
}