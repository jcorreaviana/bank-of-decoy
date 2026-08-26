---
name: História de negócio
about: Template para histórias que seguem o padrão spec-driven do projeto
title: "[FASE X] Título curto da história"
labels: ["business-story"]
---

## Spec de referência

Link para o arquivo em `specs/business/` que detalha essa história.
Se a spec ainda não existe, criar antes de iniciar a implementação.

## Resumo

Uma ou duas frases descrevendo o que essa história entrega.

## Contrato afetado

Quais endpoints REST ou eventos Kafka essa história cria ou modifica.
Referenciar a spec técnica relevante (specs/tech/api-conventions.md, specs/tech/messaging.md).

## Critério de aceite

- [ ] Item verificável 1
- [ ] Item verificável 2
- [ ] Testes cobrindo caminho feliz e erros documentados na spec

## Specs técnicas relevantes

Marcar quais specs técnicas essa história precisa respeitar:

- [ ] stack.md
- [ ] logging.md
- [ ] database.md
- [ ] error-handling.md
- [ ] api-conventions.md
- [ ] testing.md
- [ ] observability.md
- [ ] messaging.md
- [ ] security.md
- [ ] infrastructure.md

## Sinal de risco (para o score de subida)

Categoria da mudança: regra de negócio | operacional
Serviço(s) afetado(s) e criticidade: (crítico | alto | baixo, conforme specs/tech/ ou documento de escopo)

## Dependências

Histórias/issues que precisam estar concluídas antes desta.
