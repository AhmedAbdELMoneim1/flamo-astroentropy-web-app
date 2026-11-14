import { useState } from 'react';
import {
  LiveKitRoom,
  RoomAudioRenderer,
  DisconnectButton,
  TrackToggle,
} from '@livekit/components-react';
import { Track } from 'livekit-client';
import Visualizer from './Visualizer.jsx';
import { DashboardProvider } from './DashboardContext.jsx';
import CategoryNav from './CategoryNav.jsx';
import CategoryView from './CategoryView.jsx';
import ConditionsPanel from './ConditionsPanel.jsx';
import MissionPanel from './MissionPanel.jsx';
import AlertBanner from './AlertBanner.jsx';

const API_URL = import.meta.env.VITE_API_URL || '';

export default function App() {
  const [conn, setConn] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function connect() {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/api/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(`Token request failed (${res.status})`);
      setConn(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  if (!conn) {
    return (
      <main className="screen">
        <h1>🔥 Flame</h1>
        <p className="muted">Fire-safety copilot</p>
        <button className="btn primary" onClick={connect} disabled={loading}>
          {loading ? 'Connecting…' : 'Start conversation'}
        </button>
        {error && <p className="error">{error}</p>}
      </main>
    );
  }

  return (
    <LiveKitRoom
      serverUrl={conn.server_url}
      token={conn.participant_token}
      connect
      audio
      video={false}
      onDisconnected={() => setConn(null)}
    >
      <DashboardProvider>
        <div className="app">
          <AlertBanner />
          <header className="topbar">
            <div className="viz"><Visualizer /></div>
            <div className="controls">
              <TrackToggle source={Track.Source.Microphone} className="btn" />
              <DisconnectButton className="btn danger">End</DisconnectButton>
            </div>
          </header>
          <aside className="side">
            <CategoryNav />
            <ConditionsPanel />
            <MissionPanel />
          </aside>
          <CategoryView />
        </div>
      </DashboardProvider>
      <RoomAudioRenderer />
    </LiveKitRoom>
  );
}