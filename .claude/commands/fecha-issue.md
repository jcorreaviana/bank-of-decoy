---
description: Ritual de fechamento de uma issue — testes, commit, changelog, fechamento no GitHub
---

Execute o ritual de fechamento de issue, na ordem, parando para confirmação do usuário nos passos que pedem:

1. **Testes**: rode a suíte de testes relevante para o que foi alterado (não necessariamente a suíte inteira do monorepo, a menos que a mudança seja transversal). Confirme que está passando antes de seguir. Se algo falhar, pare e resolva antes de continuar o ritual.

2. **Commits pendentes**: rode `git status` e `git diff` para conferir se há mudança não commitada. Se houver, commite de forma separada e significativa (não um commit único genérico juntando tudo), seguindo o padrão de mensagem já usado no projeto (ver `git log` para o estilo: título curto no formato `tipo(escopo): descrição`, corpo explicando o racional quando não for óbvio, `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`).

3. **Changelog de decisão**: pergunte ao usuário se a entrada correspondente em `docs/escopo-arquitetura.md` (seção "Histórico de decisões") precisa ser adicionada ou atualizada. Se sim, proponha o texto da entrada (nova versão `vN` ou atualização da existente) antes de aplicar.

4. **Fechamento no GitHub**: pergunte ao usuário se a issue deve ser comentada com um resumo do que foi feito e fechada via `gh issue close`. Não feche sem confirmação explícita.

5. **Lembrete final**: ao terminar, sempre encerre a resposta com:

   > Issue fechada. Rode `/clear` antes de começar a próxima tarefa, a menos que ela seja continuação direta desta.
