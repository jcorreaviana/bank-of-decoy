"""Gerador de trafego sintetico contra a API REAL (onboarding -> conta ->
chave PIX -> transacao), para a janela de operacao real dos agentes
(agent-preditivo, agent-local) contra o ambiente efemero
(docker-compose.test.yml). Ritmo moderado (nao e teste de carga) - so
existe para esta simulacao, nao faz parte do sistema em si.

Diferente de scripts/populate_volume.py (insercao direta no banco, para o
dataset de ML - issue #8), este script passa pela API/Kafka de verdade a
cada registro, de proposito: e assim que o agent-preditivo consegue
observar golden signals reais no Prometheus e logs reais nos containers.

Conta so fica pronta para gerar transacao depois que account-service
consome o evento onboarding.aprovado (Kafka, assincrono) - como nao ha
endpoint REST para achar account_id a partir de onboarding_id, este
script consulta diretamente o Postgres do account-service (leitura, sem
escrita) so para descobrir esse id - pragmatico para uma ferramenta de
simulacao, nunca faria isso em codigo de servico real.
"""

import argparse
import json
import random
import sys
import time
import uuid
from datetime import date, timedelta

import httpx
import psycopg2

ONBOARDING_URL = "http://localhost:8001/v1/onboarding"
PIXKEY_URL = "http://localhost:8003/v1/pix-keys"
TRANSACTION_URL = "http://localhost:8004/v1/transactions"
ACCOUNT_DB_DSN = "dbname=account user=bank password=bank host=localhost port=5432"

# Mesmos valores simulados de shared/risk_engine/risk_engine/onboarding.py -
# hardcoded aqui (nao importados) para este script nao depender do pacote
# instalado no venv que o executa.
IPS_BLACKLIST = ["198.51.100.66", "203.0.113.66"]
DISPOSITIVOS_BLACKLIST = ["device-blacklist-1", "device-blacklist-2"]

FRACAO_ONBOARDING_INCONSISTENTE = 0.12
FRACAO_ONBOARDING_FRAUDE = 0.03
FRACAO_TRANSACAO_SALDO_INSUFICIENTE = 0.06
FRACAO_TRANSACAO_CHAVE_INEXISTENTE = 0.06

_ACCOUNT_POLL_TIMEOUT_SECONDS = 15.0
_ACCOUNT_POLL_INTERVAL_SECONDS = 0.5


def _log(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def _cpf_sintetico(rng: random.Random) -> str:
    return f"{rng.randint(20_000_000_000, 89_999_999_999):011d}"


def _build_onboarding_payload(rng: random.Random, indice: int) -> dict:
    nome = f"Cliente Sintetico {indice}"
    documento_numero = f"SIMDOC{indice:07d}"
    data_nascimento = (date.today() - timedelta(days=rng.randint(18 * 365, 80 * 365))).isoformat()
    ip_origem = f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}"
    dispositivo_id = f"device-sintetico-{indice}"

    r = rng.random()
    if r < FRACAO_ONBOARDING_FRAUDE:
        if rng.random() < 0.5:
            ip_origem = rng.choice(IPS_BLACKLIST)
        else:
            dispositivo_id = rng.choice(DISPOSITIVOS_BLACKLIST)
    elif r < FRACAO_ONBOARDING_FRAUDE + FRACAO_ONBOARDING_INCONSISTENTE:
        nome = f"Sozinho{indice}"  # nome de uma palavra com digito -> dados_inconsistentes

    return {
        "cpf": _cpf_sintetico(rng),
        "nome": nome,
        "data_nascimento": data_nascimento,
        "email": f"sintetico{indice}@example.com",
        "telefone": f"119{indice:08d}"[-11:],
        "documento_tipo": "rg",
        "documento_numero": documento_numero,
        "dispositivo_id": dispositivo_id,
        "ip_origem": ip_origem,
    }


def _find_account_id(client: httpx.Client, onboarding_id: str) -> str | None:
    """Espera a conta ser criada pelo consumo assincrono do evento
    onboarding.aprovado. Onboardings reprovados (fraude/qualidade) nunca
    geram conta - retorna None nesse caso, esperado, nao e erro."""
    resp = client.get(f"{ONBOARDING_URL}/{onboarding_id}")
    if resp.status_code != 200 or resp.json().get("status") != "aprovado":
        return None

    deadline = time.monotonic() + _ACCOUNT_POLL_TIMEOUT_SECONDS
    conn = psycopg2.connect(ACCOUNT_DB_DSN)
    try:
        with conn.cursor() as cur:
            while time.monotonic() < deadline:
                cur.execute("SELECT id FROM accounts WHERE onboarding_id = %s", (onboarding_id,))
                row = cur.fetchone()
                if row:
                    return str(row[0])
                time.sleep(_ACCOUNT_POLL_INTERVAL_SECONDS)
    finally:
        conn.close()
    return None


