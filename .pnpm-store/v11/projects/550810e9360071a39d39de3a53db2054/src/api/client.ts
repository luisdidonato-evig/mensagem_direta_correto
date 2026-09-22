import type {
  AudiencePreview,
  AudienceRules,
  Campaign,
  CampaignResults,
  MessageTemplate,
  Organization,
  TemplatePreset,
  WabaConnection,
  WabaConnectionTestResult,
  WabaConnectionWrite
} from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";
const TOKEN_KEY = "evig.api-token";

export function getAccessToken(): string {
  return window.sessionStorage.getItem(TOKEN_KEY) ?? import.meta.env.VITE_API_TOKEN ?? "";
}

export function setAccessToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
      ...init?.headers
    }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Erro inesperado" }));
    const detail = Array.isArray(body.detail) ? body.detail.join("; ") : body.detail;
    throw new Error(detail || `Erro HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function withOrg(path: string, organizationId: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}organization_id=${encodeURIComponent(organizationId)}`;
}

export const api = {
  getSession: () => request<{ role: "ADMIN" | "OPERATOR" | "VIEWER"; organization_id: string | null }>("/auth/me"),
  listOrganizations: () => request<Organization[]>("/organizations"),
  createOrganization: (payload: { name: string; timezone?: string }) =>
    request<Organization>("/organizations", { method: "POST", body: JSON.stringify(payload) }),
  getWabaConnection: (organizationId: string) =>
    request<WabaConnection>(`/organizations/${organizationId}/waba-connection`),
  updateWabaConnection: (organizationId: string, payload: WabaConnectionWrite) =>
    request<WabaConnection>(`/organizations/${organizationId}/waba-connection`, {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  testWabaConnection: (organizationId: string) =>
    request<WabaConnectionTestResult>(`/organizations/${organizationId}/waba-connection/test`, {
      method: "POST"
    }),

  listTemplates: (organizationId: string) =>
    request<MessageTemplate[]>(withOrg("/templates", organizationId)),
  listPresets: () => request<TemplatePreset[]>("/templates/presets"),
  syncTemplates: (organizationId: string) =>
    request<{ created: number; updated: number }>(withOrg("/templates/sync", organizationId), {
      method: "POST"
    }),
  createDraftFromPreset: (preset: TemplatePreset, organizationId: string) =>
    request<MessageTemplate>(withOrg("/templates/drafts", organizationId), {
      method: "POST",
      body: JSON.stringify({
        name: `${preset.id}_${Date.now()}`,
        display_name: preset.name,
        language: "pt_BR",
        category: preset.category,
        components: preset.components,
        variable_schema: preset.variable_schema
      })
    }),
  createBlankDraft: (category: MessageTemplate["category"], organizationId: string) =>
    request<MessageTemplate>(withOrg("/templates/drafts", organizationId), {
      method: "POST",
      body: JSON.stringify({
        name: `novo_template_${Date.now()}`,
        display_name: "Novo template",
        language: "pt_BR",
        category,
        components: [{ type: "BODY", text: "" }],
        variable_schema: {}
      })
    }),
  updateDraft: (
    id: string,
    payload: { display_name: string; category: MessageTemplate["category"]; components: MessageTemplate["components"]; variable_schema: MessageTemplate["variable_schema"] },
    organizationId: string
  ) =>
    request<MessageTemplate>(withOrg(`/templates/${id}/draft`, organizationId), {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  submitTemplate: (id: string, organizationId: string) =>
    request<MessageTemplate>(withOrg(`/templates/${id}/submit`, organizationId), { method: "POST" }),
  deleteTemplate: (id: string, organizationId: string) => request<void>(withOrg(`/templates/${id}`, organizationId), { method: "DELETE" }),
  previewAudience: (product: string, category: MessageTemplate["category"], rules: AudienceRules, organizationId: string) =>
    request<AudiencePreview>(withOrg("/audiences/preview", organizationId), {
      method: "POST",
      body: JSON.stringify({ product, category, rules })
    }),
  createCampaign: (
    payload: {
      name: string;
      product: string;
      template_id: string;
      audience_rules: AudienceRules;
      variable_mapping?: Record<string, string>;
      scheduled_at?: string;
    },
    organizationId: string
  ) => request<Campaign>(withOrg("/campaigns", organizationId), { method: "POST", body: JSON.stringify(payload) }),
  listCampaigns: (organizationId: string) =>
    request<Campaign[]>(withOrg("/campaigns", organizationId)),
  getCampaignResults: (id: string, organizationId: string) => request<CampaignResults>(withOrg(`/campaigns/${id}/results`, organizationId)),
  validateCampaign: (id: string, organizationId: string) =>
    request<{ valid: boolean; errors: string[]; audience: AudiencePreview }>(withOrg(`/campaigns/${id}/validate`, organizationId), { method: "POST" }),
  sendCampaign: (id: string, organizationId: string) => request<Campaign>(withOrg(`/campaigns/${id}/send`, organizationId), { method: "POST" }),
  scheduleCampaign: (id: string, organizationId: string) => request<Campaign>(withOrg(`/campaigns/${id}/schedule`, organizationId), { method: "POST" })
  ,cancelCampaign: (id: string, organizationId: string) => request<Campaign>(withOrg(`/campaigns/${id}/cancel`, organizationId), { method: "POST" })
};
