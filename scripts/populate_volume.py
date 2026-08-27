#!/usr/bin/env python
"""Populador de volumetria (specs/business/08-populador-volume.md, issue #8).

Gera onboarding -> conta -> chave PIX -> transacoes em massa, direto nos
quatro bancos (sem passar pela API/Kafka - inviavel no volume de centenas
de milhares de contas / dezenas de milhoes de transacoes), reusando a
MESMA logica de classificacao de risco dos servicos reais via o pacote
compartilhado `risk_engine` (shared/risk_engine).

Uso:
    python populate_volume.py --seed 20260826 --onboardings 505000
    python populate_volume.py --seed 1 --onboardings 10000   # amostra menor

Falha tecnica simulada (5%-10% de transacoes com status "falha", prevista
na spec original) e DELIBERADAMENTE deixada de fora desta execucao -
adiada para a Fase 2, decisao confirmada com o autor da issue.
"""

import argparse
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone

from db_writer import ServiceDatabase, account_row, chunked, onboarding_row, pix_key_row, transaction_row
from generation import gerar_conta_e_pix_key, gerar_onboarding, gerar_transacoes

SERVICE_NAME = "populate-volume"

DEFAULT_SEED = 20260826
DEFAULT_ONBOARDINGS = 505_000
"""505k a 0.5%-1% de reprovacao ainda deixa >= 500k contas aprovadas
(pior caso 1%: 505_000 * 0.99 = 499_950 - por isso um pouco de folga
extra abaixo em vez de exatos 505_000/0.99)."""


def _log(run_id: str, level: str, message: str, **context) -> None:
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    payload = {
        "timestamp": timestamp,
        "service_name": SERVICE_NAME,
        "level": level,
        "trace_id": run_id,
        "message": message,
        "context": context,
    }
    print(json.dumps(payload, ensure_ascii=False), file=sys.stdout, flush=True)


