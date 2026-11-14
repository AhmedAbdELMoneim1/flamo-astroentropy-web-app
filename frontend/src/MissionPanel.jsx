import { useDashboard } from './DashboardContext.jsx';

export default function MissionPanel() {
  const { mission, notes, log, loadMission } = useDashboard();
  return (
    <section className="card">
      <h3>Mission</h3>
      {!mission ? (
        <button className="btn" onClick={loadMission}>Load mission</button>
      ) : (
        <dl className="mission">
          {Object.entries(mission).map(([k, v]) => (
            <div key={k}><dt>{k.replace(/_/g, ' ')}</dt><dd>{String(v)}</dd></div>
          ))}
        </dl>
      )}

      {notes.length > 0 && (
        <>
          <h3>Log</h3>
          <ul className="notes">{notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </>
      )}

      <ul className="log">{log.map((l, i) => <li key={i}>{l}</li>)}</ul>
    </section>
  );
}
