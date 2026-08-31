"""Logging estruturado (specs/tech/logging.md), mesmo padrao (JSON de uma
linha, campos obrigatorios) usado nos 4 servicos de dominio
(ex. account-service/app/core/logging.py) - duplicado aqui em vez de
compartilhado porque o restante do projeto ja segue essa convencao (cada
componente isolado em sua propria pasta, sem acoplamento de codigo entre
servicos/agentes, docs/escopo-arquitetura.md v2).

Diferenca do padrao de servico HTTP: nao ha requisicao entrante para
carimbar um `trace_id` - aqui o `trace_id` e gerado uma vez por ciclo de
polling (`new_trace_id()`, chamado no inicio de `run_cycle`) e vale para
todos os logs emitidos durante aquele ciclo, permitindo reconstruir a
historia de um ciclo completo so lendo o log."""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

# agent-preditivo/daemon.log (irma do pacote agent_preditivo/, nao dentro
# dele) - caminho absoluto derivado do proprio arquivo para nao depender do
# cwd de onde o operador inicia o daemon (issue #79: ate aqui "daemon.log"
# so existia por convencao de redirecionar o stdout manualmente no terminal).
_LOG_FILE = Path(__file__).resolve().parent.parent / "daemon.log"
_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB por arquivo
_LOG_BACKUP_COUNT = 5  # daemon.log + ate 5 arquivos antigos (~50 MiB retidos no total)


def new_trace_id() -> str:
    """Gera e ativa um `trace_id` novo para o ciclo que esta comecando."""
    trace_id = str(uuid.uuid4())
    _trace_id_var.set(trace_id)
    return trace_id


def get_trace_id() -> str:
    return _trace_id_var.get() or ""


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
        payload = {
            "timestamp": timestamp,
            "service_name": self.service_name,
            "level": record.levelname,
            "trace_id": getattr(record, "trace_id", None) or get_trace_id(),
            "message": record.getMessage(),
            "context": getattr(record, "context", {}),
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(service_name: str, log_level: str) -> None:
    # Ao contrario dos 4 servicos de dominio (rodam em containers Linux,
    # stdout ja e UTF-8), estes agentes rodam nativamente no Windows, onde
    # o stdout default e cp1252 - sem isso, "ção"/"í"/etc no `message`
    # (json.dumps(..., ensure_ascii=False)) grava bytes cp1252 que um
    # consumidor de log (que espera UTF-8, specs/tech/logging.md) le
    # corrompidos, mesmo sem lançar excecao aqui (mesma classe de bug ja
    # documentada em agent_local/github_client.py para saida do `gh`).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    formatter = JsonFormatter(service_name)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    # Rotacao por tamanho, nao por horario fixo: um ciclo de polling varia
    # de segundos a dezenas de minutos (chamada ao Ollama/Prometheus), entao
    # um corte por horario (ex. meia-noite) seria arbitrario em relacao ao
    # ciclo; por tamanho (10 MiB x 5 arquivos = ate ~50 MiB retidos) e
    # previsivel independente de quanto tempo o daemon roda continuamente.
    file_handler = RotatingFileHandler(
        _LOG_FILE, maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [stream_handler, file_handler]
    root.setLevel(log_level.upper())
