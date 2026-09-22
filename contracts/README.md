# Contratos

`openapi.json` é um snapshot do contrato REST atual (`GET /openapi.json` do
backend), gerado por `backend/scripts/export_openapi.py`. Existe pra dar ao
frontend (ou a qualquer cliente externo) uma referência versionada do
contrato sem precisar subir o backend — e pra deixar visível no diff de PR
quando um endpoint muda de forma.

Regenerar depois de qualquer mudança em rota/schema:

```powershell
cd backend
python scripts/export_openapi.py
```

Não é gerado em CI ainda — hoje é responsabilidade de quem mexeu no backend
rodar o script e commitar o resultado junto.
