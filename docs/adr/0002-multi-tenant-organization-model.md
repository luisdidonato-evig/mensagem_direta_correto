# ADR 0002 — Multi-tenant via `organization_id`, sem isolamento de banco

## Status
Histórico (2026-09-21). A decisão atual sobre webhook e envio está em
[`../arquitetura-mensagem-direta.md`](../arquitetura-mensagem-direta.md).

## Contexto
O produto passou de single-tenant (uma WABA fixa via `.env`) para gerenciar
templates e campanhas de várias empresas. Cada empresa tem sua própria
conexão WABA (token, WABA ID, phone number ID).

## Decisão
- `organizations` + `waba_connections` (1:1) guardam a identidade e a conexão
  Meta de cada empresa.
- `message_templates` e `campaigns` ganharam `organization_id` (FK,
  obrigatório). Isolamento é por filtro de query (`WHERE organization_id = ?`),
  não por schema/banco separado por tenant.
- O provider da Meta (`WhatsAppProvider`) é reconstruído por conexão a cada
  operação (`build_provider_for_connection`), nunca reaproveitado como
  singleton global — cada chamada usa o token/WABA certo da organização.
- Endpoints que criam recurso (`POST /templates/drafts`, `POST /campaigns`)
  recebem `organization_id` via query param, com fallback pra organização
  "default" quando omitido (mantém scripts/testes antigos funcionando).
  Endpoints que agem sobre um recurso existente (`submit`, `delete`, `send`)
  derivam a organização do próprio recurso, nunca do query param — evita
  usar a conexão errada se o cliente mandar um `organization_id`
  desatualizado.

## Consequências
- Sem RBAC (ADR 0001), o isolamento por `organization_id` é só uma barreira
  de dados, não de acesso — qualquer chamador pode enxergar qualquer empresa
  trocando o parâmetro.
- Webhooks da Meta (`message_template_status_update`, `messages`) continuam
  resolvendo o registro certo via `meta_template_id`/`wamid`, que já são
  globalmente únicos — não precisaram de `organization_id` explícito.
- Multi-app-por-empresa na Meta (Business Manager diferente por cliente) não
  é suportado — a verificação de assinatura do webhook (`X-Hub-Signature-256`)
  ainda usa um único `META_APP_SECRET` global. Funciona bem quando todas as
  WABAs estão sob o mesmo App da Meta (padrão comum); precisaria de mais
  trabalho se cada empresa tiver App próprio.
