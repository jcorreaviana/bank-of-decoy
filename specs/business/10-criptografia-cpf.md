# 10 — Criptografia de CPF (repouso + trânsito interno)

## Contexto

`onboardings.cpf` já está em produção local (issues #2/#3, fechadas) armazenando CPF em texto puro. `accounts.cpf` (NOT NULL, issue #2) ainda não foi preenchido, porque a issue #5 identificou que o único jeito de obter o CPF é via um novo endpoint interno de comunicação serviço-a-serviço, e esse é o momento correto de já nascer criptografado — tanto em repouso quanto no payload transmitido internamente.

## Objetivo

1. Criptografar `cpf` em repouso nas tabelas `onboardings` e `accounts`, com chave simétrica fornecida via variável de ambiente, transparente na camada de aplicação (a aplicação criptografa ao salvar e descriptografa ao ler; o valor nunca fica em texto puro no banco).
2. Migrar os dados já existentes em `onboardings.cpf` para o formato criptografado (mesmo sendo dados de teste, a correção deve ser feita como se fosse produção real).
3. O endpoint interno `GET /v1/onboarding/{id}/internal` (a ser criado na issue #5) retorna o CPF já no formato criptografado no payload da resposta; o serviço consumidor (`account-service`) descriptografa usando a mesma chave simétrica antes de gravar em `accounts.cpf` (também criptografado em repouso).

## Contrato afetado

Nenhuma mudança de endpoint público. Mudança é interna: como o dado é armazenado e como transita entre `onboarding-service` e `account-service` na chamada interna.

## Critério de aceite

- [ ] Biblioteca de criptografia simétrica (ex. `cryptography` / Fernet) integrada, chave lida de variável de ambiente, documentada em `.env.example` (sem valor real)
- [ ] `onboardings.cpf` criptografado em repouso; migration aplicada convertendo os registros existentes
- [ ] `accounts.cpf` criptografado em repouso desde a criação
- [ ] Endpoint interno retorna CPF criptografado; `account-service` descriptografa corretamente para uso interno e regrava criptografado
- [ ] Teste confirmando que consultar o banco diretamente (fora da aplicação) não expõe o CPF em texto puro
- [ ] Nenhuma mudança no contrato público documentado em `specs/business/03-onboarding-post.md` (CPF continua ausente do GET público)

## Specs técnicas relevantes

- `specs/tech/security.md` (atualizar para documentar a decisão de criptografia em repouso e a chave via variável de ambiente)
- `specs/tech/database.md`
- `specs/tech/infrastructure.md` (variável de ambiente da chave)

## Sinal de risco (para o score de subida)

Categoria da mudança: regra de negócio (dado sensível, decisão de segurança)
Serviço(s) afetado(s): onboarding-service e account-service (criticidade alta — dado sensível de cliente)

## Dependências

Depende da issue #2 (schema já existente, requer migration) e da issue #3 (onboarding-service já implementado). Bloqueia a issue #5, que só pode ser retomada depois desta.
