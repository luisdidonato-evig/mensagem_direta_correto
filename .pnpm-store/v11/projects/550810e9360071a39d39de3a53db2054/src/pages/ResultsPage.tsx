import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useOrganization } from "../state/organization";

const labels: Record<string, string> = {
  SELECTED: "Selecionados",
  SUPPRESSED: "Suprimidos",
  ACCEPTED: "Aceitos",
  SENT: "Enviados",
  DELIVERED: "Entregues",
  READ: "Lidos",
  REPLIED: "Responderam",
  FAILED: "Falharam",
  OPTED_OUT: "Opt-out"
};

export function ResultsPage() {
  const { organizationId } = useOrganization();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const campaigns = useQuery({
    queryKey: ["campaigns", organizationId],
    queryFn: () => api.listCampaigns(organizationId!),
    enabled: !!organizationId,
    refetchInterval: 5000
  });
  const selectedCampaign = campaigns.data?.find((campaign) => campaign.id === selectedId) ?? campaigns.data?.[0];
  const results = useQuery({
    queryKey: ["campaign-results", selectedCampaign?.id],
    queryFn: () => api.getCampaignResults(selectedCampaign!.id, organizationId!),
    enabled: Boolean(selectedCampaign),
    refetchInterval: (query) => {
      const status = query.state.data?.campaign_status;
      return status === "QUEUED" || status === "SENDING" || status === "SCHEDULED" ? 3000 : false;
    }
  });
  const cancelMutation = useMutation({
    mutationFn: () => api.cancelCampaign(selectedCampaign!.id, organizationId!),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["campaigns", organizationId] });
      await queryClient.invalidateQueries({ queryKey: ["campaign-results", selectedCampaign?.id] });
    }
  });

  useEffect(() => {
    if (!selectedId && campaigns.data?.[0]) setSelectedId(campaigns.data[0].id);
  }, [campaigns.data, selectedId]);

  return (
    <section className="page results-page">
      <p className="eyebrow blue">OPERAR</p>
      <h1>Resultados</h1>
      <p className="intro">Acompanhe processamento, entrega e resposta das mensagens diretas.</p>
      <div className="divider" />
      {(!organizationId || campaigns.isLoading) && <div className="empty">Carregando campanhas…</div>}
      {organizationId && !campaigns.isLoading && !campaigns.data?.length && <div className="empty"><h3>Nenhuma campanha executada.</h3><p>Crie uma mensagem direta para começar.</p></div>}
      {campaigns.data?.length ? <div className="results-layout">
        <aside className="campaign-list">
          <h2>Campanhas</h2>
          {campaigns.data.map((campaign) => <button key={campaign.id} className={campaign.id === selectedCampaign?.id ? "active" : ""} onClick={() => setSelectedId(campaign.id)}><span>{campaign.name}</span><small>{campaign.product ?? "Sem produto"} · {new Date(campaign.created_at).toLocaleDateString("pt-BR")}</small><b>{campaign.status}</b></button>)}
        </aside>
        <div className="result-detail">
          <div className="result-heading"><div><p className="eyebrow">CAMPANHA</p><h2>{selectedCampaign?.name}</h2><span className="muted">{selectedCampaign?.product} · {selectedCampaign?.timezone}</span></div><div><span className={`campaign-state ${(results.data?.campaign_status ?? selectedCampaign?.status ?? "DRAFT").toLowerCase()}`}>{results.data?.campaign_status ?? selectedCampaign?.status}</span>{["DRAFT", "VALIDATED", "SCHEDULED", "QUEUED"].includes(selectedCampaign?.status ?? "") && <button className="ghost" disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate()}>Cancelar campanha</button>}</div></div>
          {results.isLoading ? <div className="empty">Consolidando resultados…</div> : <>
            <div className="metric-grid"><div className="metric total"><span>Total processado</span><b>{results.data?.total ?? 0}</b></div>{Object.entries(labels).map(([key, label]) => <div className="metric" key={key}><span>{label}</span><b>{results.data?.by_status[key] ?? 0}</b></div>)}</div>
            <div className="result-note"><b>Atualização por webhook</b><p>Estados nunca regridem. Eventos duplicados são descartados pelo backend e campanhas em andamento são atualizadas automaticamente.</p></div>
          </>}
        </div>
      </div> : null}
    </section>
  );
}
