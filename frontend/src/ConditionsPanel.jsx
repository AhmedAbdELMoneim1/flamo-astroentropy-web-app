import { useDashboard } from './DashboardContext.jsx';

export default function ConditionsPanel() {
  const { specs, inputs, changeInputs } = useDashboard();
  const entries = Object.entries(specs);
  if (!entries.length) return null;

  return (
    <section className="card">
      <h3>Conditions</h3>
      {entries.map(([key, spec]) => (
        <label key={key} className="cond">
          <span>
            {spec.label}
            {spec.kind === 'number' && (
              <b>{Number(inputs[key]).toFixed(spec.step < 1 ? 1 : 0)} {spec.unit}</b>
            )}
          </span>

          {spec.kind === 'number' && (
            <input
              type="range" min={spec.min} max={spec.max} step={spec.step}
              value={inputs[key] ?? spec.default}
              onChange={(e) => changeInputs({ [key]: Number(e.target.value) })}
            />
          )}
          {spec.kind === 'choice' && (
            <select value={inputs[key]} onChange={(e) => changeInputs({ [key]: e.target.value }, 0)}>              {spec.options.map((o) => <option key={o}>{o}</option>)}
            </select>
          )}
          {spec.kind === 'text' && (
            <>
              <input
                list={`${key}-list`} value={inputs[key] ?? ''}
                onChange={(e) => changeInputs({ [key]: e.target.value })}
              />
              <datalist id={`${key}-list`}>
                {spec.suggestions.map((o) => <option key={o} value={o} />)}
              </datalist>
            </>
          )}
        </label>
      ))}
    </section>
  );
}
