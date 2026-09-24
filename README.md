# Evig — Mensagem Direta

Primeiro vertical slice do serviço de templates e campanhas via WhatsApp Business Platform.

## Estrutura

- `backend/`: FastAPI, domínio, persistência e adapters Meta/gateway;
- `frontend/`: React + TypeScript + Vite;
- `docs/adr/`: decisões de arquitetura registradas;
- `contracts/`: snapshot do contrato REST (OpenAPI);
- `PLANEJAMENTO.md`: escopo, arquitetura e fases;
- `compose.yaml`: ambiente local com PostgreSQL, Redis, API, worker, beat e frontend.

## Execução local rápida

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

A documentação OpenAPI estará em `http://localhost:8000/docs`.

### Frontend

```powershell
cd frontend
pnpm install
pnpm dev
```

Abra `http://localhost:5173/mensagem-direta`.

### Containers

```powershell
docker compose up --build
```

### Produção em uma única VM

O arquivo `compose.production.yaml` executa Caddy, frontend, API, worker,
scheduler, PostgreSQL e Redis na mesma máquina. Apenas as portas 80/443 são
publicadas; banco, cache e API permanecem na rede interna do Docker. O Caddy
emite e renova HTTPS automaticamente para o host definido em `PUBLIC_HOST`.

```bash
cp .env.production.example .env.production
# edite todos os segredos e o IP/domínio permitido
docker compose --env-file .env.production -f compose.production.yaml up -d --build
```

Para 2 GB de RAM, o worker usa uma única tarefa concorrente e cada serviço tem
limite de memória. O banco fica persistido no volume `postgres-data`; mantenha
backup externo periódico desse volume. O deploy Lightsail também instala o
script `deploy/backup-postgres.sh`, que gera dumps locais diários com retenção
de sete dias quando o arquivo cron correspondente é habilitado.

## Disparo via gateway

Campanhas e envios de teste usam exclusivamente `Mensagem Direta → gateway Go → Meta`. Configure `GATEWAY_URL` e `GATEWAY_INTERNAL_KEY` no serviço e `channel_account_id` por empresa na tela Conexão WABA. O gateway responde `delivery_id` e o status local `ACCEPTED` indica apenas enfileiramento. [Arquitetura e contrato](docs/arquitetura-mensagem-direta.md).

Configure o callback da Meta somente no gateway Go. Mensagem Direta não registra webhook Meta. Status de templates vêm da Graph API por sincronização manual ou periódica; estados novos de entrega e resposta ainda não são repassados pelo gateway.

## Modo Meta

O padrão é `META_MODE=mock`. Nesse modo, o botão **Sincronizar Meta** importa um template aprovado de demonstração. Envio ainda exige middleware configurado e conta por empresa.

Para usar a Graph API real, defina `META_MODE=live` em `backend/.env` (copie de `.env.example`) e cadastre o token, WABA ID e phone number ID **por empresa**, em *Empresa → Configurar conexão WABA* na UI (ou via `PUT /api/v1/organizations/{id}/waba-connection`). As variáveis `META_ACCESS_TOKEN`/`META_WABA_ID`/`META_PHONE_NUMBER_ID` do `.env` só servem para semear a conexão da organização padrão na primeira inicialização; depois disso a conexão de cada empresa vive no banco. Nunca coloque o token no frontend ou no Git.

## Fonte comercial

O padrão `AUDIENCE_MODE=mock` mantém sete contatos exclusivamente para demonstração. Para operar dados reais, use `AUDIENCE_MODE=http`, configure `AUDIENCE_API_URL` e, se necessário, `AUDIENCE_API_TOKEN`. O contrato está em [`docs/audience-api.md`](docs/audience-api.md). A seleção é consultada novamente no momento do disparo e opt-outs locais sempre prevalecem.

## Multi-empresa e acesso

Cada empresa é uma `organization`, com conexão WABA, templates, campanhas, consentimentos e opt-outs isolados por `organization_id`. O seletor **Empresa** troca a organização atual.

Em desenvolvimento, `AUTH_ENABLED=false`. Em ambiente com dados reais, ative `AUTH_ENABLED=true` e configure `AUTH_TOKENS` no formato `token:ROLE:organization_id`, separado por vírgulas. Papéis disponíveis: `VIEWER`, `OPERATOR` e `ADMIN`; apenas o administrador global usa `*`. Ative `VITE_AUTH_ENABLED=true` no build do frontend: a tela de acesso guarda o token somente em `sessionStorage`. `VITE_API_TOKEN` é apenas uma conveniência local e não deve conter segredo num build distribuído.

## Respostas e atendimento

