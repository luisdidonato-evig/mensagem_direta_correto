# ADR 0005 — RBAC com tokens estáticos no MVP

## Status
Aceito (2026-09-21).

## Contexto
O serviço precisa impedir acesso cruzado entre empresas antes de operar dados reais,
mas a escolha do provedor de identidade corporativo ainda não foi feita.

## Decisão
Quando `AUTH_ENABLED=true`, toda rota de negócio exige Bearer token configurado em
`AUTH_TOKENS`. Cada token recebe um papel (`VIEWER`, `OPERATOR` ou `ADMIN`) e uma
organização; somente o administrador global usa `*`.

Webhooks da Meta continuam autenticados pela assinatura `X-Hub-Signature-256`.

## Consequências
- o MVP já aplica autorização e isolamento por empresa;
- os tokens devem ser injetados como segredo e rotacionados;
- SSO/OIDC, identidade individual e lifecycle de usuários continuam sendo evolução
  pós-MVP, sem exigir mudança no domínio de autorização.
