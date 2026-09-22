# Contrato da fonte comercial

Com `AUDIENCE_MODE=http`, a API faz `GET` em `AUDIENCE_API_URL` com os query params
`organization_id` e `product`. Se `AUDIENCE_API_TOKEN` estiver definido, envia
`Authorization: Bearer <token>`.

A resposta pode ser uma lista ou `{ "items": [...] }`. Cada item usa o formato:

```json
{
  "id": "contact-123",
  "phone_e164": "+5511999999999",
  "first_name": "Ana",
  "product": "Crédito",
  "eligible": true,
  "deal_status": "open",
  "last_customer_reply_at": "2026-09-01T12:00:00Z",
  "direct_messages_90d": 1,
  "has_consent": true,
  "opted_out": false,
  "attributes": {}
}
```

Campos adicionais usados em templates devem vir em `attributes`. Por exemplo,
`"attributes": {"numero_contrato": "123"}` pode ser referenciado por
`contact.attributes.numero_contrato` no mapeamento da campanha.

`phone_e164`, consentimento e estado do negócio são revalidados imediatamente antes
do disparo. `direct_messages_90d` permanece disponível como dado comercial, mas não
é autoridade para frequência. O serviço mantém contador próprio e bloqueia o quarto
template consecutivo por empresa e telefone; qualquer mensagem recebida do usuário
zera esse contador. Opt-outs registrados localmente sempre prevalecem sobre a resposta
da fonte.
