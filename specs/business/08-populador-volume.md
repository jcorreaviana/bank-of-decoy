# 08 — Populador de volumetria

## Contexto / objetivo
Gerar massa de dados sintética e realista sobre o funil completo (onboarding → conta → chave PIX → transações), em volume suficiente para as fases seguintes de caos e engenharia agêntica terem um cenário rico para explorar. Precisa ser reprodutível (seed fixa) para que execuções repetidas do script gerem sempre a mesma distribuição, permitindo comparar resultados entre rodadas.

## Contrato afetado
Nenhum endpoint novo. **Decisão de implementação**: o script popula diretamente via bulk insert no banco de cada serviço (reflexão de schema, sem importar `app.*` de nenhum serviço — ver [stack.md](../tech/stack.md)), nunca via API/Kafka registro a registro — inviável no volume de centenas de milhares de contas e dezenas de milhões de transações. Para não duplicar a lógica de classificação de risco (já implementada em onboarding-service e transaction-service), ela foi extraída para um pacote compartilhado (`shared/risk_engine/`), usado tanto pelos dois serviços (refatorados para consumi-lo) quanto pelo populador.

## Escopo
- Gera **500.000+ contas** a partir de onboardings sintéticos classificados pelo mesmo motor de risco dos serviços reais (`risk_engine`), respeitando a distribuição de 0,5%–1% de reprovação de [04-onboarding-risco.md](04-onboarding-risco.md).
- Para cada conta, gera **20 a 50 transações**, respeitando a distribuição de 1%–2% de `suspeita` de [06-pixkey-transaction-crud.md](06-pixkey-transaction-crud.md).
- Seed fixa e documentada (parâmetro `--seed`, default fixo `20260826`) — duas execuções com a mesma seed produzem a mesma volumetria e as mesmas classificações (verificado na prática, não só em teste unitário: rodar duas vezes contra bancos limpos produziu contagens e percentuais idênticos; seed diferente divergiu).
- **Adaptação necessária em relação à calibração original** (que assumia geração pura, sem banco real): `onboardings.cpf_hash` tem índice único — o sinal `pep_detectado` só pode aparecer no máximo 3 vezes no total (um CPF fixo por vez, dos 3 simulados). O restante da fração de fraude usa `ip_origem`/`dispositivo_id` na blacklist simulada (sem restrição de unicidade), produzindo o mesmo hard-stop de fraude sem violar constraint.
- `tipo_conta` das contas geradas: distribuição sintética 70% `corrente` / 30% `poupança` (decisão de implementação para diversidade de dados — o funil real via evento Kafka, issue #7, sempre usa `corrente` como default, já que o payload do evento não carrega esse campo).
- **Não implementado nesta história** (decisão confirmada com o autor, adiada para a Fase 2): 5%–10% de transações com falha técnica simulada (`status: "falha"`) — o populador gera apenas `concluida`/`suspeita`, mesmos status já produzidos pelo gerador de risco real.

## Critério de aceite
- [x] Script executável de ponta a ponta (`python populate_volume.py`) gera ao menos 500.000 contas. Rodado de ponta a ponta: 505.000 onboardings → 500.980 contas.
- [x] Cada conta tem entre 20 e 50 transações associadas (`account_id` correspondente). Verificado via `SELECT min/max/avg` sobre a carga real: min 20, max 50, média 35.
- [x] Percentual de onboardings reprovados (qualidade + fraude combinados) no resultado final está entre 0,5% e 1%. Obtido: 0,796% (4.020 de 505.000).
- [x] Percentual de transações `suspeita` está entre 1% e 2%. Obtido: 1,5374% (269.330 de 17.518.471).
- [ ] Percentual de transações com falha técnica simulada está entre 5% e 10%. **Não implementado nesta história** — adiado para a Fase 2, decisão confirmada com o autor antes da implementação.
- [x] Rodar o script duas vezes com a mesma seed produz a mesma contagem total e a mesma distribuição percentual. Verificado contra bancos descartáveis: duas execuções com seed `20260826` produziram exatamente os mesmos totais (contas, transações, suspeitas, reprovados).
- [x] Rodar o script com seed diferente produz volumetria diferente. Verificado: seed `777` produziu totais diferentes de `20260826` na mesma escala.
- [x] Script loga progresso em formato estruturado (ver [logging.md](../tech/logging.md)) sem expor CPF/dados pessoais reais — dados sintéticos gerados não usam CPFs válidos reais de pessoas. Log JSON com os 6 campos padrão; `context` só carrega contadores/percentuais, nunca CPF/nome/e-mail; CPFs sintéticos são sequenciais com prefixo fixo, óbviamente não reais.
- [x] Teste automatizado valida a distribuição gerada em uma amostra menor (ex. 10.000 registros) antes de rodar a carga completa de 500k, para detectar regressão de proporção sem esperar a execução completa. `scripts/tests/test_generation_distribution.py`, roda sem banco (só a lógica pura de geração).

## Specs técnicas aplicáveis
- [testing.md](../tech/testing.md) — validação estatística da distribuição gerada como parte da suite de testes.
- [logging.md](../tech/logging.md) — log estruturado do progresso, sem PII real.
- [database.md](../tech/database.md) — volume respeita soft delete e timestamps de auditoria já definidos no schema.
