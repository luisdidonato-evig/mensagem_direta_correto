# Mensagem Direta: templates e envio

## Arquitetura anterior

`WhatsAppProvider` misturava gestão Graph API com envio. Campanhas podiam enviar direto pela Meta quando o gateway não estava configurado. `GATEWAY_CHANNEL_ACCOUNT_ID` global identificava a conta de canal de todas as empresas. `/api/v1/webhooks/meta` processava status de template, entrega e entrada. O gateway já oferecia `POST /internal/v1/messages`, mas a resposta era tratada como possível `wamid`.

## Arquitetura nova

Mensagem Direta mantém drafts, revisões, templates, públicos, campanhas e destinatários. `TemplateManagementProvider` tem implementação `MetaTemplateManagementProvider` para operações de administração pela Graph API. `TemplateDispatchProvider` tem implementação `MiddlewareTemplateDispatchProvider` e é o único caminho de envio. Não há fallback de envio direto à Meta.

## TemplateManagementProvider

Lista, cria e exclui templates pelo WABA configurado para a empresa. A edição local altera draft ou cria revisão; a submissão chama `POST /{waba_id}/message_templates`. A credencial da Meta fica cifrada em `waba_connections.access_token`, obtida somente pelo builder do provider; a chave deriva do segredo da aplicação. Substituir por KMS/secret manager é trabalho futuro.

## TemplateDispatchProvider

Envia somente por `POST /internal/v1/messages` no middleware, com `X-Internal-Key`. Corpo: `tenant_id` UUID da organização, `channel_account_id` UUID persistido nessa organização, `recipient_id`, `message.kind=template`, `message.template_key`, `message.parameters`, `idempotency_key` e `source=mensagem_direta`. Gateway responde `202 {"status":"queued","delivery_id":"..."}`. `ACCEPTED` indica enfileiramento, não envio, entrega ou leitura. Campo histórico `wamid` do destinatário armazena atualmente esse `delivery_id`; sem migração destrutiva. Resposta de envio de teste expõe `delivery_id` e mantém `wamid` como alias legado.

## Fluxo de criação

Draft é local e segregado por `organization_id`. Nome, idioma, categoria, componentes, variáveis e revisão ficam em `message_templates`.

## Fluxo de submissão

Submissão usa credencial e WABA da organização na Graph API. Persiste ID externo, status devolvido, categoria e `submitted_at`. Não supõe aprovação.

## Fluxo de sincronização

`POST /api/v1/templates/sync?organization_id=...` força leitura Graph API. `scheduler.sync_all_organizations` sincroniza a cada 30 minutos quando Celery beat está ativo. A comparação usa ID externo e tenta correlacionar submissões locais ainda sem ID por nome e idioma. Atualiza status, categoria, ID externo, motivo de rejeição e `last_synced_at`. Estados conhecidos: `PENDING`, `APPROVED`, `REJECTED`, `PAUSED`, `DISABLED`. A leitura normal usa dados persistidos; evita chamada Graph API em cada página. Eventos remotos sem campos essenciais são ignorados, e falhas HTTP preservam estado local para próxima tentativa. Entre sincronizações, a aprovação local pode estar desatualizada; o gateway pode aceitar na fila um template que a Meta pausou depois.

## Fluxo de envio

Campanha valida template aprovado, resolve organização e conta de canal, monta parâmetros e usa chave estável derivada do ID da campanha e hash do ID externo do contato. A chave sobrevive a rollback local após aceite do gateway. Destinatário vira `ACCEPTED` após `202 queued`. Teste usa mesmo provider e exige `Idempotency-Key`; a interface gera chave nova por envio intencional, e o cliente pode repetir a mesma chave para retentar. Não há evidência local para `SENT`, `DELIVERED` ou `READ` após desativar webhook.

## Configuração por tenant

`organizations.id` é identificador externo `tenant_id` para gateway. Empresas reais precisam UUID, pois middleware valida UUID; registro legado `default` serve apenas desenvolvimento e não pode enviar pelo middleware. `waba_connections` contém `channel_account_id`, `waba_id`, `business_id`, `phone_number_id` e token cifrado por organização. Tela **Conexão WABA** configura conta de canal. `GATEWAY_URL` e `GATEWAY_INTERNAL_KEY` são configuração do serviço, não da conta. Configuração ausente bloqueia envio. Migração `20260924_0011` acrescenta campos sem apagar dados.

## Dependências da Meta

Somente gestão de templates e sincronização. Requer WABA ID e token da organização em modo live. Nenhum envio usa Graph API diretamente.

## Dependências do middleware

Contrato auditado em `golang-gateway/src/httpapi/messages.go`, `src/channel/outbound.go` e `docs/internal-messages.md`. Gateway resolve `channel_account_id` para tenant e rejeita divergência com `tenant_id`; enfileira envio com chave de idempotência. Renderer atual aceita `parameters` para corpo e usa `pt_BR` fixo. Mensagem Direta bloqueia envio com outro idioma para evitar troca silenciosa. `template_parameters` e `template_language` não são campos consumidos pelo `OutboundMessage` atual, portanto não são enviados como contrato útil.

## Webhook

**Meta webhook pertence ao middleware.** Mensagem Direta não registra `/api/v1/webhooks/meta` no roteador. Código antigo permanece no arquivo `webhooks.py` somente como referência legada inativa; não configurar callback Meta para este serviço. Entrada, status de entrega e resposta do cliente ficam no runtime do middleware. O contador de frequência de campanha pode ser zerado quando a fonte comercial confiável informa `last_customer_reply_at` posterior ao último envio conhecido; envio de teste não dispõe dessa evidência.

## Gaps futuros

- Middleware precisa expor idioma variável para templates além de `pt_BR`.
- Middleware precisa preservar ordem de mais de nove parâmetros posicionais e receber mídia de cabeçalho e parâmetros dinâmicos além de BODY; até lá, esses templates são bloqueados na validação de campanha e no envio de teste.
- Middleware precisa repassar estados de entrega, leitura, resposta e opt-out com identidade do tenant e ID correlacionável; até lá, campanha mostra apenas aceite de fila.
- Integração de retorno de mensagens precisa substituir lógica antiga de webhook para atualizar frequência, compliance, handoff e estados de destinatário em tempo real. Até lá, respostas e `SAIR` não geram atualização local automática.
- Gestão completa de templates pelo middleware pode substituir acesso direto Graph API no futuro.
- Categoria `AUTHENTICATION` e estados novos da Meta ainda não pertencem ao modelo local; sincronização registra inconsistência e ignora esses itens até migração explícita de schema e interface.
- Migração operacional de organizações legadas com ID `default` para UUID requer mapeamento explícito da conta no gateway.
