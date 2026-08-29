"""chaos-orchestrator (issue #53, specs/business/24-camada-caos-avancada.md) -
runner Python standalone (sem framework web) que le um cenario YAML
(scenario.py) descrevendo uma timeline de ativacoes de caos e chama
`POST /internal/chaos/config` (issue #51) de cada servico no momento certo,
via chaos_client.py.

Uso:
    CHAOS_INTERNAL_TOKEN=... python orchestrator.py scenarios/account_and_queue_cascade.yaml

Decisoes de desenho (confirmadas com o usuario):
- Cada POST substitui por completo o estado do servico (nao acumula -
  shared/chaos/chaos/runtime_config.py, `_RuntimeConfigStore.set()`). Duas
  ativacoes sobrepostas no MESMO servico, se enviadas como dois POSTs
  independentes, fariam a segunda apagar a primeira. Este modulo evita isso
  rastreando o estado ativo por servico (`Orchestrator._active`) e fundindo
  `failure_types`/`params` numa unica chamada sempre que houver sobreposicao.
- Toda ativacao/reconfiguracao envia `duration_seconds` (o quanto falta ate o
  fim da JANELA MAIS LONGA ainda ativa naquele servico, mais uma margem de
  seguranca) - um teto que o proprio servico aplica sozinho
  (chaos/runtime_config.py `expires_at`). Isso cobre o caso de o processo do
  orquestrador ser morto abruptamente (SIGKILL) sem chance de rodar o
  desligamento explicito: o servico se auto-desliga de qualquer forma, um
  pouco depois do previsto, em vez de ficar com caos ativo para sempre.
- SIGINT/SIGTERM (Ctrl+C) interrompem a timeline o quanto antes (sleep em
  fatias curtas, verificando um flag) e disparam desligamento explicito de
  tudo que estiver ativo naquele momento - mesmo caminho de limpeza usado ao
  fim natural da timeline (bloco `finally`, idempotente).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from chaos_client import TOKEN_ENV_VAR, post_chaos_config
from scenario import Scenario, TimelineStep, load_scenario

SERVICE_NAME = "chaos-orchestrator"

# Margem somada ao teto de duration_seconds enviado a cada servico, para
# absorver jitter de agendamento/rede entre o momento em que o orquestrador
# calcula o teto e o momento em que o desligamento explicito de fato chega -
# sem isso, uma corrida poderia deixar o override expirar no servico um
# instante antes do nosso proprio POST de desligamento (inofensivo, so
# redundante) ou, pior, o inverso nunca acontece por design (o teto e sempre
# calculado para vencer DEPOIS do fim previsto).
SAFETY_MARGIN_SECONDS = 60.0

# Granularidade do sleep interrompivel - o quao rapido Ctrl+C e percebido.
_SLEEP_CHUNK_SECONDS = 1.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def default_log(level: str, message: str, *, trace_id: str, context: dict | None = None) -> None:
    """JSON de linha unica em stdout, campos obrigatorios de
    specs/tech/logging.md (timestamp/service_name/level/trace_id/message/
    context) - trace_id e o mesmo para toda a execucao do cenario (um
    "ciclo", no vocabulario daquela spec para processos sem requisicao
    HTTP entrante)."""
    print(
        json.dumps(
            {
                "timestamp": _utc_now_iso(),
                "service_name": SERVICE_NAME,
                "level": level,
                "trace_id": trace_id,
                "message": message,
                "context": context or {},
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


class Clock:
    """Abstrai `time.monotonic`/`time.sleep` para o motor da timeline poder
    ser testado sem esperar minutos reais (requisito de teste da issue #53) -
    testes injetam uma fake que avanca o relogio instantaneamente."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def sleep_until(self, target: float, *, should_stop: Callable[[], bool]) -> None:
        while not should_stop():
            remaining = target - self.now()
            if remaining <= 0:
                return
            self.sleep(min(_SLEEP_CHUNK_SECONDS, remaining))


PostFn = Callable[..., dict]


class Orchestrator:
    def __init__(
        self,
        scenario: Scenario,
        *,
        token: str,
        post_fn: PostFn = post_chaos_config,
        clock: Clock | None = None,
        log_fn: Callable[..., None] = default_log,
        safety_margin_seconds: float = SAFETY_MARGIN_SECONDS,
    ) -> None:
        self.scenario = scenario
        self.token = token
        self.post_fn = post_fn
        self.clock = clock or Clock()
        self.log = log_fn
        self.safety_margin_seconds = safety_margin_seconds
        self.trace_id = str(uuid.uuid4())
        self._active: dict[str, dict[str, TimelineStep]] = {}
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        start = self.clock.now()
        events = self._build_events()

        self.log(
            "INFO",
            f"Iniciando cenario de caos '{self.scenario.name}'.",
            trace_id=self.trace_id,
            context={"scenario": self.scenario.name, "passos": len(self.scenario.steps)},
        )
        try:
            for event_minute, kind, step in events:
                if self._stop_requested:
                    break
                target = start + event_minute * 60.0
                self.clock.sleep_until(target, should_stop=lambda: self._stop_requested)
                if self._stop_requested:
                    break
                if kind == "activate":
                    self._activate(step, start)
                else:
                    self._deactivate(step, start)

            if self._stop_requested:
                self.log(
                    "WARNING",
                    "Execucao interrompida antes do fim da timeline - desligando o que ainda estiver ativo.",
                    trace_id=self.trace_id,
                    context={"scenario": self.scenario.name},
                )
        finally:
            self._shutdown_all()
            self.log(
                "INFO",
                f"Cenario de caos '{self.scenario.name}' finalizado.",
                trace_id=self.trace_id,
                context={"scenario": self.scenario.name},
            )

    def _build_events(self) -> list[tuple[float, str, TimelineStep]]:
        events: list[tuple[float, str, TimelineStep]] = []
        for step in self.scenario.steps:
            events.append((step.start_minute, "activate", step))
            events.append((step.end_minute, "deactivate", step))
        # Em empate no mesmo minuto, desligamentos antes de ativacoes - libera
        # estado antes de qualquer fusao nova precisar dele.
        events.sort(key=lambda e: (e[0], 0 if e[1] == "deactivate" else 1))
        return events

    def _merge_active(self, service: str) -> tuple[list[str], dict]:
        active = self._active.get(service, {})
        merged_types = sorted(active.keys())
        # TimelineStep tem um campo dict (`params`) - nao e hasheavel, entao
        # dedup por identidade (id()) em vez de set(), que exigiria hash().
        distinct_steps = {id(step): step for step in active.values()}.values()
        merged_params: dict = {}
        for owning_step in sorted(distinct_steps, key=lambda s: s.start_minute):
            merged_params.update(owning_step.params)
        return merged_types, merged_params

    def _reconfigure(self, service: str, *, action: str, triggering_step: TimelineStep, start: float) -> None:
        active = self._active.get(service, {})
        if not active:
            self._post(service, {"enabled": False}, action=action, triggering_step=triggering_step)
            self._active.pop(service, None)
            return

        merged_types, merged_params = self._merge_active(service)
        now_minute = (self.clock.now() - start) / 60.0
        latest_end = max(s.end_minute for s in active.values())
        duration_seconds = max((latest_end - now_minute) * 60.0, 0.0) + self.safety_margin_seconds

        payload = {
            "enabled": True,
            "failure_types": merged_types,
            "duration_seconds": duration_seconds,
            **merged_params,
        }
        self._post(service, payload, action=action, triggering_step=triggering_step)

    def _activate(self, step: TimelineStep, start: float) -> None:
        active = self._active.setdefault(step.service, {})
        for failure_type in step.failure_types:
            active[failure_type] = step
        self._reconfigure(step.service, action="ativado", triggering_step=step, start=start)

    def _deactivate(self, step: TimelineStep, start: float) -> None:
        active = self._active.get(step.service, {})
        for failure_type in step.failure_types:
            if active.get(failure_type) is step:
                active.pop(failure_type, None)
        self._reconfigure(step.service, action="desligado", triggering_step=step, start=start)

    def _post(self, service: str, payload: dict, *, action: str, triggering_step: TimelineStep) -> None:
        base_url = self.scenario.service_urls[service]
        context = {
            "servico": service,
            "tipos_falha": triggering_step.failure_types,
            "start_minute": triggering_step.start_minute,
            "duration_minutes": triggering_step.duration_minutes,
            "payload": payload,
        }
        try:
            self.post_fn(base_url, payload, token=self.token)
        except httpx.HTTPError as exc:
            self.log(
                "ERROR",
                f"Falha ao chamar POST /internal/chaos/config em {service} (acao: {action}) - seguindo para o proximo passo.",
                trace_id=self.trace_id,
                context={**context, "erro": str(exc)},
            )
            return

        self.log(
            "INFO",
            f"Caos {action} em {service}.",
            trace_id=self.trace_id,
            context=context,
        )

    def _shutdown_all(self) -> None:
        """Chamado sempre ao final de run() (fim natural ou interrupcao) -
        desliga explicitamente qualquer servico que ainda tenha algo ativo.
        No caminho feliz isso e um no-op (a ultima etapa da timeline de cada
        servico ja e um desligamento); so tem efeito real quando a execucao
        foi interrompida no meio (Ctrl+C)."""
        for service in list(self._active.keys()):
            active = self._active.get(service, {})
            if not active:
                continue
            try:
                self.post_fn(self.scenario.service_urls[service], {"enabled": False}, token=self.token)
            except httpx.HTTPError as exc:
                self.log(
                    "ERROR",
                    f"Falha ao desligar caos em {service} durante o encerramento - "
                    "o teto de seguranca (duration_seconds) enviado na ativacao ainda vale como rede de protecao.",
                    trace_id=self.trace_id,
                    context={"servico": service, "erro": str(exc)},
                )
                continue
            self.log(
                "INFO",
                f"Caos desligado em {service} (encerramento do orquestrador).",
                trace_id=self.trace_id,
                context={"servico": service, "tipos_falha": sorted(active.keys())},
            )
            self._active.pop(service, None)


def _read_token() -> str:
    token = os.environ.get(TOKEN_ENV_VAR, "")
    if not token:
        raise SystemExit(
            f"Variavel de ambiente {TOKEN_ENV_VAR} nao definida - necessaria para "
            "autenticar contra o endpoint interno de cada servico (mesmo segredo "
            "usado pelos 4 microservicos, ver .env.example)."
        )
    return token


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Executa um cenario de cascata coordenada de caos.")
    parser.add_argument("scenario_path", type=Path, help="Caminho do arquivo YAML do cenario.")
    args = parser.parse_args(argv)

    scenario = load_scenario(args.scenario_path)
    token = _read_token()
    orchestrator = Orchestrator(scenario, token=token)

    def _handle_signal(signum, frame):  # noqa: ARG001 - assinatura exigida por signal.signal
        orchestrator.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    orchestrator.run()


if __name__ == "__main__":
    main(sys.argv[1:])
