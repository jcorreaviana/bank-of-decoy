from agent_preditivo.logs_client import LogEntry, count_repeated_critical_or_error


def _log(level: str, message: str, chaos_injected: bool = False) -> LogEntry:
    context = {"chaos_injected": True} if chaos_injected else {}
    return LogEntry(timestamp="", service_name="x", level=level, trace_id="", message=message, context=context, raw="")


def test_count_repeated_ignora_entradas_marcadas_como_chaos() -> None:
    """Regressao critica (specs/business/21-filtro-caos-pipeline-agentes.md):
    o log ERROR gerado pelo handler generico quando a camada de caos
    injeta failure_type=500 carrega context.chaos_injected=true - nao pode
    poluir o threshold de erro repetido com ruido esperado."""
    entries = [_log("ERROR", "falha simulada", chaos_injected=True) for _ in range(5)]

    assert count_repeated_critical_or_error(entries) == {}


def test_count_repeated_conta_normalmente_entradas_sem_chaos() -> None:
    entries = [_log("ERROR", "falha real") for _ in range(3)]

    assert count_repeated_critical_or_error(entries) == {"ERROR:falha real": 3}


def test_count_repeated_mistura_chaos_e_real_conta_so_o_real() -> None:
    entries = [
        _log("ERROR", "falha real"),
        _log("ERROR", "falha real"),
        _log("ERROR", "falha simulada", chaos_injected=True),
        _log("ERROR", "falha simulada", chaos_injected=True),
        _log("ERROR", "falha simulada", chaos_injected=True),
    ]

    assert count_repeated_critical_or_error(entries) == {"ERROR:falha real": 2}
