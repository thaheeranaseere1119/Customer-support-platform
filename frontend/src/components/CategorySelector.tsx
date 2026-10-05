import type { Category } from "../types/api";
import { CATEGORY_ICONS, Icon } from "./Icon";

export function CategorySelector({ categories, selected, onSelect }:
  { categories: Category[]; selected: string | null; onSelect: (name: string | null) => void }) {
  return (
    <div className="category-grid" role="group" aria-label="Guided support categories">
      {categories.map((c) => (
        <button type="button" key={c.name} className={`category-chip ${selected === c.name ? "active" : ""}`}
          onClick={() => onSelect(selected === c.name ? null : c.name)} aria-pressed={selected === c.name} title={c.description}>
          <Icon name={CATEGORY_ICONS[c.name] ?? "tag"} size={16} />{c.name}
        </button>
      ))}
    </div>
  );
}
