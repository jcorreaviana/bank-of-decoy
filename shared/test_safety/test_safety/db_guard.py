"""Trava de seguranca contra suites de teste rodarem TRUNCATE/DELETE no
banco persistente principal por engano.

Incidente que motivou este modulo: a suite de contrato do account-service
rodou com `DATABASE_URL` apontando para o banco persistente (o mesmo usado
pelo ambiente principal) - a fixture autouse de limpeza truncou `accounts`
antes/depois de cada teste, apagando as 500.980 contas geradas pelo
populador de volume (issue #8), sem chance de recuperacao (sem backup
configurado neste projeto). pix-key-service e transaction-service escaparam
do mesmo risco por sorte (as tabelas deles estavam vazias no momento), nao
por protecao real.

Por que a checagem nao pode se basear em host/porta/nome do banco: por
decisao de arquitetura (specs/business/16-saldo-partida-dobrada.md, v12 de
docs/escopo-arquitetura.md), o ambiente efemero de teste
(docker-compose.test.yml) substitui o ambiente principal reaproveitando as
MESMAS portas e os MESMOS nomes de banco - as duas `DATABASE_URL` sao
indistinguiveis textualmente por design. A unica protecao confiavel e um
opt-in explicito: quem roda a suite precisa confirmar, fora do codigo, que
o banco apontado e descartavel.
"""

import os


class UnsafeTestDatabaseError(RuntimeError):
    """Levantado quando uma suite de teste tenta truncar/limpar tabelas sem
    a confirmacao explicita de que o banco alvo e descartavel."""


def require_disposable_database(database_url: str) -> None:
    """Aborta a suite ANTES de qualquer TRUNCATE/DELETE se a variavel de
    ambiente `TESTING` nao estiver setada como `"true"`. Chamar no primeiro
    passo de toda fixture autouse que limpa tabelas (specs/tech/testing.md)."""
    if os.environ.get("TESTING") != "true":
        raise UnsafeTestDatabaseError(
            "Suite de teste tentou truncar/limpar tabelas sem TESTING=true "
            "no ambiente. Isso e uma protecao contra apagar dados do banco "
            "persistente principal por engano (specs/tech/testing.md) - "
            "confirme que DATABASE_URL aponta para um banco descartavel "
            "(docker-compose.test.yml ou um banco de teste dedicado, nunca "
            "o volume persistente principal) e so entao exporte TESTING=true. "
            f"DATABASE_URL atual: {database_url}"
        )
