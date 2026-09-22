import type { MessageTemplate, TemplatePreset } from "../api/types";

type Props = {
  item: MessageTemplate | TemplatePreset;
  onUse: () => void;
  onView: () => void;
  onDelete?: () => void;
};

function isTemplate(item: MessageTemplate | TemplatePreset): item is MessageTemplate {
  return "status" in item;
}

export function TemplateCard({ item, onUse, onView, onDelete }: Props) {
  const body = item.components.find((component) => component.type.toUpperCase() === "BODY")?.text;
  const canDelete = isTemplate(item) && item.status !== "PENDING" && !!onDelete;
  return (
    <article className="template-card">
      <div className="labels">
        <span>
          <span className={`category ${item.category.toLowerCase()}`}>{item.category === "UTILITY" ? "UTILIDADE" : "MARKETING"}</span>
          {!isTemplate(item) && item.tags[0] && <span className="subtag">{item.tags[0].toUpperCase()}</span>}
        </span>
        {isTemplate(item) && <span className={`status ${item.status.toLowerCase()}`}>{item.status}</span>}
      </div>
      <h3>{"display_name" in item ? item.display_name : item.name}</h3>
      {isTemplate(item) && <p className="muted">Meta: {item.name}</p>}
      <p className="description">{"description" in item ? item.description : "Template sincronizado com a conta Meta."}</p>
      <div className="message-snippet">{body}</div>
      {!isTemplate(item) && <div className="reach"><b>{item.estimated_reach.toLocaleString("pt-BR")}</b> pessoas</div>}
      <footer>
        <span className="muted">{isTemplate(item) ? item.language : item.tags.join(" · ")}</span>
        <div>
          {canDelete && <button className="ghost small danger" onClick={onDelete} title="Excluir template">🗑</button>}
          <button className="ghost" onClick={onView}>Ver</button>
          <button className="primary small" onClick={onUse}>Usar →</button>
        </div>
      </footer>
    </article>
  );
}

