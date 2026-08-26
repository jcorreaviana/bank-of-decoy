# Database

## Banco
Postgres. Cada microserviço tem seu próprio schema/banco — sem acesso cruzado direto a tabelas de outro serviço (comunicação entre serviços é via API ou eventos, nunca via SQL entre bancos).

## Colunas obrigatórias em toda tabela
- `id`: UUID, chave primária (gerado na aplicação ou via `gen_random_uuid()`).
- `created_at`: `timestamptz`, `NOT NULL`, default `now()`.
- `updated_at`: `timestamptz`, `NOT NULL`, default `now()`, atualizado em todo `UPDATE`.

## Soft delete
- Registros que podem ser cancelados ou removidos usam soft delete: coluna `deleted_at` (`timestamptz`, nullable).
- `DELETE` físico é proibido para essas entidades. "Remover" = `UPDATE ... SET deleted_at = now()`.
- Toda query de leitura em tabela com soft delete filtra `WHERE deleted_at IS NULL` por padrão, exceto consultas explícitas de auditoria/histórico.
- Nem toda tabela precisa de soft delete — apenas entidades de negócio que representam um registro que pode ser "desfeito" (conta, chave PIX). Tabelas puramente de log/evento não precisam.

## Nomenclatura
- Nome de tabela: `snake_case`, plural (ex. `accounts`, `pix_keys`, `transactions`).
- Nome de coluna: `snake_case`, singular (ex. `account_id`, `pix_key_type`).
- FK nomeada como `<entidade_referenciada_singular>_id` (ex. `account_id` referenciando `accounts.id`).

## Referências entre tabelas
- FKs entre tabelas do mesmo serviço usam constraint de FK real no Postgres.
- Referências que representam um vínculo opcional ou tardio (ex. `reversals.original_transaction_id` apontando para `transactions.id`) são FK nullable — a ausência do vínculo é um estado válido, não um erro de dado.
- Nenhuma FK usa `ON DELETE CASCADE` como padrão automático — cascade é decisão explícita por caso de uso, documentada no modelo.

## Migrations
- Toda alteração de schema é versionada via migration (Alembic recomendado), nunca alteração manual direto no banco.
