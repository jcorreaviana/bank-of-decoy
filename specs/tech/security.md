# Security

## Comunicação entre serviços
- Nesta fase (ambiente local de estudo), comunicação entre serviços internos (REST e Kafka) **não tem autenticação**.
- **Nota explícita**: em um ambiente de produção real, isso exigiria mTLS entre serviços ou, no mínimo, API key/token por serviço com rotação — a ausência de autenticação é uma simplificação deliberada de escopo de estudo, não um padrão a levar para produção.

## Dados sensíveis (CPF, documentos)
- CPF e documentos de identificação **nunca** aparecem em log, em nenhum nível (ver [logging.md](logging.md) para regras de PII em geral).
- CPF e documentos **nunca** trafegam em query string — sempre no body da requisição (query string é registrada em logs de acesso, proxies e histórico de navegador com mais facilidade que body).
- CPF armazenado em banco não é logado nem em mensagens de erro (`message` em [error-handling.md](error-handling.md) nunca inclui o valor do documento).

## Criptografia de CPF em repouso e em trânsito interno

- `cpf` é criptografado em repouso nas tabelas `onboardings` e `accounts` (ver [database.md](database.md)) — nunca fica em texto puro no banco. Criptografia simétrica (Fernet, biblioteca `cryptography`), transparente na camada de aplicação via um `TypeDecorator` do SQLAlchemy: o código de domínio sempre manipula o CPF em texto puro; a conversão para/de ciphertext acontece só na fronteira com o banco.
- A chave simétrica é fornecida via variável de ambiente `CPF_ENCRYPTION_KEY`, **igual nos dois serviços** que a usam (`onboarding-service` e `account-service`) — é a mesma chave que permite ao `account-service` decifrar o CPF recebido do `onboarding-service`. Documentada (sem valor real) no `.env.example` de cada um.
- Como Fernet não é determinístico (o mesmo texto claro gera ciphertexts diferentes a cada chamada), a unicidade de `onboardings.cpf` (ver [database.md](database.md)) não pode ser garantida por um índice sobre a coluna criptografada. Um índice único parcial separado sobre um HMAC-SHA256 determinístico do CPF (`cpf_hash`, não reversível) é quem garante essa unicidade e permite o lookup por CPF sem decifrar linha a linha.
- O endpoint interno `GET /v1/onboarding/{id}/internal` (uso exclusivo `account-service` → `onboarding-service`, sem autenticação nesta fase, mesma simplificação de escopo já registrada acima) retorna o CPF **já criptografado** (o `onboarding-service` não decifra para servir esse endpoint) — o `account-service` decifra ao consumir, usando a mesma `CPF_ENCRYPTION_KEY`, e regrava criptografado em `accounts.cpf`.

## Segredos
- Credenciais de banco, Kafka e qualquer outro segredo são fornecidos via variável de ambiente — nunca hardcoded no código-fonte.
- Cada serviço tem um `.env.example` no próprio diretório, listando todas as variáveis esperadas com valores de exemplo/placeholder (nunca valores reais ou funcionais).
- `.env` (valores reais) está no `.gitignore` de cada serviço e nunca é commitado.

## Validação de entrada
- Todo input externo (body, query params, path params) é validado via schema Pydantic antes de chegar à camada de service — nenhuma validação de negócio assume que o input já é confiável só por ter passado pelo schema.
