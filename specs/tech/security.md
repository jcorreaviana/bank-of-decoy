# Security

## Comunicação entre serviços
- Nesta fase (ambiente local de estudo), comunicação entre serviços internos (REST e Kafka) **não tem autenticação**.
- **Nota explícita**: em um ambiente de produção real, isso exigiria mTLS entre serviços ou, no mínimo, API key/token por serviço com rotação — a ausência de autenticação é uma simplificação deliberada de escopo de estudo, não um padrão a levar para produção.

## Dados sensíveis (CPF, documentos)
- CPF e documentos de identificação **nunca** aparecem em log, em nenhum nível (ver [logging.md](logging.md) para regras de PII em geral).
- CPF e documentos **nunca** trafegam em query string — sempre no body da requisição (query string é registrada em logs de acesso, proxies e histórico de navegador com mais facilidade que body).
- CPF armazenado em banco não é logado nem em mensagens de erro (`message` em [error-handling.md](error-handling.md) nunca inclui o valor do documento).

## Segredos
- Credenciais de banco, Kafka e qualquer outro segredo são fornecidos via variável de ambiente — nunca hardcoded no código-fonte.
- Cada serviço tem um `.env.example` no próprio diretório, listando todas as variáveis esperadas com valores de exemplo/placeholder (nunca valores reais ou funcionais).
- `.env` (valores reais) está no `.gitignore` de cada serviço e nunca é commitado.

## Validação de entrada
- Todo input externo (body, query params, path params) é validado via schema Pydantic antes de chegar à camada de service — nenhuma validação de negócio assume que o input já é confiável só por ter passado pelo schema.
