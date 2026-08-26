# 02 — Modelo de dados inicial

## Contexto / objetivo
Definir e migrar o schema Postgres inicial das quatro entidades centrais do domínio (onboarding, account, pix_key, transaction), já preparado para soft delete, auditoria e para o vínculo de estorno que será implementado em fase futura — evita migration destrutiva mais tarde para adicionar essas colunas.

## Contrato afetado
Nenhum endpoint REST diretamente — esta história entrega apenas schema de banco (migrations), consumido pelas histórias 03, 05 e 06.

## Escopo

### `onboardings` (onboarding-service)
- `id` UUID PK
- `cpf` string, indexado, único entre registros não deletados
- `nome` string
- `data_nascimento` date
- `email` string
- `telefone` string
- `documento_tipo` string
- `documento_numero` string
- `dispositivo_id` string
- `ip_origem` string
- `status` string (`em_analise`, `aprovado`, `reprovado_qualidade`, `reprovado_fraude`)
- `motivo_reprovacao` string, nullable — sinal registrado pelo gerador de risco (ver [04-onboarding-risco.md](04-onboarding-risco.md))
- `created_at`, `updated_at`, `deleted_at` (nullable)

### `accounts` (account-service)
- `id` UUID PK
- `onboarding_id` UUID, referência ao onboarding de origem (sem FK cross-database — apenas armazenado como referência lógica, já que é outro serviço/banco)
- `cpf` string, indexado
- `status` string (`ativa`, `bloqueada`, `encerrada`)
- `created_at`, `updated_at`, `deleted_at` (nullable)

### `pix_keys` (pix-key-service)
- `id` UUID PK
- `account_id` UUID, referência lógica à conta
- `tipo` string (`cpf`, `email`, `telefone`, `aleatoria`)
- `valor` string, único entre registros não deletados
- `created_at`, `updated_at`, `deleted_at` (nullable)

### `transactions` (transaction-service)
- `id` UUID PK
- `account_id` UUID, referência lógica à conta de origem
- `pix_key_destino` string
- `valor` numeric(18,2)
- `status` string (`concluida`, `suspeita`, `falha`)
- `original_transaction_id` UUID, FK nullable para `transactions.id` — reservado para o vínculo de estorno (feature futura, fora do escopo desta fase, mas a coluna já existe para não exigir migration destrutiva depois)
- `created_at`, `updated_at`, `deleted_at` (nullable)

Todas as quatro tabelas seguem as convenções gerais de [database.md](../tech/database.md): `id` UUID, `created_at`/`updated_at`, soft delete via `deleted_at`, nomenclatura `snake_case` plural.

## Critério de aceite
- [ ] Migration (Alembic) para cada uma das quatro tabelas, aplicável via `alembic upgrade head` em cada serviço.
- [ ] Todas as tabelas têm `id` UUID, `created_at`, `updated_at`, `deleted_at` nullable.
- [ ] `transactions.original_transaction_id` existe como FK nullable para `transactions.id`, sem `ON DELETE CASCADE`.
- [ ] Índice único em `onboardings.cpf` e `pix_keys.valor`, restrito a `deleted_at IS NULL` (índice parcial), garantindo que um CPF/chave "deletado" não bloqueia reuso.
- [ ] Teste automatizado (migration test ou teste de integração) comprovando que `DELETE` físico não é usado — a remoção via repository seta `deleted_at`, o registro continua existindo na tabela.

## Specs técnicas aplicáveis
- [database.md](../tech/database.md) — convenções de schema, soft delete, nomenclatura, FK nullable.
