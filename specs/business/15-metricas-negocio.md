# 15 — Dashboard de métricas de negócio (v1)

## Contexto

Desde a issue #9, o projeto tem observabilidade de **engenharia** (golden signals: latência, tráfego, taxa de erro, saturação) via Grafana/Prometheus. Métricas de **negócio** — volume de onboarding, volume financeiro transacionado, taxa de sinalização de risco — nunca foram instrumentadas, apesar do schema de domínio já carregar todos os dados necessários (`risco_score`, `risco_sinais`, `status`) desde a Fase 1 (`docs/escopo-arquitetura.md`, seção "Resolvidos").

**Esta spec define a v1 do dashboard de negócio — não a versão final.** É a primeira iteração validável: as métricas mais óbvias e diretamente disponíveis nos quatro serviços hoje, expostas pelo mesmo mecanismo que já existe (Prometheus via `/metrics`), num dashboard Grafana separado dos técnicos. Métricas mais sofisticadas, correlações entre sinais, ou uma UI de negócio dedicada fora do Grafana ficam para depois (ver "Fora de escopo para v1" abaixo) — não é decisão tomada aqui, é decisão adiada de propósito para não travar esta primeira entrega.

## Objetivo

Instrumentar métricas de negócio nos serviços onde os fatos já acontecem hoje, e montar um dashboard Grafana v1 legível por alguém não técnico, contando três histórias:

