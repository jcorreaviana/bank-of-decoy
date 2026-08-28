# bank-of-decoy

`docs/escopo-arquitetura.md` é a fonte de verdade do projeto (histórico de decisões, arquitetura, specs pendentes) — consulte-o sempre que houver dúvida de contexto ou decisão arquitetural. Não recole o conteúdo dele aqui nem em outros arquivos; referencie o arquivo.

## Objetivo do projeto

Simulação de domínio PIX (onboarding → conta → chaves PIX → transações) combinada com injeção de caos e engenharia agêntica, com três frentes de valor: gerar um dataset realista de fraude para modelagem futura, testar resiliência a falhas comuns de produção, e construir agentes autônomos que detectam problemas, corrigem código e decidem sobre subida com base em score de risco.

## Convenção spec-driven

Toda história de negócio tem spec própria em `specs/business/`. Specs técnicas transversais (stack, logging, database, error-handling, api-conventions, testing, observability, messaging, security, infrastructure) ficam em `specs/tech/`. Uma issue no GitHub por história.

## Gestão de contexto

Ao concluir uma issue ou tarefa fechada, sugira ativamente rodar `/clear` antes de começar a próxima — a menos que a próxima tarefa seja continuação direta do mesmo trabalho, caso em que sugira `/compact` em vez de deixar o contexto crescer sem controle.

Ao terminar uma issue, use `/fecha-issue` como fluxo padrão de fechamento.
