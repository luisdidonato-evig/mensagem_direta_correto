# ADR 0004 — Token da WABA cifrado com Fernet, não secret manager

## Status
Aceito (2026-09-21).

## Contexto
`waba_connections.access_token` guardava o token da Meta em texto puro.
Um secret manager de verdade (Vault, AWS KMS/Secrets Manager) é a solução
correta, mas exige decidir provedor de infraestrutura — fora do escopo desta
entrega.

## Decisão
Cifrar o token com `cryptography.fernet.Fernet`, chave derivada por SHA-256
de `PII_HASH_SECRET` (já existente na configuração). Cifra/decifra centralizada
em `app/core/crypto.py`; `build_provider_for_connection` decifra no único
lugar onde o token vira uma chamada HTTP real.

## Consequências
- Protege contra vazamento de dump/backup do banco. **Não** protege contra
  quem também tem acesso ao `PII_HASH_SECRET` do ambiente — não é isolamento
  de segredo de verdade.
- Trocar `PII_HASH_SECRET` invalida todos os tokens já salvos (viram
  ilegíveis, endpoint de teste de conexão retorna `ERROR`). Não existe
  rotação de chave nem migração de token entre chaves — precisa reconfigurar
  a conexão manualmente se o secret mudar.
- Antes de produção com token real, isso deveria virar um secret manager de
  verdade (item já listado no `README.md`).
