# 08 — Populador de volumetria

## Contexto / objetivo
Gerar massa de dados sintética e realista sobre o funil completo (onboarding → conta → chave PIX → transações), em volume suficiente para as fases seguintes de caos e engenharia agêntica terem um cenário rico para explorar. Precisa ser reprodutível (seed fixa) para que execuções repetidas do script gerem sempre a mesma distribuição, permitindo comparar resultados entre rodadas.

## Contrato afetado
Nenhum endpoint novo. O script consome os endpoints já existentes (`POST /v1/onboarding`, fluxo de conta via evento Kafka da história [07-kafka-onboarding-eventos.md](07-kafka-onboarding-eventos.md), `POST /v1/pix-keys`, `POST /v1/transactions`) ou popula diretamente via repository/banco quando o volume via HTTP for inviável em tempo de execução — decisão de implementação, desde que a distribuição final resultante respeite as regras de negócio de cada gerador de risco.

## Escopo
- Gera **500.000+ contas** (via onboardings aprovados que viram conta pelo fluxo real, respeitando a distribuição de 0,5%–1% de reprovação de [04-onboarding-risco.md](04-onboarding-risco.md)).
- Para cada conta, gera **20 a 50 transações**, respeitando a distribuição de 1%–2% de `suspeita` de [06-pixkey-transaction-crud.md](06-pixkey-transaction-crud.md).
- Além da suspeita de fraude do gerador de risco de transação, o populador introduz **5% a 10%** de transações com falha técnica simulada (`status: "falha"` — timeout, erro de validação tardia, etc.), representando ruído operacional independente do sinal de fraude.
- Seed fixa e documentada (ex. constante no script ou parâmetro `--seed` com default fixo) — duas execuções com a mesma seed produzem a mesma volumetria e as mesmas classificações.

## Critério de aceite
- [ ] Script executável de ponta a ponta (`python populate.py` ou equivalente) gera ao menos 500.000 contas.
- [ ] Cada conta tem entre 20 e 50 transações associadas (`account_id` correspondente).
- [ ] Percentual de onboardings reprovados (qualidade + fraude combinados) no resultado final está entre 0,5% e 1%.
- [ ] Percentual de transações `suspeita` está entre 1% e 2%.
- [ ] Percentual de transações com falha técnica simulada está entre 5% e 10%.
- [ ] Rodar o script duas vezes com a mesma seed produz a mesma contagem total e a mesma distribuição percentual (dentro de margem de arredondamento).
- [ ] Rodar o script com seed diferente produz volumetria diferente, confirmando que a seed de fato controla a geração (não é reprodutibilidade por acidente).
- [ ] Script loga progresso em formato estruturado (ver [logging.md](../tech/logging.md)) sem expor CPF/dados pessoais reais — dados sintéticos gerados não usam CPFs válidos reais de pessoas.
- [ ] Teste automatizado valida a distribuição gerada em uma amostra menor (ex. 10.000 registros) antes de rodar a carga completa de 500k, para detectar regressão de proporção sem esperar a execução completa.

## Specs técnicas aplicáveis
- [testing.md](../tech/testing.md) — validação estatística da distribuição gerada como parte da suite de testes.
- [logging.md](../tech/logging.md) — log estruturado do progresso, sem PII real.
- [database.md](../tech/database.md) — volume respeita soft delete e timestamps de auditoria já definidos no schema.
