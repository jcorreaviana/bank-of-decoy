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
