# Stack

## Linguagem e runtime
- Python 3.12+.
- FastAPI como framework web.
- Uvicorn como servidor ASGI (modo `--reload` em dev, sem reload em produção).
- SQLAlchemy como ORM/toolkit de acesso a dados.
- psycopg2-binary como driver Postgres.
- pytest como framework de testes (+ `pytest-cov`, `httpx` para testes de contrato).
- `confluent-kafka` como client Kafka (produtor e consumidor) — wheel binário disponível para Windows/Linux sem build C manual, decisão tomada na história [07-kafka-onboarding-eventos.md](../business/07-kafka-onboarding-eventos.md), primeiro uso real de Kafka no repositório.

## Ambiente virtual
- Cada microserviço tem seu próprio ambiente virtual isolado (`venv` ou `.venv` na raiz do serviço).
- Dependências declaradas em `requirements.txt` (ou `pyproject.toml`, se o serviço adotar) próprio de cada serviço.
- Nunca instalar dependências globalmente na máquina/container de desenvolvimento.

## Pacotes compartilhados (`shared/`)
- Lógica de domínio que precisa ser **idêntica** em mais de um consumidor (ex. classificação de risco, usada por onboarding-service/transaction-service e pelo populador de volume — [08-populador-volume.md](../business/08-populador-volume.md)) vive em `shared/<pacote>/`, na raiz do monorepo, como um pacote Python instalável (`pyproject.toml` próprio).
- Cada consumidor instala o pacote como dependência local editável (`-e ../shared/<pacote>` no `requirements.txt`), nunca copiando/duplicando o código.
- Um pacote em `shared/` é deliberadamente livre de banco/ORM/framework — só lógica pura, testável sem infraestrutura. Quem consome (um serviço, o populador) cuida da parte que toca banco/HTTP/Kafka.
- Build Docker: se um serviço depende de um pacote em `shared/`, seu `docker-compose.yml` usa `context: .` (raiz do monorepo) com `dockerfile: <servico>/Dockerfile` em vez de `build: ./<servico>` — o contexto de build de um serviço isolado não alcançaria `shared/`. O Dockerfile correspondente copia `shared/<pacote>` antes de instalar `requirements.txt`.
- Nenhum serviço importa o pacote `app` de outro serviço diretamente (todos usam o mesmo nome de módulo top-level - ver "Estrutura de pastas" abaixo -, colidiriam se importados no mesmo processo). Um consumidor externo ao ecossistema de serviços (ex. o populador) que precisa ler/escrever no schema de um serviço sem importar seu código usa reflexão do SQLAlchemy (`MetaData.reflect`) contra o banco já migrado, nunca import de `app.*`.

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
