# Bank of Decoy

Monorepo de microserviços (`onboarding-service`, `account-service`, `pix-key-service`, `transaction-service`) com Postgres, Kafka, Prometheus e Grafana como infraestrutura compartilhada. Specs do projeto em [specs/](specs/).

## Configuração inicial

Antes de subir qualquer um dos ambientes abaixo, copie `.env.example` para `.env` na raiz e preencha `CPF_ENCRYPTION_KEY` com uma chave real (gere com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) — `docker-compose.yml`/`docker-compose.test.yml` leem esse arquivo automaticamente. `.env` nunca é commitado (specs/tech/security.md, specs/business/18-correcao-vazamento-chave.md).

## Ambientes de desenvolvimento local

Existem dois arquivos de compose na raiz, e eles **não rodam em paralelo** — ambos usam as mesmas portas:

- `docker-compose.yml`: ambiente principal, com volume nomeado persistente para o Postgres (`postgres_data`). Dados sobrevivem a `docker-compose down`/`up`.
- `docker-compose.test.yml`: ambiente efêmero, idêntico ao principal exceto que o Postgres **não** tem volume nomeado — cada `up` começa com bancos vazios (migrations rodam do zero). Útil para testes de ponta a ponta que não podem depender de estado deixado por execuções anteriores.

### Alternar entre os dois

Antes de subir um, derrube o outro:

```bash
# do principal para o de teste
docker-compose down
docker-compose -f docker-compose.test.yml up -d

# de volta ao principal
docker-compose -f docker-compose.test.yml down
docker-compose up -d
```

`docker-compose down` sem `-v` preserva o volume `postgres_data` do ambiente principal — os dados persistentes não são afetados por um ciclo no ambiente de teste.
