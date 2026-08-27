"""Loop de polling do agente preditivo - roda um ciclo de deteccao de bug
(sobre o ambiente principal, via Prometheus/logs reais) e um ciclo de
deteccao de oportunidade (sobre o ambiente efemero de teste, via API real)
a cada `PREDICTIVE_AGENT_INTERVAL_SECONDS` (default 300)
(specs/business/13-agente-preditivo-registro.md).
"""

import argparse
import logging
import time
import traceback

from notifications import notify_agent_error

from agent_preditivo.bug_detection import detect_bugs_for_service
from agent_preditivo.config import get_settings
from agent_preditivo.opportunity_detection import run_opportunity_battery, save_scenario_journey
from agent_preditivo.registration_agent import register_bug, register_opportunity

logger = logging.getLogger(__name__)


def run_bug_cycle() -> list[int]:
    settings = get_settings()
    issue_numbers = []
    for service in settings.services:
        for signal in detect_bugs_for_service(service):
            issue_number = register_bug(signal)
            if issue_number is not None:
                issue_numbers.append(issue_number)
    return issue_numbers


def run_opportunity_cycle(api_base_urls: dict[str, str] | None = None) -> list[int]:
    issue_numbers = []
    findings = run_opportunity_battery(api_base_urls)
    for finding in findings:
        scenario_path = None
        if finding.veredito == "GAP":
            scenario_path = save_scenario_journey(finding, steps=[finding.observed_behavior])
        issue_number = register_opportunity(finding, scenario_path)
        if issue_number is not None:
            issue_numbers.append(issue_number)
    return issue_numbers


def run_cycle(include_opportunity: bool = True) -> None:
    """Erro nao tratado em um ciclo (Ollama indisponivel, falha de rede,
    etc.) e notificado e logado, mas NAO derruba o processo - um daemon de
    polling deve sobreviver a falhas transitorias e tentar de novo no
    proximo ciclo; a notificacao e o mecanismo de alerta para intervencao
    humana, nao um crash (specs/business/20-notificacoes-discord-agentes.md,
    evento 4)."""
    try:
        run_bug_cycle()
        if include_opportunity:
            run_opportunity_cycle()
    except Exception as exc:
        logger.error(
            "Erro nao tratado no ciclo do agent-preditivo.",
            extra={"context": {"stack_trace": traceback.format_exc()}},
        )
        notify_agent_error("agent-preditivo", str(exc), context={"traceback": traceback.format_exc()[-500:]})


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente preditivo - polling de bug/oportunidade")
    parser.add_argument("--once", action="store_true", help="roda um único ciclo e encerra (para validação/CI)")
    parser.add_argument("--skip-opportunity", action="store_true", help="pula a bateria de oportunidade nesse ciclo")
    args = parser.parse_args()

    settings = get_settings()
    if args.once:
        run_cycle(include_opportunity=not args.skip_opportunity)
        return

    while True:
        run_cycle(include_opportunity=not args.skip_opportunity)
        time.sleep(settings.interval_seconds)


if __name__ == "__main__":
    main()
