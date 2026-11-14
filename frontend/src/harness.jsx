// TEMPORARY visual harness (not committed): mounts the dashboard engine with real packets, no LiveKit.
import { mountDashboard } from './coreSolution/FlameDashboard.jsx';
import { overviewToView, answerToView, coverageBadges } from './coreSolution/adapters.js';
import './coreSolution/FlameDashboard.css';
const fx = await (await fetch('/fx.json')).json();
const host = document.getElementById('root');
const app = mountDashboard(host, { category: 'flammability', apiUrl: '', loadChart: async () => (await fetch('/api/charts/o2_vs_pressure')).json(), onAsk: (d) => console.log('ask', d.text), onCategoryChange: (c) => console.log('cat', c) });
const texts = fx.catalog.texts;
app.setTexts(texts);
window.app = app; window.fx = fx;
window.show = (key) => {
  const p = fx.views[key]; const pillar = p.pillar;
  app.setCategory(pillar);
  app.setData('spacecraft', pillar, overviewToView(p, texts));
  app.setCoverage({ badges: coverageBadges(p.coverage, p.coverage_note, texts), custom: p.scenario == null });
};
const fx2 = await (await fetch('/fx2.json')).json();
window.ans2 = (k) => app.showAnswer(answerToView(fx2[k], texts));
window.ans = (k) => app.showAnswer(answerToView(fx.answers[k], texts));
window.show('flammability:iss');

window.setv = (o2, psi, src) => { app.setConditionSource(src || ''); app.setValues({ oxygen: o2, pressure: psi }); };
