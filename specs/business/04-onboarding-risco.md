# 04 — Gerador de risco do onboarding

## Contexto / objetivo
Classificar cada onboarding criado pela história [03-onboarding-post.md](03-onboarding-post.md) em `aprovado`, `reprovado_qualidade` ou `reprovado_fraude`. Nesta fase o gerador de risco é um conjunto de regras simples e explicáveis (não um modelo de ML) — o objetivo é produzir volumetria realista e auditável para as fases seguintes de engenharia agêntica/caos, não simular um motor antifraude sofisticado.

## Contrato afetado
Não introduz endpoint novo — altera o `status` do registro criado por `POST /v1/onboarding` (ver [03-onboarding-post.md](03-onboarding-post.md)) de `em_analise` para o resultado da classificação. Nesta fase (antes da história 07), a classificação roda de forma síncrona logo após a criação, dentro do mesmo processo/request ou em um job imediatamente subsequente — o mecanismo de fila assíncrona via Kafka só entra na história [07-kafka-onboarding-eventos.md](07-kafka-onboarding-eventos.md).

## Regras de classificação
Regras determinísticas e documentadas (exemplos de sinais avaliados — a lista exata de regras é definida na implementação, mas deve ser auditável e testável):
- **Reprovação por qualidade** (`reprovado_qualidade`): dados inconsistentes ou incompletos que passam na validação de schema mas falham em regra de negócio (ex. `data_nascimento` implicando menor de idade, `documento_numero` com dígito verificador inválido).
- **Reprovação por fraude** (`reprovado_fraude`): sinais associados a fraude (ex. `dispositivo_id` ou `ip_origem` já associado a outro onboarding reprovado por fraude recentemente, CPF em lista de bloqueio simulada).
- **Aprovado**: nenhuma regra de reprovação disparada.

## Distribuição alvo
- Combinado (`reprovado_qualidade` + `reprovado_fraude`) deve representar **0,5% a 1%** do total de onboardings processados no funil onboarding → conta.
- A proporção entre qualidade e fraude dentro desse intervalo é decisão de implementação, desde que documentada e reprodutível (parametrizável, para permitir ajuste na história [08-populador-volume.md](08-populador-volume.md)).

## Score e sinais

O gerador de risco não produz apenas um `status`/`motivo_reprovacao` — cada regra avaliada (dispare ela ou não a reprovação) contribui para dois campos persistidos em `onboardings` (ver [02-modelo-dados.md](02-modelo-dados.md)):

- `risco_sinais`: lista com o identificador de **cada** sinal individual disparado na avaliação (ex. `idade_invalida`, `documento_dv_invalido`, `dispositivo_reincidente_fraude`, `cpf_lista_bloqueio`) — um onboarding pode acionar mais de um sinal ao mesmo tempo, mesmo quando só um deles determina o `status` final.
- `risco_score`: valor numérico (0-100) derivado da combinação de sinais disparados — quanto maior, maior o risco. O cálculo exato (soma ponderada, tabela de pesos por sinal, etc.) é decisão de implementação, desde que determinístico e auditável.

O `status` continua sendo derivado dos sinais: qualquer sinal de fraude disparado resulta em `reprovado_fraude`; na ausência de sinal de fraude, qualquer sinal de qualidade disparado resulta em `reprovado_qualidade`; caso contrário, `aprovado`. O `motivo_reprovacao` é preenchido com o sinal principal (o que determinou o `status`) e permanece por compatibilidade — `risco_sinais` é a lista completa e `risco_score` a métrica agregada, ambos consumidos pelo endpoint `GET /v1/onboarding/{id}` (ver [03-onboarding-post.md](03-onboarding-post.md)).

## Critério de aceite
- [ ] Todo onboarding criado sai do status `em_analise` para `aprovado`, `reprovado_qualidade` ou `reprovado_fraude` de forma determinística dado o mesmo input (mesmas regras, sem aleatoriedade não controlada — se houver componente probabilístico, é seedado).
- [ ] Cada regra de reprovação é uma função isolada e testável unitariamente (caminho feliz + caso que dispara a regra).
- [ ] Rodando o gerador sobre uma amostra grande (ex. 10.000 onboardings sintéticos variados), o percentual combinado de reprovação fica entre 0,5% e 1%.
- [ ] O `motivo_reprovacao` (coluna definida em [02-modelo-dados.md](02-modelo-dados.md)) é preenchido com o sinal que determinou a reprovação, permitindo auditoria.
- [ ] `risco_score` (0-100) e `risco_sinais` (lista, podendo ter múltiplos itens mesmo quando `status` é `aprovado`) são preenchidos para todo onboarding processado.
- [ ] Nenhum dado pessoal (CPF, nome) aparece no log do processo de classificação abaixo de `WARNING` — apenas o `id` do onboarding e o resultado.

## Specs técnicas aplicáveis
- [database.md](../tech/database.md) — persistência do `status` e `motivo_reprovacao` como sinais registrados na tabela `onboardings`.
- [logging.md](../tech/logging.md) — regra de PII no log da classificação.
- [testing.md](../tech/testing.md) — cobertura mínima de 80% em lógica de domínio, aplicável diretamente às regras de risco.