def _database_url(env_var: str, db_host: str, db_name: str) -> str:
    return os.environ.get(env_var) or f"postgresql://bank:bank@{db_host}:5432/{db_name}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"seed reprodutivel (default {DEFAULT_SEED})")
    parser.add_argument(
        "--onboardings",
        type=int,
        default=DEFAULT_ONBOARDINGS,
        help=f"total de onboardings a gerar (default {DEFAULT_ONBOARDINGS}, produz 500k+ contas)",
    )
    parser.add_argument("--db-host", default="localhost", help="host Postgres (default localhost)")
    parser.add_argument("--batch-size", type=int, default=5_000, help="tamanho de lote onboarding/conta/pix-key")
    parser.add_argument("--transaction-batch-size", type=int, default=20_000, help="tamanho de lote de transacoes")
    parser.add_argument("--log-interval", type=int, default=10_000, help="log de progresso a cada N onboardings")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    run_id = str(uuid.uuid4())
    inicio = time.monotonic()

    _log(
        run_id,
        "INFO",
        "Populador de volumetria iniciado.",
        seed=args.seed,
        onboardings_alvo=args.onboardings,
    )

    onboarding_db = ServiceDatabase(
        _database_url("ONBOARDING_DATABASE_URL", args.db_host, "onboarding"), ["onboardings"]
    )
    account_db = ServiceDatabase(_database_url("ACCOUNT_DATABASE_URL", args.db_host, "account"), ["accounts"])
    pix_key_db = ServiceDatabase(_database_url("PIX_KEY_DATABASE_URL", args.db_host, "pix_key"), ["pix_keys"])
    transaction_db = ServiceDatabase(
        _database_url("TRANSACTION_DATABASE_URL", args.db_host, "transaction"), ["transactions"]
    )

    rng = random.Random(args.seed)
    agora = datetime.now(timezone.utc)

    onboarding_batch: list[dict] = []
    account_batch: list[dict] = []
    pix_key_batch: list[dict] = []
    transaction_batch: list[dict] = []

    total_onboardings = 0
    total_reprovado_qualidade = 0
    total_reprovado_fraude = 0
    total_contas = 0
    total_pix_keys = 0
    total_transacoes = 0
    total_transacoes_suspeitas = 0

    def flush_transactions() -> None:
        nonlocal transaction_batch
        if transaction_batch:
            transaction_db.bulk_insert("transactions", transaction_batch)
            transaction_batch = []

    for indice in range(args.onboardings):
        onboarding = gerar_onboarding(rng, indice, agora)
        onboarding_batch.append(onboarding_row(onboarding))
        total_onboardings += 1

        if onboarding.status == "reprovado_qualidade":
            total_reprovado_qualidade += 1
        elif onboarding.status == "reprovado_fraude":
            total_reprovado_fraude += 1
        else:
            account, pix_key = gerar_conta_e_pix_key(rng, indice, onboarding)
            account_batch.append(account_row(account))
            pix_key_batch.append(pix_key_row(pix_key))
            total_contas += 1
            total_pix_keys += 1

            for transacao in gerar_transacoes(rng, account, agora):
                transaction_batch.append(transaction_row(transacao))
                total_transacoes += 1
                if transacao.status == "suspeita":
                    total_transacoes_suspeitas += 1

                if len(transaction_batch) >= args.transaction_batch_size:
                    flush_transactions()

        if len(onboarding_batch) >= args.batch_size:
            onboarding_db.bulk_insert("onboardings", onboarding_batch)
            onboarding_batch = []
        if len(account_batch) >= args.batch_size:
            account_db.bulk_insert("accounts", account_batch)
            account_batch = []
        if len(pix_key_batch) >= args.batch_size:
            pix_key_db.bulk_insert("pix_keys", pix_key_batch)
            pix_key_batch = []

        if (indice + 1) % args.log_interval == 0:
            decorrido = time.monotonic() - inicio
            _log(
                run_id,
                "INFO",
                "Progresso do populador.",
                onboardings_processados=indice + 1,
                contas_criadas=total_contas,
                transacoes_criadas=total_transacoes,
                segundos_decorridos=round(decorrido, 1),
            )

    # flush final de qualquer resto abaixo do tamanho de lote
    if onboarding_batch:
        onboarding_db.bulk_insert("onboardings", onboarding_batch)
    if account_batch:
        account_db.bulk_insert("accounts", account_batch)
    if pix_key_batch:
        pix_key_db.bulk_insert("pix_keys", pix_key_batch)
    flush_transactions()

    for db in (onboarding_db, account_db, pix_key_db, transaction_db):
        db.dispose()

    duracao_segundos = time.monotonic() - inicio
    percentual_reprovacao = (
        (total_reprovado_qualidade + total_reprovado_fraude) / total_onboardings if total_onboardings else 0.0
    )
    percentual_suspeita = total_transacoes_suspeitas / total_transacoes if total_transacoes else 0.0

    _log(
        run_id,
        "INFO",
        "Populador de volumetria concluido.",
        seed=args.seed,
        total_onboardings=total_onboardings,
        total_reprovado_qualidade=total_reprovado_qualidade,
        total_reprovado_fraude=total_reprovado_fraude,
        total_contas=total_contas,
        total_pix_keys=total_pix_keys,
        total_transacoes=total_transacoes,
        total_transacoes_suspeitas=total_transacoes_suspeitas,
        percentual_reprovacao=round(percentual_reprovacao * 100, 4),
        percentual_suspeita=round(percentual_suspeita * 100, 4),
        duracao_segundos=round(duracao_segundos, 1),
    )

    print("\n=== Resumo do populador de volumetria ===")
    print(f"seed:                          {args.seed}")
    print(f"onboardings gerados:           {total_onboardings:,}")
    print(
        f"reprovados (qualidade+fraude): {total_reprovado_qualidade + total_reprovado_fraude:,} "
        f"({percentual_reprovacao:.4%}) - alvo [0.5%, 1%]"
    )
    print(f"contas criadas:                {total_contas:,}")
    print(f"chaves pix criadas:            {total_pix_keys:,}")
    print(f"transacoes criadas:            {total_transacoes:,}")
    print(f"transacoes suspeitas:          {total_transacoes_suspeitas:,} ({percentual_suspeita:.4%}) - alvo [1%, 2%]")
    print(f"tempo total:                   {duracao_segundos:.1f}s")


if __name__ == "__main__":
    main()
