import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type PropsWithChildren, useState } from "react";
import { NavLink } from "react-router-dom";

import { api, clearAccessToken } from "../api/client";
import { useOrganization } from "../state/organization";
import { WabaConnectionModal } from "./WabaConnectionModal";

export function Layout({ children }: PropsWithChildren) {
  const { organizationId, organizations, setOrganizationId, refreshOrganizations } = useOrganization();
  const client = useQueryClient();
  const [menuOpen, setMenuOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const [connectionOpen, setConnectionOpen] = useState(false);
  const authEnabled = import.meta.env.VITE_AUTH_ENABLED === "true";
  const session = useQuery({ queryKey: ["session"], queryFn: api.getSession, enabled: authEnabled });
  const isAdmin = !authEnabled || session.data?.role === "ADMIN";

  const currentOrganization = organizations.find((org) => org.id === organizationId);

  const createOrgMutation = useMutation({
    mutationFn: (name: string) => api.createOrganization({ name }),
    onSuccess: async (organization) => {
      await refreshOrganizations();
      setOrganizationId(organization.id);
      setCreating(false);
      setNewOrgName("");
      setMenuOpen(false);
      await client.invalidateQueries({ queryKey: ["templates"] });
      await client.invalidateQueries({ queryKey: ["campaigns"] });
    }
  });

  function submitNewOrg() {
    const name = newOrgName.trim();
    if (name.length < 2) return;
    createOrgMutation.mutate(name);
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><span>e</span> Gooroo</div>
        <div className="search">⌕&nbsp;&nbsp; Buscar no workspace</div>
        <p className="eyebrow">SEU WORKSPACE</p>
        <nav>
          <a>⌂ <span>Início</span></a>
          <p className="eyebrow">OPERAÇÃO AGÊNTICA</p>
          <a>⌘ <span>Sales</span></a>
          <a className="indent">✣ <span>Configurador</span></a>
          <a className="indent">♙ <span>Agente</span></a>
          <NavLink className="indent" to="/mensagem-direta">➤ <span>Mensagem direta</span></NavLink>
          <a className="indent">◎ <span>Estratégias</span></a>
          <p className="eyebrow">OPERAR</p>
          <a>◌ <span>Negociações</span></a>
          <NavLink to="/resultados">◔ <span>Resultados</span></NavLink>
        </nav>
        <div className="sidebar-footer">AG<br /><span>Administrador Gooroo</span></div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>Sales&nbsp;&nbsp;›&nbsp;&nbsp;<b>Mensagem direta</b></span>
          <div className="org-switcher">
            {import.meta.env.VITE_AUTH_ENABLED === "true" && <button className="company" onClick={() => { clearAccessToken(); window.location.reload(); }}>Sair</button>}
            <button className="company" onClick={() => setMenuOpen((open) => !open)}>
              ▦ Empresa&nbsp;&nbsp; <b>{currentOrganization?.name ?? "…"}</b> <span className="caret">⌄</span>
            </button>
            {menuOpen && (
              <div className="org-menu" onMouseLeave={() => { setMenuOpen(false); setCreating(false); }}>
                {organizations.map((org) => (
                  <button
                    key={org.id}
                    className={`org-menu-item ${org.id === organizationId ? "active" : ""}`}
                    onClick={() => { setOrganizationId(org.id); setMenuOpen(false); }}
                  >
                    {org.name}
                    {org.id === organizationId && <span className="check">✓</span>}
                  </button>
                ))}
                {isAdmin && <div className="org-menu-divider" />}
                {isAdmin && (creating ? (
                  <div className="org-menu-create">
                    <input
                      autoFocus
                      value={newOrgName}
                      placeholder="Nome da empresa"
                      onChange={(event) => setNewOrgName(event.target.value)}
                      onKeyDown={(event) => event.key === "Enter" && submitNewOrg()}
                    />
                    <button className="primary small" disabled={createOrgMutation.isPending} onClick={submitNewOrg}>Criar</button>
                  </div>
                ) : (
                  <button className="org-menu-item" onClick={() => setCreating(true)}>+ Nova empresa</button>
                ))}
                {isAdmin && <div className="org-menu-divider" />}
                {isAdmin && <button
                  className="org-menu-item"
                  onClick={() => { setConnectionOpen(true); setMenuOpen(false); }}
                  disabled={!organizationId}
                >
                  ⚙ Configurar conexão WABA
                </button>}
              </div>
            )}
          </div>
        </header>
        <main>{children}</main>
      </div>
      {connectionOpen && organizationId && (
        <WabaConnectionModal
          organizationId={organizationId}
          organizationName={currentOrganization?.name ?? ""}
          onClose={() => setConnectionOpen(false)}
        />
      )}
    </div>
  );
}