def _criar_onboarding_e_conta(client: httpx.Client, rng: random.Random, indice: int, ready_accounts: list) -> None:
    payload = _build_onboarding_payload(rng, indice)
    try:
        resp = client.post(ONBOARDING_URL, json=payload, timeout=10.0)
    except httpx.HTTPError as exc:
        _log("onboarding_erro_rede", erro=str(exc))
        return

    if resp.status_code != 201:
        _log("onboarding_rejeitado", status_code=resp.status_code, body=resp.text[:300])
        return

    onboarding_id = resp.json()["id"]
    account_id = _find_account_id(client, onboarding_id)
    if account_id is None:
        _log("onboarding_sem_conta", onboarding_id=onboarding_id)
        return

    tipo = "email" if indice % 2 == 0 else "telefone"
    valor = f"sintetico{indice}@example.com" if tipo == "email" else f"119{indice:08d}"[-11:]
    try:
        pk_resp = client.post(PIXKEY_URL, json={"account_id": account_id, "tipo": tipo, "valor": valor}, timeout=10.0)
    except httpx.HTTPError as exc:
        _log("pixkey_erro_rede", erro=str(exc))
        return

    if pk_resp.status_code != 201:
        _log("pixkey_rejeitada", status_code=pk_resp.status_code, body=pk_resp.text[:300])
        return

    ready_accounts.append({"account_id": account_id, "pix_valor": valor})
    _log("conta_pronta", account_id=account_id, pix_valor=valor, total_prontas=len(ready_accounts))


def _criar_transacao(client: httpx.Client, rng: random.Random, ready_accounts: list) -> None:
    if len(ready_accounts) < 2:
        return
    origem, destino = rng.sample(ready_accounts, 2)

    r = rng.random()
    if r < FRACAO_TRANSACAO_SALDO_INSUFICIENTE:
        valor = round(rng.uniform(12_000, 30_000), 2)
        destino_valor = destino["pix_valor"]
    elif r < FRACAO_TRANSACAO_SALDO_INSUFICIENTE + FRACAO_TRANSACAO_CHAVE_INEXISTENTE:
        valor = round(rng.uniform(10, 500), 2)
        destino_valor = f"inexistente-{uuid.uuid4()}@example.com"
    else:
        valor = round(rng.uniform(10, 3_000), 2)
        destino_valor = destino["pix_valor"]

    payload = {"account_id": origem["account_id"], "pix_key_destino": destino_valor, "valor": valor}
    try:
        resp = client.post(TRANSACTION_URL, json=payload, timeout=10.0)
    except httpx.HTTPError as exc:
        _log("transacao_erro_rede", erro=str(exc))
        return

    if resp.status_code == 201:
        body = resp.json()
        _log(
            "transacao_criada",
            transaction_id=body["id"],
            status=body["status"],
            sinais=body["risco_transacao"]["sinais"],
            valor=valor,
        )
    else:
        _log("transacao_rejeitada", status_code=resp.status_code, body=resp.text[:300])


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerador de trafego sintetico via API real")
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--stop-file", type=str, required=True)
    parser.add_argument("--min-pace-seconds", type=float, default=1.5)
    parser.add_argument("--max-pace-seconds", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    ready_accounts: list[dict] = []
    indice = 0
    inicio = time.monotonic()
    stop_path = args.stop_file

    _log("inicio", duration_seconds=args.duration_seconds, stop_file=stop_path)

    with httpx.Client() as client:
        while True:
            try:
                with open(stop_path, encoding="utf-8"):
                    _log("parado_por_stop_file")
                    break
            except FileNotFoundError:
                pass

            if time.monotonic() - inicio >= args.duration_seconds:
                _log("parado_por_tempo")
                break

            indice += 1
            if len(ready_accounts) < 4 or rng.random() < 0.4:
                _criar_onboarding_e_conta(client, rng, indice, ready_accounts)
            else:
                _criar_transacao(client, rng, ready_accounts)

            time.sleep(rng.uniform(args.min_pace_seconds, args.max_pace_seconds))

    _log("fim", total_contas_prontas=len(ready_accounts))


if __name__ == "__main__":
    sys.exit(main())