O gateway recebe respostas. Ainda não existe contrato para repassar esses eventos ao Mensagem Direta, portanto `HANDOFF_WEBHOOK_URL` e o processamento local de `SAIR` permanecem legados e inativos. Opt-outs podem ser registrados pela API local de compliance; a fonte comercial também informa `opted_out`. Consulte os [gaps da arquitetura](docs/arquitetura-mensagem-direta.md).

## Estado desta entrega

Implementado:

- projetos backend/frontend separados;
- modelos de template, campanha e destinatário;
- adapter mock e adapter HTTP da Graph API;
- sincronização e submissão de template;
- presets locais;
- preview cumulativo de público com guardas obrigatórias;
- criação, validação e envio controlado em modo local;
- sincronização de templates pela Graph API sem webhook local;
- webhook Meta exclusivo do gateway;
- worker Celery e agendamento persistido;
- opt-out persistido com telefone protegido por HMAC;
- compliance isolado por empresa e opt-outs incorporados ao preview;
- opt-out por categoria (`ALL`, `MARKETING` ou `UTILITY`) e revogação de consentimento aplicados no preview e novamente no disparo;
- API para registrar/revogar consentimento e registrar opt-out por outros canais;
- auditoria das ações de template e campanha;
- agregação de resultados por campanha;
- migração inicial Alembic;
- interface de catálogo, preview, wizard em duas etapas e resultados com polling;
- criação de template do zero e edição completa de rascunho/rejeitado (título, corpo, rodapé, botões) direto na UI;
- exclusão de template (local e na Meta, quando aplicável);
- `example` de variável e `format` de header gerados automaticamente na submissão, para bater com o que a Graph API exige;
- multi-empresa: `organizations` + `waba_connections`, templates e campanhas isolados por `organization_id`, seletor de empresa e tela de configuração/teste de conexão WABA na UI;
- `Idempotency-Key` em criação/disparo (`POST /templates/drafts`, `.../submit`, `POST /campaigns`, `.../send`) — replay com a mesma chave devolve o resultado salvo, não repete o efeito;
- retry de falha transitória do middleware, com backoff e jitter nativos do Celery; erros permanentes não são repetidos (`app/services/campaign_dispatcher.py`);
- lease persistente e heartbeat por campanha para impedir dois workers de dispararem a mesma campanha ao mesmo tempo;
- reconciliação periódica via Celery Beat: campanha travada há mais de 10 min é reenfileirada, templates de toda organização são resincronizados a cada 30 min pela Graph API;
- token da conexão WABA cifrado em repouso (Fernet, ver `docs/adr/0004-token-encryption-not-secret-manager.md`);
- telefone e variáveis de novos destinatários cifrados em repouso, com hash para compliance e frequência;
- fonte comercial substituível (`mock` ou HTTP), com contrato e teste;
- RBAC de MVP por Bearer token estático, papel e empresa;
- agendamento e cancelamento disponíveis na interface;
- outbox legado de encaminhamento, sem novos eventos desde a desativação do webhook local;
- recuperação de campanhas agendadas vencidas mesmo depois de perda/reinício do Redis;
- inferência e edição das fontes de variáveis em templates sincronizados da Meta;
- versões imutáveis: template aprovado como marketing pode gerar novo rascunho utility sem alterar campanhas antigas;
- categoria solicitada, categoria efetiva e futura correção da Meta registradas separadamente;
- nomes enviados à Meta recebem prefixo normalizado da empresa para facilitar gestão na WABA;
- limite local obrigatório de três templates consecutivos por contato, zerado por resposta comprovada pela fonte comercial; envio de teste não consulta a fonte;
- restrições de templates corretamente isoladas por organização;
- logs JSON com request ID, status e duração;
- workflow de CI para lint, testes, migrações e build;
- ADRs em `docs/adr/` e snapshot do contrato REST em `contracts/openapi.json`;
- testes unitários das regras críticas e teste de integração HTTP em memória.

Fora do escopo do MVP, recomendados antes de ampliar a operação:

- contrato do gateway para repassar resposta, `SAIR`, entrega e leitura com identificação de tenant;
- suporte de envio no gateway para outros idiomas, mídia de cabeçalho e parâmetros dinâmicos de botão;
- trocar tokens estáticos por SSO/OIDC e identidade individual;
- upload de mídia para templates (header do tipo imagem);
- token da conexão WABA num secret manager de verdade (Fernet hoje protege só contra dump de banco, não contra quem tem o `PII_HASH_SECRET`);
- testes de integração contínuos com PostgreSQL/Redis e sandbox real da Meta;
- métricas e tracing distribuído (logs estruturados já estão presentes);
- cliente TypeScript gerado a partir do OpenAPI (hoje o `frontend/src/api/client.ts` é escrito à mão).
