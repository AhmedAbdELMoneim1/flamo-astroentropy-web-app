// Main stage: shows whichever category the agent (or the user) selected.
import { useDashboard } from './DashboardContext.jsx';

export default function CategoryView() {
  const { categories, category, focus, headline, keyPoints, inputs, selectCategory } = useDashboard();
  const cat = categories.find((c) => c.id === category);

  if (!cat) {
    return (
      <section className="stage empty">
        <h2>Ask Flame anything about fire safety</h2>
        <p>Say a question out loud, or pick a category on the left.</p>
      </section>
    );
  }

  return (
    <section className="stage" key={cat.id /* replays the enter animation on change */}>
      <header className="stage-head">
        <span className="stage-icon">{cat.icon}</span>
        <div>
          <h2>{cat.label}</h2>
          <p className="muted">{cat.tagline}</p>
        </div>
      </header>

      {headline && <p className="headline">{headline}</p>}
      {keyPoints.length > 0 && (
        <ul className="key-points">
          {keyPoints.map((k, i) => <li key={i}>{k}</li>)}
        </ul>
      )}

      <div className="chips">
        {cat.focus_options.map((f) => (
          <button
            key={f}
            className={`chip ${focus === f ? 'active' : ''}`}
            onClick={() => selectCategory(cat.id, f)}
          >
            {f}
          </button>
        ))}
      </div>

      {/* >>> CHART SLOT: render your NASA-data charts here <<<
          Props you have: cat.id, focus, inputs. */}
      <div className="chart-slot">
        <span>{cat.label}{focus ? ` · ${focus}` : ''}</span>
        <small>
          {inputs.material} · O₂ {inputs.oxygen_pct}% · {inputs.pressure_kpa} kPa · {inputs.airflow_cm_s} cm/s · {inputs.gravity}
        </small>
      </div>
    </section>
  );
}
