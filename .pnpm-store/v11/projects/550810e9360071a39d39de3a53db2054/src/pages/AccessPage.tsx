import { useState } from "react";

import { setAccessToken } from "../api/client";

export function AccessPage() {
  const [token, setToken] = useState("");

  function enter() {
    if (!token.trim()) return;
    setAccessToken(token.trim());
    window.location.reload();
  }

  return (
    <main className="access-page">
      <div className="wizard-card access-card">
        <p className="eyebrow blue">EVIG</p>
        <h1>Acessar Mensagem direta</h1>
        <p className="muted">Informe o token fornecido pelo administrador. Ele fica somente nesta sessão do navegador.</p>
        <label>Token de acesso<input autoFocus type="password" value={token} onChange={(event) => setToken(event.target.value)} onKeyDown={(event) => event.key === "Enter" && enter()} /></label>
        <button className="primary" disabled={!token.trim()} onClick={enter}>Entrar</button>
      </div>
    </main>
  );
}
