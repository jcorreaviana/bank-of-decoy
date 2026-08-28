# Error Handling

## Formato padrão de resposta de erro

Toda resposta de erro HTTP (4xx e 5xx) segue este formato JSON:

```json
{
  "error_code": "string",
  "message": "string",
  "field": "string|null",
  "trace_id": "string"
}
```

- `error_code`: identificador estável e específico do domínio (ex. `ACCOUNT_NOT_FOUND`, `PIX_KEY_ALREADY_REGISTERED`, `INVALID_DOCUMENT_FORMAT`). `SCREAMING_SNAKE_CASE`. Usado por clientes para tratamento programático — não muda entre versões sem depreciação.
- `message`: descrição legível por humanos, em português, sem detalhes internos (sem nome de tabela, sem stack trace).
- `field`: nome do campo do request que causou o erro, quando aplicável (erro de validação). `null` quando o erro não é atribuível a um campo específico.
- `trace_id`: mesmo UUID usado no log estruturado da requisição, permite correlacionar erro no cliente com log no servidor.

## Middleware global
- Cada serviço registra um exception handler global no FastAPI.
- Toda exceção não mapeada explicitamente é capturada por esse handler e retorna HTTP 500 no formato acima, com `error_code: "INTERNAL_ERROR"` e `message` genérica ("Erro interno. Tente novamente.").
- Stack trace nunca é retornado no corpo da resposta ao cliente, em nenhum ambiente (incluindo dev). Stack trace completo vai para o log (nível `ERROR`, campo `context.stack_trace`).

## Exceções de domínio
- Regras de negócio lançam exceções de domínio tipadas (ex. `AccountNotFoundError`, `InsufficientFundsError`), definidas em `app/core/errors.py`.
- Cada exceção de domínio é mapeada explicitamente para um status HTTP e `error_code` no exception handler — não depende do handler genérico de 500.
- Erros de validação de schema (Pydantic) são convertidos para o formato padrão com `error_code: "VALIDATION_ERROR"` e `field` preenchido com o primeiro campo inválido.

## Ciclo de vida de auto-atribuição de agentes autônomos

Todo agente que executa `assign_self` sobre uma issue antes de iniciar processamento assíncrono (SDK, testes, push, PR) assume um contrato implícito: a partir da atribuição, a issue sai da fila de candidatos (`no:assignee`) e não retorna automaticamente por nenhum mecanismo além da conclusão explícita do fluxo.

Esse contrato exige que toda saída do processamento — sucesso ou falha — resulte em um destino final visível para a issue. Não é aceitável que uma exceção não tratada deixe a issue atribuída sem comentário, sem decisão registrada em `risk_decisions` e sem retorno à fila.

Destinos válidos após `assign_self`:

1. **Decisão de risco registrada** (`record_risk_decision`), com PR aberto ou merge automático.
2. **No-op legítimo**: quando o agente conclui corretamente que nenhuma mudança é necessária (ex. `diff_lines: 0`), isso não é falha. Deve gerar uma decisão do tipo `no_action_needed` em `risk_decisions`, comentário na issue explicando o motivo, e a issue deve ser desatribuída.
3. **Falha genérica não tratada**: qualquer exceção não prevista nos destinos acima deve, via `try`/`finally` (ou context manager) envolvendo todo o corpo de `process_issue`, desatribuir a issue, comentar o motivo da falha e devolvê-la à elegibilidade em `list_candidate_issues`.

Nenhum agente pode encerrar processamento de uma issue atribuída sem cair em um dos três destinos acima.

Toda chamada ao SDK dentro de `process_issue` deve ter timeout explícito, garantindo que o bloco `finally` seja alcançado mesmo em caso de travamento sem exceção lançada.

Após N falhas consecutivas na mesma issue, o agente deve aplicar um label de escalonamento (ex. `agent-stuck`) em vez de devolver a issue à fila indefinidamente, evitando um loop de retry sem teto.
