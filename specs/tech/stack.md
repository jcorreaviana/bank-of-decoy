# Stack

## Linguagem e runtime
- Python 3.12+.
- FastAPI como framework web.
- Uvicorn como servidor ASGI (modo `--reload` em dev, sem reload em produção).
- SQLAlchemy como ORM/toolkit de acesso a dados.
- psycopg2-binary como driver Postgres.
- pytest como framework de testes (+ `pytest-cov`, `httpx` para testes de contrato).

## Ambiente virtual
- Cada microserviço tem seu próprio ambiente virtual isolado (`venv` ou `.venv` na raiz do serviço).
- Dependências declaradas em `requirements.txt` (ou `pyproject.toml`, se o serviço adotar) próprio de cada serviço — não há dependências compartilhadas entre serviços via path relativo.
- Nunca instalar dependências globalmente na máquina/container de desenvolvimento.

## Estrutura de pastas por serviço

```
<nome-do-servico>/
  app/
    __init__.py
    main.py                # cria a app FastAPI, registra routers e middlewares
    routers/
      __init__.py
      <recurso>.py          # um arquivo por recurso REST (ex. accounts.py)
    models/
      __init__.py
      <recurso>.py          # modelos SQLAlchemy
    schemas/
      __init__.py
      <recurso>.py          # schemas Pydantic (request/response)
    services/
      __init__.py
      <recurso>.py          # regras de negócio/domínio, desacopladas do router
    repositories/
      __init__.py
      <recurso>.py          # acesso a dados (queries), desacoplado do service
    core/
      config.py             # leitura de variáveis de ambiente
      logging.py            # setup de log estruturado
      errors.py             # exceções de domínio e handlers
      db.py                 # engine/session do SQLAlchemy
  tests/
    unit/
    contract/
  requirements.txt
  .env.example
  Dockerfile
```

## Convenções gerais
- Router não contém lógica de negócio: apenas parsing de request, chamada ao service e serialização de response.
- Service não conhece detalhes HTTP (status code, headers) nem SQL cru — depende do repository.
- Toda dependência externa (DB, broker) é injetada via `Depends` do FastAPI, nunca instanciada direto dentro do endpoint.
