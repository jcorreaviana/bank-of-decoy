# Correção: chave de criptografia hardcoded no docker-compose

## Contexto

O GitGuardian detectou `CPF_ENCRYPTION_KEY` com valor real commitado em `docker-compose.yml`, violando a regra de `specs/tech/security.md` de nunca hardcodar segredos. Como os dados protegidos por essa chave são sintéticos (sem PII real), não é urgente, mas deve ser corrigido antes do projeto ser tratado como artefato de portfólio finalizado — não é uma boa prática deixar em um repositório público de demonstração.

## Objetivo

1. Rotacionar a chave (gerar uma nova)
2. Referenciar via variável de ambiente no `docker-compose.yml` (`${CPF_ENCRYPTION_KEY}`), não valor literal — mesma correção em `docker-compose.test.yml` se aplicável
3. `.env` real (com a nova chave) no `.gitignore`; `.env.example` com placeholder, sem valor real
4. Purgar o valor antigo do histórico de commits do Git (`git filter-repo` ou BFG), com `git push --force` subsequente — só executar após confirmação explícita, já que é operação destrutiva sobre o histórico remoto

## Critério de aceite

- [ ] Nova chave gerada e funcionando
- [ ] `docker-compose.yml` (e `.test.yml`, se aplicável) referenciando variável de ambiente, sem valor literal
- [ ] `.env` no `.gitignore`, `.env.example` com placeholder
- [ ] Histórico do Git purgado do valor antigo (após confirmação explícita antes do force-push)
- [ ] Nenhum outro segredo hardcoded encontrado numa varredura geral do repositório

## Sinal de risco

Categoria da mudança: operacional (correção de configuração/segurança, sem PII real em risco)
Serviço(s) afetado(s): onboarding-service e account-service (baixo risco real, dado sintético, mas tratado como alto padrão de prática)

## Dependências

Nenhuma. Pode ser feita a qualquer momento, mas faz sentido antes da issue de sanitização de referências cruzadas (mesma categoria de "arrumação antes de tratar como portfólio final").
