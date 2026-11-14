import { useDashboard } from './DashboardContext.jsx';

export default function CategoryNav() {
  const { categories, category, selectCategory } = useDashboard();
  return (
    <nav className="cat-nav">
      {categories.map((c) => (
        <button
          key={c.id}
          className={`cat-tab ${category === c.id ? 'active' : ''}`}
          onClick={() => selectCategory(c.id)}
        >
          <span className="cat-icon">{c.icon}</span>
          <span>{c.label}</span>
        </button>
      ))}
    </nav>
  );
}
