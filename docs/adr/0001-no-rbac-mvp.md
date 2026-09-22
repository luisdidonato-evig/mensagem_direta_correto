# ADR 0001 — Sem RBAC no MVP

## Status
Superado por ADR 0005 (2026-09-21).

## Contexto
O objetivo do MVP é gerenciar e enviar templates para múltiplas empresas. Um
sistema de identidade/permissões completo (login, papéis viewer/operador/
administrador, integração com provedor de identidade — decisão pendente na
seção 15 do `PLANEJAMENTO.md`) é um projeto à parte.

## Decisão
Não implementar autenticação nem RBAC nesta fase. Qualquer pessoa com acesso
à UI ou à API enxerga e opera todas as organizações cadastradas.

## Consequências
- Nenhum endpoint valida "quem" está fazendo a chamada — `organization_id` é
  só um parâmetro de roteamento, não um limite de autorização.
- Auditoria (`audit_logs.actor`) sempre grava `"system"` como ator.
- Antes de qualquer ambiente com dado real de cliente, isso precisa ser
  resolvido — é o item de maior risco de segurança do projeto hoje.
