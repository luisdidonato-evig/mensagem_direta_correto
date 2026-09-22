# ADR 0003 — Idempotency-Key, retry e circuit breaker

## Status
Aceito (2026-09-21).

## Contexto
`PLANEJAMENTO.md` §8 exige `Idempotency-Key` em toda criação/disparo; §10 e
§11 exigem retry só para falha transitória (nunca repetir erro permanente) e
circuit breaker pra Meta. Nenhum dos três existia.

## Decisão

**Idempotency-Key** — tabela `idempotency_records` (chave = `scope:namespace:
key`). Endpoints que criam ou disparam (`POST /templates/drafts`,
`POST /templates/{id}/submit`, `POST /campaigns`, `POST /campaigns/{id}/send`)
aceitam o header; se a mesma chave repetir, devolve a resposta gravada sem
re-executar o handler. O header é opcional — sem ele, cada chamada roda
normal. A checagem de idempotência acontece *antes* de qualquer guarda de
estado (ex.: "template já submetido"), pra um replay legítimo não bater em
409 só porque o primeiro request já mudou o estado do recurso.

**Retry** — `MetaProviderError.transient` já existia mas não era usado.
Agora: erro transitório em `campaign_dispatcher` incrementa
`CampaignRecipient.retry_count` e deixa o destinatário pendente (sem marcar
`FAILED`) até `MAX_SEND_RETRIES` (5); erro permanente falha na hora, sem
retry. A campanha fica em `SENDING` enquanto houver pendência transitória;
a task Celery (`campaign.dispatch`) detecta isso e se re-agenda sozinha com
`retry_backoff` + `retry_jitter` nativos do Celery.

**Circuit breaker** — `CircuitBreaker` em memória, por `organization_id`:
abre depois de 5 falhas transitórias seguidas, fica fechado (sem bater na
Meta) por 60s, fecha de novo no primeiro sucesso.

## Consequências
- Breaker é por processo — um deploy com múltiplos workers Celery tem um
  breaker por worker, não um estado compartilhado. Suficiente pra parar um
  loop batendo numa Meta fora do ar; não é rate limit global de verdade.
  Isso precisaria de estado em Redis pra ficar correto entre workers.
- `idempotency_records` não expira — cresce sem limite. Junta com a decisão
  de retenção ainda pendente (seção 15, item 8 do plano).
- Reconciliação periódica (Celery Beat, a cada 5 min) só re-enfileira
  campanha travada há mais de 10 minutos (`Campaign.updated_at` velho) —
  evita disparo duplicado numa campanha que está sendo processada agora.
