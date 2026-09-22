import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { AudiencePreview, AudienceRules, MessageTemplate, TemplateComponent, TemplatePreset } from "../api/types";
import { PhonePreview } from "../components/PhonePreview";
import { TemplateCard } from "../components/TemplateCard";
import { useOrganization } from "../state/organization";

type Tab = "mine" | "presets";
type DraftEdit = { header: string; body: string; footer: string; buttons: string[] };

const BODY_LIMIT = 1024;
const FOOTER_LIMIT = 60;
const HEADER_LIMIT = 60;
const EDITABLE_STATUSES: MessageTemplate["status"][] = ["DRAFT", "REJECTED"];

const initialRules: AudienceRules = {
  eligible_not_closed: true,
  no_response_days: 7,
  fewer_than_direct_messages: 3
};

const AUDIENCE_RULE_LABELS: Record<string, string> = {
  no_response_days_7: "Parou no meio de uma simulação",
  no_response_days_90: "Sem contato na última semana",
  fewer_than_direct_messages: "Recebeu menos de 3 mensagens diretas"
};

function suggestedRuleLabels(rules: AudienceRules): string[] {
  const labels: string[] = [];
  if (rules.no_response_days === 7) labels.push(AUDIENCE_RULE_LABELS.no_response_days_7);
  if (rules.no_response_days === 90) labels.push(AUDIENCE_RULE_LABELS.no_response_days_90);
  if (rules.fewer_than_direct_messages != null) labels.push(AUDIENCE_RULE_LABELS.fewer_than_direct_messages);
  return labels;
}

function componentsToEdit(components: TemplateComponent[]): DraftEdit {
  return {
    header: components.find((item) => item.type.toUpperCase() === "HEADER")?.text ?? "",
    body: components.find((item) => item.type.toUpperCase() === "BODY")?.text ?? "",
    footer: components.find((item) => item.type.toUpperCase() === "FOOTER")?.text ?? "",
    buttons: (components.find((item) => item.type.toUpperCase() === "BUTTONS")?.buttons ?? []).map((button) => button.text)
  };
}

function editToComponents(edit: DraftEdit): TemplateComponent[] {
  const components: TemplateComponent[] = [];
  if (edit.header.trim()) components.push({ type: "HEADER", format: "TEXT", text: edit.header.trim() });
  components.push({ type: "BODY", text: edit.body });
  if (edit.footer.trim()) components.push({ type: "FOOTER", text: edit.footer.trim() });
  const buttons = edit.buttons.map((text) => text.trim()).filter(Boolean);
  if (buttons.length) components.push({ type: "BUTTONS", buttons: buttons.map((text) => ({ type: "QUICK_REPLY", text })) });
  return components;
}

function deriveVariableSchema(
  edit: DraftEdit,
  existing: MessageTemplate["variable_schema"]
): MessageTemplate["variable_schema"] {
  const aliases = Array.from(edit.body.matchAll(/{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}/g)).map((match) => match[1]);
  const uniqueAliases = Array.from(new Set(aliases));
  const previousByAlias = Object.values(existing).reduce<Record<string, MessageTemplate["variable_schema"][string]>>((result, definition) => {
    result[definition.alias] = definition;
    return result;
  }, {});
  return Object.fromEntries(uniqueAliases.map((alias, index) => [String(index + 1), previousByAlias[alias] ?? {
    alias,
    source: alias === "nome" ? "contact.first_name" : alias === "produto" ? "deal.product_name" : `contact.attributes.${alias}`,
    required: true
  }]));
}

