export type TemplateCategory = "MARKETING" | "UTILITY";
export type TemplateStatus = "DRAFT" | "PENDING" | "APPROVED" | "REJECTED" | "PAUSED" | "DISABLED";

export interface TemplateComponent {
  type: string;
  format?: string;
  text?: string;
  buttons?: Array<{ type: string; text: string }>;
  example?: Record<string, string[][]>;
}

export interface MessageTemplate {
  id: string;
  meta_template_id: string | null;
  name: string;
  display_name: string;
  language: string;
  category: TemplateCategory;
  requested_category: TemplateCategory;
  correct_category: TemplateCategory | null;
  status: TemplateStatus;
  components: TemplateComponent[];
  variable_schema: Record<string, { alias: string; source: string; required: boolean }>;
  source: string;
  revision: number;
  parent_template_id: string | null;
  submission_attempt: number;
  category_changed_at: string | null;
  rejection_reason: string | null;
  submitted_at: string | null;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TemplatePreset {
  id: string;
  name: string;
  description: string;
  category: TemplateCategory;
  tags: string[];
  when_to_use: string;
  why_it_works: string;
  caution: string;
  suggested_rules: AudienceRules;
  components: TemplateComponent[];
  variable_schema: MessageTemplate["variable_schema"];
  estimated_reach: number;
}

export interface AudienceRules {
  eligible_not_closed: true;
  no_response_days: 7 | 90 | null;
  fewer_than_direct_messages: number | null;
}

export interface AudiencePreview {
  total_considered: number;
  eligible: number;
  suppressed: number;
  suppression_reasons: Record<string, number>;
  normalized_rules: AudienceRules;
}

export interface Campaign {
  id: string;
  name: string;
  product: string | null;
  template_id: string;
  audience_rules: AudienceRules;
  variable_mapping: Record<string, string>;
  status: string;
  scheduled_at: string | null;
  timezone: string;
  created_at: string;
}

export interface CampaignResults {
  campaign_id: string;
  campaign_status: string;
  total: number;
  by_status: Record<string, number>;
}

export interface Organization {
  id: string;
  name: string;
  timezone: string;
  created_at: string;
}

export type WabaConnectionStatus = "DISCONNECTED" | "CONNECTED" | "ERROR";

export interface WabaConnection {
  organization_id: string;
  business_id: string | null;
  waba_id: string | null;
  phone_number_id: string | null;
  channel_account_id: string | null;
  api_version: string;
  has_token: boolean;
  status: WabaConnectionStatus;
  last_synced_at: string | null;
  updated_at: string;
}

export interface WabaConnectionWrite {
  business_id: string | null;
  waba_id: string | null;
  phone_number_id: string | null;
  channel_account_id: string | null;
  api_version: string;
  access_token?: string | null;
}

export interface WabaConnectionTestResult {
  status: WabaConnectionStatus;
  detail: string;
}

export interface TemplateTestSendResult {
  accepted: boolean;
  delivery_id: string;
  wamid: string;
  consecutive_template_sends: number;
}
