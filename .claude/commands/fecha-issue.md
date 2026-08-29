---
description: Ritual de fechamento de uma issue — testes, commit, changelog, fechamento no GitHub
---

Execute o ritual de fechamento de issue, na ordem, parando para confirmação do usuário nos passos que pedem:

1. **Testes**: rode a suíte de testes relevante para o que foi alterado (não necessariamente a suíte inteira do monorepo, a menos que a mudança seja transversal). Confirme que está passando antes de seguir. Se algo falhar, pare e resolva antes de continuar o ritual.

2. **Commits pendentes**: rode `git status` e `git diff` para conferir se há mudança não commitada. Se houver, commite de forma separada e significativa (não um commit único genérico juntando tudo), seguindo o padrão de mensagem já usado no projeto (ver `git log` para o estilo: título curto no formato `tipo(escopo): descrição`, corpo explicando o racional quando não for óbvio, `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`).

3. **Critério de aceite**: leia o corpo da issue no GitHub (`gh issue view <n> --json body`) e verifique item a item a seção "Critério de aceite" contra o que foi de fato implementado, testado ou validado manualmente:
   - Para cada item, identifique a evidência concreta que o sustenta (teste automatizado passando, código implementado e revisado, validação manual feita nesta sessão). Não aceite a palavra do commit message sozinha como evidência suficiente — se o commit afirma uma validação "real"/manual sem trilha reproduzível no repositório, trate como não confirmado.
   - Itens que pedem confirmação visual/manual explícita (ex. "validado no dashboard Grafana", "confirmado visualmente") exigem que o usuário veja e confirme nesta sessão — não podem ser marcados só com base em análise de código ou dado de API equivalente (ex. Prometheus no lugar do Grafana). Veja o precedente da issue #11 (commit `ba5d34b`): o checkbox de validação no Grafana só foi marcado depois de confirmação visual explícita do usuário, mesmo já havendo validação via API do Prometheus.
   - Marque via `gh issue edit <n> --body-file <arquivo>` (reescrevendo o corpo com os checkboxes cumpridos como `[x]`) somente os itens genuinamente cumpridos.
   - Se um item não puder ser confirmado como cumprido, **pare o ritual e avise o usuário** explicitamente qual item ficou pendente e por quê — não feche a issue com critério de aceite pendente sem essa conversa explícita. Se o item descreve um mecanismo que foi implementado de forma diferente da especificada (ex. controle alternativo em vez do originalmente pedido), proponha reescrever o texto do critério para refletir a decisão real antes de marcar, e peça confirmação do usuário sobre a mudança de escopo.
   - Itens deixados pendentes por decisão do usuário (tratados como débito técnico em vez de bloqueio) devem ser registrados em um comentário na issue, não silenciosamente ignorados.

4. **Changelog de decisão**: pergunte ao usuário se a entrada correspondente em `docs/escopo-arquitetura.md` (seção "Histórico de decisões") precisa ser adicionada ou atualizada. Se sim, proponha o texto da entrada (nova versão `vN` ou atualização da existente) antes de aplicar.

5. **Fechamento no GitHub**: pergunte ao usuário se a issue deve ser comentada com um resumo do que foi feito e fechada via `gh issue close`. Não feche sem confirmação explícita. Não feche uma issue com item do critério de aceite genuinamente pendente sem esse pendente ter sido reconhecido explicitamente pelo usuário (reabertura, débito técnico registrado, ou reescrita do critério) no passo 3.

6. **Lembrete final**: ao terminar, sempre encerre a resposta com:

   > Issue fechada. Rode `/clear` antes de começar a próxima tarefa, a menos que ela seja continuação direta desta.
