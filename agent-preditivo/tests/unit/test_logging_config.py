import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import agent_preditivo.logging_config as logging_config
from agent_preditivo.logging_config import configure_logging


def _reset_root_handlers() -> None:
    root = logging.getLogger()
    for h in root.handlers:
        h.close()
    root.handlers = []


def test_configure_logging_registra_stream_e_rotating_file_handler(tmp_path: Path, monkeypatch) -> None:
    log_file = tmp_path / "daemon.log"
    monkeypatch.setattr(logging_config, "_LOG_FILE", log_file)
    _reset_root_handlers()

    configure_logging("agent-preditivo", "INFO")
    root = logging.getLogger()

    stream_handlers = [
        h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
    ]
    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(stream_handlers) == 1
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename) == log_file
    assert file_handlers[0].maxBytes > 0
    assert file_handlers[0].backupCount > 0


def test_configure_logging_grava_mensagem_real_no_arquivo(tmp_path: Path, monkeypatch) -> None:
    log_file = tmp_path / "daemon.log"
    monkeypatch.setattr(logging_config, "_LOG_FILE", log_file)
    _reset_root_handlers()

    configure_logging("agent-preditivo", "INFO")
    marker = "teste-issue-79-agent-preditivo"
    logging.getLogger("test_logging_config").info(marker, extra={"context": {}})

    root = logging.getLogger()
    file_handler = next(h for h in root.handlers if isinstance(h, RotatingFileHandler))
    file_handler.flush()

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert lines, "daemon.log deveria conter ao menos uma linha apos o log acima"
    last = json.loads(lines[-1])
    assert last["message"] == marker
    assert last["service_name"] == "agent-preditivo"
