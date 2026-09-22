import { useState } from "react";

import type { TemplateComponent } from "../api/types";

export function PhonePreview({ components }: { components: TemplateComponent[] }) {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const header = components.find((item) => item.type.toUpperCase() === "HEADER")?.text;
  const body = components.find((item) => item.type.toUpperCase() === "BODY")?.text ?? "Selecione um template";
  const footer = components.find((item) => item.type.toUpperCase() === "FOOTER")?.text;
  const buttons = components.find((item) => item.type.toUpperCase() === "BUTTONS")?.buttons ?? [];
  return (
    <div className="preview-column">
      <div className="preview-title">
        COMO CHEGA NO WHATSAPP
        <span className="theme-toggle">
          <button className={theme === "light" ? "active" : ""} onClick={() => setTheme("light")}>Claro</button>
          <button className={theme === "dark" ? "active" : ""} onClick={() => setTheme("dark")}>Escuro</button>
        </span>
      </div>
      <div className={`phone ${theme}`}>
        <div className="phone-status">09:41 <span>▮▮ ◉</span></div>
        <div className="wa-header"><b>‹</b><div className="avatar">EV</div><div><b>Evig ✓</b><small>conta comercial</small></div></div>
        <div className="chat">
          <span className="today">HOJE</span>
          <div className="bubble">{header && <b>{header}</b>}<p>{body}</p>{footer && <small>{footer}</small>}<time>09:41</time></div>
          {buttons.map((button) => <button key={button.text} className="wa-button">↪&nbsp; {button.text}</button>)}
        </div>
        <div className="composer">☺ &nbsp; Mensagem <span>⌕ &nbsp; ●</span></div>
      </div>
    </div>
  );
}

