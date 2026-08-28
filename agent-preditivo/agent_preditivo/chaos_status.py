"""Verifica se a camada de caos (specs/business/11-camada-caos.md) esta
ativa num servico, lendo `CHAOS_ENABLED` do container real via
`docker inspect` - mesmo mecanismo (subprocess, sem infraestrutura nova)
ja usado em logs_client.py para ler logs dos containers.
"""

import subprocess

CONTAINER_PREFIX = "bank-of-decoy-"


def is_chaos_enabled(service: str) -> bool:
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
