# Logging

## Formato
Todo log é uma linha JSON única (sem multi-linha, sem pretty-print) escrita em stdout.

## Campos obrigatórios

| Campo         | Tipo   | Descrição                                                        |
|---------------|--------|-------------------------------------------------------------------|
| `timestamp`   | string | ISO 8601 UTC, ex. `2026-08-26T14:32:01.123Z`                     |
| `service_name`| string | nome do microserviço (ex. `onboarding-service`)                  |
| `level`       | string | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL`           |
| `trace_id`    | string | UUID correlacionando a requisição/evento fim a fim               |
| `message`     | string | descrição curta e legível do evento                              |
| `context`     | object | dict livre com dados adicionais relevantes ao evento             |

Nenhum log é aceito em code review sem esses seis campos.

## Quando usar cada nível

- **DEBUG**: detalhes internos úteis apenas em desenvolvimento/depuração local (payloads intermediários, valores de variáveis de decisão). Desligado por padrão em produção.
- **INFO**: eventos de negócio relevantes e esperados (conta criada, chave PIX registrada, transação processada com sucesso). Um INFO por marco de fluxo, não por linha de código. Vale também para o caminho de sucesso "sem ação" — um ciclo que termina sem achado, ou uma decisão explícita de não agir (ex. issue pulada, sinal já sinalizado/dedup), é um marco de fluxo como outro qualquer e precisa de log; só existir log em `ERROR` deixa o operador sem visibilidade do comportamento normal (achado real, issue #33).

## `trace_id` fora de um serviço HTTP

Nos 4 microserviços de domínio, o `trace_id` correlaciona uma requisição HTTP fim a fim (`RequestLoggingMiddleware`). Processos sem requisição entrante — os daemons de polling `agent-preditivo` e `agent-local` — não têm esse gancho: nesse caso, o `trace_id` é gerado uma vez no início de cada ciclo de polling e vale para todos os logs emitidos durante aquele ciclo, permitindo reconstruir a história de um ciclo completo (o que foi consultado, o que foi decidido e por quê) só lendo o log, sem precisar consultar outro sistema.
- **WARNING**: situação anômala mas recuperável ou esperada como exceção (retry, validação de negócio rejeitada, timeout com fallback).
- **ERROR**: falha que impede a operação corrente de completar, mas não derruba o serviço (exceção tratada, chamada externa falhou sem fallback).
- **CRITICAL**: falha que compromete a disponibilidade do serviço (perda de conexão com banco, falha ao iniciar).

## PII
- CPF, nome completo e qualquer outro dado pessoal identificável **nunca** aparecem em log de nível `DEBUG` ou `INFO`.
- Em `WARNING`, `ERROR` e `CRITICAL`, quando for indispensável referenciar o registro afetado, usar o `id` (UUID) do recurso, nunca o CPF ou nome cru.
- Se for necessário logar um CPF por exigência de auditoria, ele deve ser mascarado (ex. `***.***.**1-23`) — nunca em texto pleno, em nenhum nível.