export function DirectMessagesPage() {
  const client = useQueryClient();
  const { organizationId } = useOrganization();
  const [tab, setTab] = useState<Tab>("mine");
  const [categoryFilter, setCategoryFilter] = useState<"ALL" | "UTILITY" | "MARKETING">("ALL");
  const [tagFilter, setTagFilter] = useState("ALL");
  const [previewItem, setPreviewItem] = useState<MessageTemplate | TemplatePreset | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<MessageTemplate | null>(null);
  const [wizardStep, setWizardStep] = useState<1 | 2>(1);
  const [campaignName, setCampaignName] = useState("Mensagem direta");
  const [product, setProduct] = useState("Crédito");
  const [rules, setRules] = useState<AudienceRules>(initialRules);
  const [audience, setAudience] = useState<AudiencePreview | null>(null);
  const [sendMode, setSendMode] = useState<"now" | "scheduled">("now");
  const [scheduledAt, setScheduledAt] = useState("");
  const [variableMapping, setVariableMapping] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [draftEdit, setDraftEdit] = useState<DraftEdit | null>(null);

  const templatesQuery = useQuery({
    queryKey: ["templates", organizationId],
    queryFn: () => api.listTemplates(organizationId!),
    enabled: !!organizationId
  });
  const presetsQuery = useQuery({ queryKey: ["presets"], queryFn: api.listPresets });

  const isEditable = !!selectedTemplate && EDITABLE_STATUSES.includes(selectedTemplate.status);

  useEffect(() => {
    if (selectedTemplate && EDITABLE_STATUSES.includes(selectedTemplate.status)) {
      setDraftEdit(componentsToEdit(selectedTemplate.components));
    } else {
      setDraftEdit(null);
    }
    if (selectedTemplate) {
      setVariableMapping(Object.fromEntries(Object.values(selectedTemplate.variable_schema).map((definition) => [definition.alias, definition.source])));
    }
  }, [selectedTemplate]);

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteTemplate(id, organizationId!),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["templates"] });
      setNotice("Template excluído.");
    },
    onError: (error) => setNotice(error.message)
  });

  const syncMutation = useMutation({
    mutationFn: () => api.syncTemplates(organizationId!),
    onSuccess: async (result) => {
      await client.invalidateQueries({ queryKey: ["templates"] });
      setNotice(`Sincronização concluída: ${result.created} criado(s), ${result.updated} atualizado(s).`);
    },
    onError: (error) => setNotice(error.message)
  });

  const presetMutation = useMutation({
    mutationFn: (preset: TemplatePreset) => api.createDraftFromPreset(preset, organizationId!),
    onSuccess: async (template, preset) => {
      await client.invalidateQueries({ queryKey: ["templates"] });
      setPreviewItem(null);
      setSelectedTemplate(template);
      setRules(preset.suggested_rules);
      setWizardStep(1);
      setAudience(null);
    },
    onError: (error) => setNotice(error.message)
  });

  const blankDraftMutation = useMutation({
    mutationFn: () => api.createBlankDraft("UTILITY", organizationId!),
    onSuccess: async (template) => {
      await client.invalidateQueries({ queryKey: ["templates"] });
      setSelectedTemplate(template);
      setRules(initialRules);
      setWizardStep(1);
      setAudience(null);
    },
    onError: (error) => setNotice(error.message)
  });

  const previewMutation = useMutation({
    mutationFn: () => api.previewAudience(product, selectedTemplate!.category, rules, organizationId!),
    onSuccess: (result) => {
      setAudience(result);
      setWizardStep(2);
    },
    onError: (error) => setNotice(error.message)
  });

  const saveDraftMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTemplate || !draftEdit) throw new Error("Nada para salvar");
      return api.updateDraft(selectedTemplate.id, {
        display_name: selectedTemplate.display_name,
        category: selectedTemplate.category,
        components: editToComponents(draftEdit),
        variable_schema: deriveVariableSchema(draftEdit, selectedTemplate.variable_schema)
      }, organizationId!);
    },
    onSuccess: async (template) => {
      await client.invalidateQueries({ queryKey: ["templates"] });
      setSelectedTemplate(template);
      setNotice("Rascunho salvo.");
    },
    onError: (error) => setNotice(error.message)
  });

  const submitMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTemplate || !draftEdit) throw new Error("Nada para enviar");
      const saved = await api.updateDraft(selectedTemplate.id, {
        display_name: selectedTemplate.display_name,
        category: selectedTemplate.category,
        components: editToComponents(draftEdit),
        variable_schema: deriveVariableSchema(draftEdit, selectedTemplate.variable_schema)
      }, organizationId!);
      return api.submitTemplate(saved.id, organizationId!);
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["templates"] });
      setNotice("Template enviado para aprovação. Ele poderá ser usado quando a Meta retornar APPROVED.");
      setSelectedTemplate(null);
      setWizardStep(1);
      setAudience(null);
    },
    onError: (error) => setNotice(error.message)
  });

  const sendMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTemplate) throw new Error("Selecione um template aprovado");
      const campaign = await api.createCampaign(
        {
          name: campaignName,
          product,
          template_id: selectedTemplate.id,
          audience_rules: rules,
          variable_mapping: variableMapping,
          ...(sendMode === "scheduled" && scheduledAt
            ? { scheduled_at: new Date(scheduledAt).toISOString() }
            : {})
        },
        organizationId!
      );
      const validation = await api.validateCampaign(campaign.id, organizationId!);
      if (!validation.valid) throw new Error(validation.errors.join("; "));
      return sendMode === "scheduled"
        ? api.scheduleCampaign(campaign.id, organizationId!)
        : api.sendCampaign(campaign.id, organizationId!);
    },
    onSuccess: (campaign) => {
      setNotice(sendMode === "scheduled" ? `Campanha agendada com estado ${campaign.status}.` : `Campanha enviada para processamento com estado ${campaign.status}.`);
      setSelectedTemplate(null);
      setWizardStep(1);
      setAudience(null);
    },
    onError: (error) => setNotice(error.message)
  });

  const presetTags = useMemo(() => {
    const all = (presetsQuery.data ?? []).flatMap((preset) => preset.tags);
    return Array.from(new Set(all));
  }, [presetsQuery.data]);

  const items = useMemo(() => {
    if (tab === "mine") {
      const values = templatesQuery.data ?? [];
      return categoryFilter === "ALL" ? values : values.filter((item) => item.category === categoryFilter);
    }
    const values = presetsQuery.data ?? [];
    return tagFilter === "ALL" ? values : values.filter((item) => item.tags.includes(tagFilter));
  }, [categoryFilter, tagFilter, presetsQuery.data, tab, templatesQuery.data]);

  function deleteItem(item: MessageTemplate) {
    if (!window.confirm(`Excluir "${item.display_name}"? Essa ação não pode ser desfeita.`)) return;
    deleteMutation.mutate(item.id);
  }

  function openWizardFor(item: MessageTemplate) {
    setSelectedTemplate(item);
    setWizardStep(1);
    setAudience(null);
  }

  function useItem(item: MessageTemplate | TemplatePreset) {
    if (!("status" in item)) {
      presetMutation.mutate(item);
      return;
    }
    if (item.status === "PENDING") {
      setPreviewItem(item);
      setNotice("Este template está aguardando aprovação da Meta.");
      return;
    }
    if (item.status === "PAUSED" || item.status === "DISABLED") {
      setPreviewItem(item);
      setNotice(`Este template está ${item.status} e não pode ser usado.`);
      return;
    }
    openWizardFor(item);
  }

  if (!organizationId) {
    return (
      <section className="page">
        <div className="empty">Carregando organização…</div>
      </section>
    );
  }

  if (selectedTemplate) {
    const status = selectedTemplate.status;
    const bodyLen = draftEdit?.body.length ?? 0;
    const footerLen = draftEdit?.footer.length ?? 0;
    const previewComponents = isEditable && draftEdit ? editToComponents(draftEdit) : selectedTemplate.components;
    const canSubmit = isEditable && !!draftEdit && draftEdit.body.trim().length > 0;

    return (
      <section className="page wizard-page">
        <button className="back" onClick={() => setSelectedTemplate(null)}>← VOLTAR PARA MENSAGENS</button>
        <p className="eyebrow blue">AGENTE</p>
        <h1>Mensagem direta</h1>
        <p className="intro">Escolha com quem falar, quando, o que dizer e quem continua depois da resposta.</p>
        <div className="stepper">
          <button className={wizardStep === 1 ? "active" : "done"} onClick={() => setWizardStep(1)}><span>1</span> Público e momento</button>
          <button className={wizardStep === 2 ? "active" : ""} onClick={() => setWizardStep(2)}><span>2</span> Mensagem</button>
        </div>

        <div className="wizard-grid">
          <div className="wizard-card">
            {wizardStep === 1 ? (
              <>
                <div className="wizard-heading"><div><h2>◎ &nbsp; Público e momento</h2><p>Recorte quem recebe e defina quando a conversa começa.</p></div>{audience && <div className="count"><b>{audience.eligible}</b><small>pessoas elegíveis</small></div>}</div>
                <label>Nome da mensagem<input value={campaignName} onChange={(event) => setCampaignName(event.target.value)} /></label>
                <label>Produto da conversa<input value={product} onChange={(event) => setProduct(event.target.value)} /></label>
                <fieldset><legend>Quem recebe</legend>
                  <label className="check"><input type="checkbox" checked disabled /> Elegível e não fechou</label>
                  <label className="check"><input type="checkbox" checked={rules.no_response_days === 7} onChange={(event) => setRules({ ...rules, no_response_days: event.target.checked ? 7 : null })} /> 1 semana sem resposta</label>
                  <label className="check"><input type="checkbox" checked={rules.no_response_days === 90} onChange={(event) => setRules({ ...rules, no_response_days: event.target.checked ? 90 : null })} /> 90 dias sem resposta</label>
                  <label className="check"><input type="checkbox" checked={rules.fewer_than_direct_messages === 3} onChange={(event) => setRules({ ...rules, fewer_than_direct_messages: event.target.checked ? 3 : null })} /> Recebeu menos de 3 mensagens diretas</label>
                </fieldset>
                <fieldset><legend>Quando enviar</legend>
                  <div className="segmented">
                    <button type="button" className={sendMode === "now" ? "selected" : ""} onClick={() => setSendMode("now")}>Enviar agora</button>
                    <button type="button" className={sendMode === "scheduled" ? "selected" : ""} onClick={() => setSendMode("scheduled")}>Agendar</button>
                  </div>
                  {sendMode === "scheduled" && <label>Data e hora<input type="datetime-local" value={scheduledAt} min={new Date(Date.now() + 300000).toISOString().slice(0, 16)} onChange={(event) => setScheduledAt(event.target.value)} /></label>}
                </fieldset>
              </>
            ) : isEditable && draftEdit ? (
              <>
                <div className="wizard-heading"><div><h2>▢ &nbsp; O que ele diz</h2><p>Curto, com um motivo claro e um convite. {"{{nome}}"} e {"{{produto}}"} são preenchidos no envio.</p></div></div>
                <label>Imagem de capa<span className="field-hint">Upload de mídia ainda não disponível nesta versão.</span>
                  <button type="button" className="add-button" disabled>+ Adicionar imagem</button>
                </label>
                <label>Título<span className="field-hint">Opcional. Uma linha acima do texto.</span>
                  <input value={draftEdit.header} maxLength={HEADER_LIMIT} onChange={(event) => setDraftEdit({ ...draftEdit, header: event.target.value })} />
                </label>
                <label>Texto da mensagem<span className="field-counter">{bodyLen}/{BODY_LIMIT}</span>
                  <textarea rows={5} value={draftEdit.body} maxLength={BODY_LIMIT} onChange={(event) => setDraftEdit({ ...draftEdit, body: event.target.value })} />
                </label>
                <label>Rodapé<span className="field-counter">{footerLen}/{FOOTER_LIMIT}</span>
                  <input value={draftEdit.footer} maxLength={FOOTER_LIMIT} onChange={(event) => setDraftEdit({ ...draftEdit, footer: event.target.value })} />
                  <span className="field-hint">Aparece pequeno no fim da mensagem.</span>
                </label>
                <label>Botões de resposta
                  <div className="button-list">
                    {draftEdit.buttons.map((text, index) => (
                      <div className="button-row" key={index}>
                        <input value={text} onChange={(event) => {
                          const buttons = [...draftEdit.buttons];
                          buttons[index] = event.target.value;
                          setDraftEdit({ ...draftEdit, buttons });
                        }} />
                        <button type="button" onClick={() => setDraftEdit({ ...draftEdit, buttons: draftEdit.buttons.filter((_, i) => i !== index) })}>🗑</button>
                      </div>
                    ))}
                    {draftEdit.buttons.length < 3 && (
                      <button type="button" className="add-button" onClick={() => setDraftEdit({ ...draftEdit, buttons: [...draftEdit.buttons, ""] })}>+ Adicionar botão</button>
                    )}
                  </div>
                </label>
                {status === "REJECTED" && selectedTemplate.rejection_reason && (
                  <div className="approval-note" style={{ color: "#ff9b9b", background: "#3d2023" }}>✕ Rejeitado pela Meta: {selectedTemplate.rejection_reason}</div>
                )}
              </>
            ) : (
              <>
                <div className="wizard-heading"><div><h2>▢ &nbsp; O que ele diz</h2><p>Conteúdo aprovado pela Meta. Variáveis são preenchidas no envio.</p></div></div>
                <label>Template aprovado<input value={selectedTemplate.display_name} disabled /></label>
                {selectedTemplate.components.map((component, index) => component.text && <label key={`${component.type}-${index}`}>{component.type}<textarea value={component.text} disabled rows={component.type === "BODY" ? 6 : 2} /></label>)}
                {Object.values(selectedTemplate.variable_schema).length > 0 && <fieldset><legend>Fontes das variáveis</legend>
                  {Object.values(selectedTemplate.variable_schema).map((definition) => <label key={definition.alias}>{`{{${definition.alias}}}`}
                    <input value={variableMapping[definition.alias] ?? definition.source} onChange={(event) => setVariableMapping({ ...variableMapping, [definition.alias]: event.target.value })} />
                    <span className="field-hint">Ex.: contact.first_name, deal.product_name ou contact.attributes.campo</span>
                  </label>)}
                </fieldset>}
                <div className="approval-note">✓ Template {selectedTemplate.status} · revisão {selectedTemplate.revision} · {selectedTemplate.language}</div>
              </>
            )}
          </div>
          <div><PhonePreview components={previewComponents} />{audience && <div className="summary"><div><small>PÚBLICO</small><b>{audience.eligible}</b></div><div><small>MOMENTO</small><b>{sendMode === "scheduled" ? "Agendado" : "Agora"}</b></div><div><small>PRODUTO</small><b>{product}</b></div><div><small>CONTINUA COM</small><b>Agente</b></div></div>}</div>
        </div>
        <div className="wizard-actions">
          <span><b>Tudo pronto para conversar.</b> Etapa {wizardStep} de 2</span>
          <div>
            <button className="ghost" onClick={() => setSelectedTemplate(null)}>Cancelar</button>
            {wizardStep === 1 ? (
              <button className="primary" disabled={previewMutation.isPending} onClick={() => previewMutation.mutate()}>{previewMutation.isPending ? "Calculando…" : "Continuar"}</button>
            ) : isEditable ? (
              <>
                <button className="ghost" disabled={saveDraftMutation.isPending} onClick={() => saveDraftMutation.mutate()}>{saveDraftMutation.isPending ? "Salvando…" : "Salvar rascunho"}</button>
                <button className="primary" disabled={!canSubmit || submitMutation.isPending} onClick={() => submitMutation.mutate()}>
                  {submitMutation.isPending ? "Enviando…" : status === "REJECTED" ? "Corrigir e reenviar →" : "Enviar para aprovação →"}
                </button>
              </>
            ) : (
              <button className="primary" disabled={sendMutation.isPending || (sendMode === "scheduled" && !scheduledAt)} onClick={() => sendMutation.mutate()}>{sendMutation.isPending ? "Processando…" : sendMode === "scheduled" ? "◷ Agendar mensagem" : "➤ Enviar mensagem"}</button>
            )}
          </div>
        </div>
        {notice && <Toast message={notice} onClose={() => setNotice(null)} />}
      </section>
    );
  }

  return (
    <section className="page">
      <button className="back">← VOLTAR PARA O AGENTE</button>
      <p className="eyebrow blue">AGENTE</p>
      <h1>Mensagem direta</h1>
      <p className="intro">Aqui o agente começa a conversa. Escolha com quem falar, quando, o que dizer e quem continua depois da resposta.</p>
      <div className="divider" />
      <div className="catalog-toolbar">
        <div className="tabs"><button className={tab === "mine" ? "active" : ""} onClick={() => setTab("mine")}>Minhas mensagens</button><button className={tab === "presets" ? "active" : ""} onClick={() => setTab("presets")}>Modelos prontos</button></div>
        <div className="toolbar-actions">
          <button className="ghost" disabled={blankDraftMutation.isPending} onClick={() => blankDraftMutation.mutate()}>{blankDraftMutation.isPending ? "Criando…" : "+ Novo template"}</button>
          <button className="ghost sync" disabled={syncMutation.isPending} onClick={() => syncMutation.mutate()}>{syncMutation.isPending ? "Sincronizando…" : "↻ Sincronizar Meta"}</button>
        </div>
      </div>
      <h2>{tab === "mine" ? "Templates da sua WABA" : "Modelos prontos para crédito"}</h2>
      <p className="muted">{tab === "mine" ? "Templates locais e sincronizados com a Meta." : "Cada modelo já vem com texto, botões e o recorte de público que combina com ele."}</p>
      {tab === "mine" ? (
        <div className="filters"><button className={categoryFilter === "ALL" ? "active" : ""} onClick={() => setCategoryFilter("ALL")}>Todos</button><button className={categoryFilter === "UTILITY" ? "active" : ""} onClick={() => setCategoryFilter("UTILITY")}>Utilidade</button><button className={categoryFilter === "MARKETING" ? "active" : ""} onClick={() => setCategoryFilter("MARKETING")}>Marketing</button></div>
      ) : (
        <div className="filters">
          <button className={tagFilter === "ALL" ? "active" : ""} onClick={() => setTagFilter("ALL")}>Todos</button>
          {presetTags.map((tag) => <button key={tag} className={tagFilter === tag ? "active" : ""} onClick={() => setTagFilter(tag)}>{tag[0].toUpperCase() + tag.slice(1)}</button>)}
        </div>
      )}
      {(templatesQuery.isLoading || presetsQuery.isLoading) && <div className="empty">Carregando mensagens…</div>}
      {items.length === 0 && !templatesQuery.isLoading && <div className="empty"><h3>Nenhum template por aqui.</h3><p>Sincronize com a Meta ou use um modelo pronto.</p></div>}
      <div className="cards">{items.map((item) => <TemplateCard key={item.id} item={item} onView={() => setPreviewItem(item)} onUse={() => useItem(item)} onDelete={tab === "mine" ? () => deleteItem(item as MessageTemplate) : undefined} />)}</div>
      {previewItem && <PreviewModal item={previewItem} onClose={() => setPreviewItem(null)} onUse={() => useItem(previewItem)} />}
      {notice && <Toast message={notice} onClose={() => setNotice(null)} />}
    </section>
  );
}

