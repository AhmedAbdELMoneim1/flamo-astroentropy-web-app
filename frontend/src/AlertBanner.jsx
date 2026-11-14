import { useDashboard } from './DashboardContext.jsx';

export default function AlertBanner() {
  const { alert } = useDashboard();
  if (!alert) return null;
  return (
    <div className="alert" role="alert">
      <strong>🚨 FIRE EMERGENCY — {alert.title}</strong>
      <ol>{alert.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
      <small>Follow your mission fire procedure.</small>
    </div>
  );
}