1. **Funil de onboarding** — quantos onboardings são aprovados vs. reprovados (por qualidade ou por fraude), ao longo do tempo.
2. **Volume financeiro PIX** — quantas transferências acontecem e qual a distribuição de valor transacionado.
3. **Taxa de sinalização de risco** — com que frequência cada tipo de sinal de risco (onboarding e transação) aparece, incluindo `entrada_saida_rapida` (padrão mula bidirecional, issue #19).

Chaves PIX registradas (volume por tipo) entram como um quarto painel simples, complementar ao funil — não é uma história de negócio por si só nesta v1, mas é um dado direto e já disponível.

### Fonte de dado: Prometheus, não consulta direta ao Postgres

Os quatro serviços passam a expor métricas de negócio via `/metrics` (Prometheus), do mesmo jeito que já expõem golden signals hoje — **não** é o Grafana consultando o Postgres diretamente. Isso significa instrumentar contadores/histogramas novos nos pontos já existentes do código onde esses eventos de negócio acontecem (classificação de onboarding, criação de transação, registro de chave PIX), sem duplicar nenhuma regra de negócio — só adicionar a chamada ao contador/histograma ao lado do que já é logado/persistido.

### Métricas novas

Seguindo a convenção de nomenclatura já estabelecida (`specs/tech/observability.md`: `snake_case`, sufixo `_total` para contador, sufixo de unidade para histograma) e a convenção de nomes de domínio em português já usada em tópicos Kafka e campos de payload (`onboarding`, `transacao`, `risco_sinais`):

| Métrica | Tipo | Serviço | Labels | Onde instrumentar |
|---|---|---|---|---|
| `onboarding_resultado_total` | Counter | `onboarding-service` | `resultado` (`aprovado`\|`reprovado_qualidade`\|`reprovado_fraude`) | `app/services/onboarding_service.py::create_onboarding`, logo após `db.commit()` da classificação |
| `transacao_processada_total` | Counter | `transaction-service` | `status` (`concluida`\|`suspeita`) | `app/services/transaction_service.py::create_transaction`, logo após `db.commit()` |
| `transacao_valor_reais` | Histogram | `transaction-service` | — | mesmo ponto acima — observa `payload.valor` uma vez por transferência (não duplicar por linha do ledger: a partida dobrada gera duas linhas, `entrada`/`saida`, para o mesmo fato financeiro) |
| `risco_sinal_total` | Counter | `onboarding-service` **e** `transaction-service` | `sinal` (nome do sinal, ex. `entrada_saida_rapida`, `documento_reciclado`, `velocidade_alta`) | mesmo ponto de cada serviço acima — um incremento por sinal presente em `risk.sinais` |
| `chave_pix_registrada_total` | Counter | `pix-key-service` | `tipo` (`cpf`\|`email`\|`telefone`\|`aleatoria`) | `app/services/pix_key_service.py::create_pix_key`, logo após `db.commit()` |

`risco_sinal_total` usa o **mesmo nome de métrica** nos dois serviços — mesmo padrão já usado por `http_requests_total`/`http_request_duration_seconds` nos quatro serviços — o label `job` do Prometheus (atribuído automaticamente pelo scrape config, `specs/tech/infrastructure.md`) já distingue a origem quando necessário; os nomes de sinal em si não colidem entre onboarding e transação.

Valores possíveis de `sinal` (para referência do dashboard/queries):
- Onboarding: `pep_detectado`, `documento_reciclado`, `padrao_mula`, `ip_dispositivo_blacklist`, `documento_formato_invalido`, `dados_inconsistentes`, `documento_ilegivel`
- Transação: `valor_atipico`, `horario_atipico`, `destinatario_novo`, `velocidade_alta`, `entrada_saida_rapida`

## Contrato afetado

Nenhum endpoint REST novo, nenhum schema de evento Kafka alterado. Só instrumentação (`prometheus-client`) nos serviços já existentes — mesma categoria de mudança operacional/observabilidade da issue #9.

## Critério de aceite

- [ ] `onboarding_resultado_total`, `transacao_processada_total`, `transacao_valor_reais`, `risco_sinal_total` (nos dois serviços) e `chave_pix_registrada_total` expostos em `/metrics` dos respectivos serviços
- [ ] Dashboard Grafana novo, **explicitamente nomeado como v1** (ex. título "Métricas de Negócio v1"), separado do dashboard técnico (`Fase 1 - Golden Signals`)
- [ ] Painel de funil de onboarding (aprovado vs. reprovado por qualidade vs. reprovado por fraude, ao longo do tempo)
- [ ] Painel de volume financeiro PIX (contagem de transferências e distribuição/soma de valor)
- [ ] Painel de taxa de sinalização de risco (por tipo de sinal, onboarding + transação)
- [ ] Painel de chaves PIX registradas (por tipo)
- [ ] Validado localmente: serviços reiniciados, volume sintético gerado (onboarding + transações + chaves), números do dashboard conferidos visualmente contra o volume gerado

## Fora de escopo para v1 (próximas iterações)

Registrado aqui para não travar a decisão desta entrega — nenhum destes itens está descartado, só adiado:

- Métricas mais sofisticadas (ex. taxa de aprovação por segmento, tempo médio até classificação, coorte de contas por padrão de risco ao longo do tempo).
- Correlação entre sinais (ex. onboarding com `padrao_mula` que depois gera transação com `entrada_saida_rapida` na mesma conta) — exige join entre dado de dois serviços, não é uma métrica Prometheus simples.
- UI de negócio dedicada fora do Grafana (ex. dashboard interno customizado) — Grafana é suficiente e já disponível para esta v1.
- Alertas/thresholds de negócio (ex. taxa de reprovação de fraude acima de X% dispara notificação) — este documento só cobre visibilidade, não automação de resposta.

## Specs técnicas relevantes

Marcar quais specs técnicas essa história precisa respeitar:

- [ ] stack.md
- [ ] logging.md
- [ ] database.md
- [ ] error-handling.md
- [ ] api-conventions.md
- [ ] testing.md
- [x] observability.md
- [ ] messaging.md
- [ ] security.md
- [x] infrastructure.md

## Sinal de risco (para o score de subida)

Categoria da mudança: operacional (observabilidade)
Serviço(s) afetado(s) e criticidade: `onboarding-service`, `transaction-service`, `pix-key-service` (baixo — instrumentação aditiva, não altera comportamento observável do domínio)

## Dependências

Depende da issue #9 (Grafana/Prometheus já configurados) e da issue #8 (dataset existente para gerar volume real de validação). Ambas já concluídas — sem bloqueio.