function PreviewModal({ item, onClose, onUse }: { item: MessageTemplate | TemplatePreset; onClose: () => void; onUse: () => void }) {
  const isTemplate = "status" in item;
  const canUse = !isTemplate || (item.status !== "PENDING" && item.status !== "PAUSED" && item.status !== "DISABLED");
  const preset = !isTemplate ? (item as TemplatePreset) : null;
  const actionLabel = !isTemplate
    ? "Usar este modelo →"
    : item.status === "APPROVED"
      ? "Usar este template →"
      : item.status === "PENDING"
        ? "Aguardando aprovação"
        : "Editar e enviar →";
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        <div className="modal-title">
          <span className={`category ${item.category.toLowerCase()}`}>{item.category === "UTILITY" ? "UTILIDADE" : "MARKETING"}</span>
          <h2>{"display_name" in item ? item.display_name : item.name}</h2>
          {"description" in item && <p>{item.description}</p>}
          {preset && <p><b>Quando usar:</b> {preset.when_to_use}</p>}
        </div>
        <div className="modal-content">
          <PhonePreview components={item.components} />
          <div className="why">
            <div><h3>⌁ POR QUE FUNCIONA</h3><p>{preset ? preset.why_it_works : "Retoma o contexto com uma mensagem curta, motivo claro e convite explícito."}</p></div>
            <div><h3>◷ CUIDADO</h3><p>{preset ? preset.caution : "Use apenas para contatos com consentimento e respeite imediatamente o opt-out."}</p></div>
            {preset && (
              <div className="suggested-audience">
                <h3>PÚBLICO SUGERIDO</h3>
                <div className="pill-row">{suggestedRuleLabels(preset.suggested_rules).map((label) => <span key={label} className="pill">✓ {label}</span>)}</div>
              </div>
            )}
            {preset && <div className="reach-line">⚙ Alcance estimado <b>{preset.estimated_reach.toLocaleString("pt-BR")}</b></div>}
          </div>
        </div>
        <footer>
          <span className="muted">{isTemplate ? `Estado: ${item.status}` : "Modelo local"}</span>
          <div>
            <button className="ghost" onClick={onClose}>Fechar</button>
            <button className="primary" disabled={!canUse} onClick={onUse}>{actionLabel}</button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  return <div className="toast">{message}<button onClick={onClose}>×</button></div>;
}
