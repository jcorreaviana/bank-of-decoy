# 16 — Saldo, partida dobrada e e2e_id

## Contexto

O contrato original do `transaction-service` sempre previu "saldo insuficiente" como erro possível, mas o conceito nunca foi implementado. Ao corrigir isso (junto com a validação de chave de destino do passo 2), é o momento certo de resolver também uma limitação estrutural: hoje uma transferência é uma única linha na tabela `transactions`, com destino armazenado só como string de chave PIX — não é possível consultar "quantas transações essa conta recebeu", só "quantas enviou". Isso impede detectar padrão mula bidirecional (dinheiro entra e sai rapidamente da mesma conta), que é um sinal de fraude mais forte que qualquer um dos lados isolado.

## Objetivo

1. **Modelo de partida dobrada**: cada transferência gera **duas linhas** na tabela `transactions` — uma de saída (`tipo: saida`, vinculada à conta de origem) e uma de entrada (`tipo: entrada`, vinculada à conta de destino, resolvida via `pix-key-service` a partir da chave). As duas linhas compartilham um `e2e_id` (identificador único da transferência completa, inspirado no `endToEndId` real do PIX/BACEN).
2. **Saldo**: adicionar campo `saldo` (numeric, não negativo) em `accounts`, com migration. Definir saldo inicial na criação da conta (proponha um valor razoável, documente a decisão).
3. **Validação de saldo**: `POST /v1/transactions` valida se `valor` excede o saldo da conta de origem — se exceder, 422 (`SALDO_INSUFICIENTE`), e nenhuma das duas linhas é criada.
4. **Débito/crédito**: transação bem-sucedida debita o saldo da conta de origem e credita o saldo da conta de destino, atomicamente (mesma transação de banco de dados).
5. **Novo sinal de risco bidirecional**: estenda o módulo de risco compartilhado (`shared/risk_engine/`, criado na issue #8) com um sinal `entrada_saida_rapida` — dispara quando uma conta recebe uma transferência e, dentro de uma janela curta (ex. 10 minutos, mesmo padrão de `velocidade_alta`), envia uma quantia significativa para fora. Esse sinal deve poder ser avaliado tanto na linha de entrada quanto na de saída relacionada.

## Contrato afetado

`POST /v1/transactions` continua com o mesmo payload de entrada, mas a resposta deve refletir o `e2e_id` gerado. `GET /v1/transactions/{id}` deve continuar funcionando para consultar uma transação específica (defina se isso busca por id da linha de saída, id da linha de entrada, ou por `e2e_id` — documente a decisão).

## Critério de aceite

- [ ] Migration criando `saldo` em `accounts` e os campos necessários em `transactions` para partida dobrada (`e2e_id`, `tipo`, `account_id` vinculado corretamente em cada linha)
- [ ] Toda transferência bem-sucedida gera exatamente duas linhas, vinculadas pelo mesmo `e2e_id`
- [ ] Saldo debitado/creditado corretamente, atomicamente
- [ ] Transação com valor > saldo retorna 422, sem criar nenhuma linha
- [ ] Sinal `entrada_saida_rapida` implementado e testável
- [ ] Testes cobrindo os cenários (partida dobrada, saldo insuficiente, débito/crédito, novo sinal)
- [ ] Avaliação de impacto no dataset já gerado — reportar se a mudança estrutural exige regeneração completa (é esperado que sim, dado que o modelo de dados muda de forma incompatível com o que já existe)

## Sinal de risco

Categoria da mudança: regra de negócio (feature nova + mudança estrutural de modelo de dados)
Serviço(s) afetado(s): account-service e transaction-service (crítico)

## Dependências

Depende do passo 2 (validação de chave de destino, já que a partida dobrada precisa resolver a conta de destino a partir da chave).
