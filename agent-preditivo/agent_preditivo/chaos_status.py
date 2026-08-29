"""Verifica se a camada de caos (specs/business/11-camada-caos.md) esta
ativa num servico.

Fonte primaria (issue #57): `GET /internal/chaos/status`
(shared/chaos/chaos/router.py) - reflete o estado EFETIVO do servico,
incluindo o override em runtime da issue #51 (`POST /internal/chaos/config`,
usado pelo chaos-orchestrator da issue #53 e pela janela de 2h da issue
#54). Achado real que motivou isso: o mecanismo antigo (abaixo) so lia a
variavel de ambiente estatica `CHAOS_ENABLED`, nunca o override em
runtime - caos ativado exclusivamente via `POST` (exatamente como o
chaos-orchestrator opera) nunca era detectado como ativo, quebrando a
label `chaos-test` em issues abertas durante esse tipo de ativacao.

Fallback (mecanismo original, issue #21): `docker inspect` na variavel de
ambiente `CHAOS_ENABLED` do container - usado quando a chamada HTTP nao
pode ser feita/confiada (token `CHAOS_INTERNAL_TOKEN` nao configurado,
endpoint indisponivel, erro de rede), para nao quebrar ambientes que ainda
nao tem o token configurado no agent-preditivo.
"""

import os
import subprocess

import httpx

CONTAINER_PREFIX = "bank-of-decoy-"
TOKEN_ENV_VAR = "CHAOS_INTERNAL_TOKEN"
TOKEN_HEADER = "X-Internal-Token"
STATUS_TIMEOUT_SECONDS = 5.0


def _is_chaos_enabled_via_status_endpoint(base_url: str) -> bool | None:
    """`None` = a chamada nao pode ser confiada (token ausente, erro de
    rede, resposta invalida) - quem chama cai para `docker inspect` nesse
    caso, nunca interpreta `None` como "desligado"."""
    token = os.environ.get(TOKEN_ENV_VAR, "")
    if not token:
        return None
    try:
        response = httpx.get(
            f"{base_url}/internal/chaos/status",
            headers={TOKEN_HEADER: token},
            timeout=STATUS_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        return bool(response.json()["enabled"])
    except (ValueError, KeyError):
        return None


def _is_chaos_enabled_via_docker_inspect(service: str) -> bool:
    """Retorna False se a checagem falhar por qualquer motivo (docker
    ausente, container parado, comando com erro) - um falso negativo aqui
    so significa que uma issue de caos fica sem a marcacao (tratada como
    bug normal, comportamento pre-existente); um falso positivo marcaria
    um bug real como simulado, escondendo-o do agente local. Entre os
    dois, o falso negativo e o erro seguro."""
    container = f"{CONTAINER_PREFIX}{service}"
    try:
        result = subprocess.run(
            ["docker", "inspect", container, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        return False

    if result.returncode != 0:
        return False

    return any(line.strip() == "CHAOS_ENABLED=true" for line in result.stdout.splitlines())


def is_chaos_enabled(service: str, base_url: str | None = None) -> bool:
    """`base_url` (ex. `http://localhost:8002`) e opcional para manter
    compatibilidade com chamadores que ainda nao passam a URL do servico
    (ex. scripts/validate_chaos_pipeline_e2e.sh) - nesse caso, so o
    mecanismo antigo (docker inspect) e usado."""
    if base_url is not None:
        result = _is_chaos_enabled_via_status_endpoint(base_url)
        if result is not None:
            return result
    return _is_chaos_enabled_via_docker_inspect(service)
