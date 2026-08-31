"""Runbook operacional da janela de validacao organica de 2h (issue #54,
specs/business/24-camada-caos-avancada.md, secao "Execucao organica (janela
de validacao real)").

Sobe o ambiente efemero (docker-compose.test.yml - decisao confirmada com o
usuario: consistente com v12/v16 de docs/escopo-arquitetura.md, que reserva
o ambiente principal persistente para o dataset de ML e usa o efemero para
qualquer bateria de validacao de agentes/caos, e com a janela anterior ja
documentada em docs/licoes-aprendidas-operacao-real.md, que rodou contra o
mesmo compose), inicia o gerador de trafego sintetico
(scripts/synthetic_traffic.py) e o chaos-orchestrator
(chaos-orchestrator/orchestrator.py) em ciclos repetidos do cenario de
cascata de exemplo (issue #53), por uma janela de tempo configuravel
(default 120 minutos).

Ao fim do relogio, o script para de agendar novo trafego/caos mas NAO
derruba o ambiente (sem `docker compose down`) nem interrompe os agentes
(preditivo, registro, local) - esses continuam sendo daemons externos,
iniciados/parados pelo operador em processos proprios, fora deste script
(este runbook nunca os inicia nem os mata). A janela so e considerada
finalizada quando nao houver mais:
  - issue candidata NOVA (label business-story/bug, sem chaos-test, sem
    dependencia aberta) ainda sem assignee - agent-local ainda nao pegou; e
  - issue aberta atribuida ao agent-local sem a label agent-stuck - ciclo
    em andamento (destinos 1/2/3 de specs/tech/error-handling.md ainda nao
    aplicados).
`agent-stuck` (escalonamento das issues #40/#41) e tratado como estado
terminal para efeito desta espera - um item que escalou nao vai se resolver
sozinho, entao nao bloqueia o fim da janela.

Para cobrir o caso de um agente estar no meio de um ciclo exatamente no
instante do corte (ex. agent-preditivo prestes a abrir uma issue nova que
ainda nao existe no momento da checagem), a condicao "sem pendencias" so e
aceita apos se manter estavel por uma janela de estabilizacao
(--settle-window-seconds, default: maior intervalo de polling configurado
entre agent-local/agent-preditivo + margem de seguranca) - qualquer nova
pendencia detectada durante esse periodo reinicia a contagem.

Uso:
    scripts/.venv/Scripts/python.exe scripts/validation_window.py --duration-minutes 120
    scripts/.venv/Scripts/python.exe scripts/validation_window.py --duration-minutes 10   # teste curto

Ctrl+C durante a fase de trafego/caos aborta com seguranca: o Windows
propaga CTRL_C_EVENT para todo o console (inclusive os subprocessos
synthetic_traffic.py/orchestrator.py, que nao sao criados em um process
group separado), entao o cenario de caos em andamento roda seu proprio
desligamento explicito (orchestrator.py, bloco `finally`) antes de sair.
Este script tambem grava o stop-file (mecanismo que faz o gerador de
trafego parar de emitir novas requisicoes) e segue direto para a fase de
espera dos agentes, sem nunca derrubar o ambiente. Ver README.md, secao
"Janela de validacao organica de 2h", para o runbook completo e o que fazer
se algo travar no meio.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CHAOS_ORCHESTRATOR_DIR = REPO_ROOT / "chaos-orchestrator"
AGENT_LOCAL_DIR = REPO_ROOT / "agent-local"
DEFAULT_SCENARIO = CHAOS_ORCHESTRATOR_DIR / "scenarios" / "account_and_queue_cascade.yaml"
DEFAULT_COMPOSE_FILE = REPO_ROOT / "docker-compose.test.yml"

SERVICE_HEALTH_URLS = {
    "onboarding-service": "http://localhost:8001/health",
    "account-service": "http://localhost:8002/health",
    "pix-key-service": "http://localhost:8003/health",
    "transaction-service": "http://localhost:8004/health",
}

# {diretorio do componente: nome do banco} - `docker-compose.test.yml` so
# cria os 5 bancos vazios (infra/postgres/init-databases.sh); o schema em
# si depende de `alembic upgrade head` rodado por fora, achado real
# documentado em docs/licoes-aprendidas-operacao-real.md ("Migrations nunca
# tinham sido aplicadas no ambiente efemero recem-criado... isso nao
# estava documentado em nenhum lugar do fluxo de subida"). Reproduzido de
# novo no teste curto deste script (10 min): sem este passo, toda
# requisicao do gerador de trafego falha com 500 (relation does not
# exist) - silencioso o bastante para passar despercebido numa janela de
# 2h inteira se nao for automatizado aqui.
MIGRATION_SERVICES = {
    "onboarding-service": "onboarding",
    "account-service": "account",
    "pix-key-service": "pix_key",
    "transaction-service": "transaction",
    "agent-ops-service": "agent_ops",
}

# Espelham agent_local.polling.CHAOS_ORIGIN_LABEL/AGENT_STUCK_LABEL - valor
# duplicado aqui (nao importado) so para a busca `gh`/rotulagem textual;
# a logica de filtro em si (quem conta como "candidata elegivel") e
# reusada de verdade via list_eligible_unassigned_candidates() abaixo, para
# nao arriscar drift com o comportamento real do agent-local.
CANDIDATE_LABELS = "business-story,bug"
CHAOS_ORIGIN_LABEL = "chaos-test"
AGENT_STUCK_LABEL = "agent-stuck"

GRAFANA_DASHBOARDS = [
    ("Golden Signals (Fase 1)", "http://localhost:3000/d/fase1-golden-signals"),
    ("Metricas de Negocio v1", "http://localhost:3000/d/metricas-negocio-v1"),
]

_DEFAULT_AGENT_POLL_INTERVAL_SECONDS = 300.0
_SETTLE_MARGIN_SECONDS = 60.0
_SLEEP_CHUNK_SECONDS = 1.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def log(event: str, **fields) -> None:
    print(
        json.dumps(
            {"timestamp": _utc_now_iso(), "service_name": "validation-window", "event": event, **fields},
            ensure_ascii=False,
        ),
        flush=True,
    )


def _venv_python(component_dir: Path) -> Path:
    windows_exe = component_dir / ".venv" / "Scripts" / "python.exe"
    if windows_exe.exists():
        return windows_exe
    return component_dir / ".venv" / "bin" / "python"


def _read_interval_from_env_file(env_path: Path, key: str, default: float) -> float:
    """Le uma unica variavel numerica de um arquivo .env sem depender de
    python-dotenv (nao e dependencia deste script) - so o suficiente para
    default o settle-window ao valor de polling real configurado, em vez
    de duplicar o numero como constante solta."""
    if not env_path.exists():
        return default
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            try:
                return float(line.split("=", 1)[1].strip())
            except ValueError:
                return default
    return default


def default_settle_window_seconds() -> float:
    local_interval = _read_interval_from_env_file(
        AGENT_LOCAL_DIR / ".env", "AGENT_LOCAL_INTERVAL_SECONDS", _DEFAULT_AGENT_POLL_INTERVAL_SECONDS
    )
    predictive_interval = _read_interval_from_env_file(
        REPO_ROOT / "agent-preditivo" / ".env", "PREDICTIVE_AGENT_INTERVAL_SECONDS", _DEFAULT_AGENT_POLL_INTERVAL_SECONDS
    )
    return max(local_interval, predictive_interval) + _SETTLE_MARGIN_SECONDS


# --------------------------------------------------------------------------
# Deteccao de atividade pendente dos agentes (via GitHub, unica fonte de
# estado compartilhado entre os agentes - "orquestracao desacoplada via
# GitHub", docs/escopo-arquitetura.md v15/v26)
# --------------------------------------------------------------------------


def _gh_json(args: list[str]) -> list[dict]:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def snapshot_pre_existing_candidates() -> set[int]:
    """Issues elegiveis (sem assignee, sem chaos-test, sem dependencia
    aberta) que JA existiam antes da janela comecar a agendar trafego/caos -
    excluidas do calculo de "pendencia" para nao esperar por backlog antigo
    e sem relacao com esta execucao (ex. issues #50/#55 do backlog real no
    momento em que esta issue foi implementada)."""
    return set(list_eligible_unassigned_candidates())


_CANDIDATE_CHECK_SCRIPT = """
import json
from agent_local import github_client
from agent_local.polling import CHAOS_ORIGIN_LABEL
from agent_local.dependency_check import has_open_dependency

eligible = []
for issue in github_client.list_candidate_issues():
    if CHAOS_ORIGIN_LABEL in issue.labels:
        continue
    if has_open_dependency(issue.body):
        continue
    eligible.append(issue.number)
print(json.dumps(eligible))
"""


def list_eligible_unassigned_candidates() -> list[int]:
    """Reusa os filtros REAIS do agent-local (agent_local.polling -
    pula chaos-test e dependencia aberta, os mesmos dois `continue` de
    pick_candidate_issue) rodando no proprio venv do agent-local, sem efeito
    colateral (nunca chama assign_self) - evita duplicar essa logica aqui e
    arriscar ela divergir com o tempo (mesmo racional de v11/v38 em
    docs/escopo-arquitetura.md)."""
    result = subprocess.run(
        [str(_venv_python(AGENT_LOCAL_DIR)), "-c", _CANDIDATE_CHECK_SCRIPT],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        cwd=AGENT_LOCAL_DIR,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def list_assigned_open_issues() -> list[int]:
    """Issues abertas atribuidas a @me (mesma identidade `gh` usada pelo
    agent-local - ver agent_local/github_client.py, assign_self) com label
    business-story/bug, sem agent-stuck. `agent-stuck` fica de fora porque e
    o proprio mecanismo de escalonamento (issues #40/#41) sinalizando que o
    item nao vai se resolver sozinho - nao deve bloquear o fim da janela."""
    data = _gh_json(
        [
            "issue",
            "list",
            "--search",
            f"is:open assignee:@me label:{CANDIDATE_LABELS} -label:{AGENT_STUCK_LABEL}",
            "--json",
            "number",
        ]
    )
    return [item["number"] for item in data]


@dataclass(frozen=True)
class PendingState:
    is_pending: bool
    new_unassigned: list[int]
    assigned_in_progress: list[int]


def compute_pending_state(
    pre_existing: set[int],
    unassigned_candidates: list[int],
    assigned_open: list[int],
) -> PendingState:
    """Pendencia = (a) candidata elegivel NOVA (ainda nao existia no
    snapshot inicial) ainda sem assignee - agent-local nao pegou ainda; ou
    (b) qualquer issue aberta atribuida a @me (nao filtrada pelo snapshot -
    se esta atribuida, e ciclo em andamento agora, independente de quando a
    issue foi criada)."""
    new_unassigned = [n for n in unassigned_candidates if n not in pre_existing]
    is_pending = bool(new_unassigned or assigned_open)
    return PendingState(is_pending, new_unassigned, list(assigned_open))


# --------------------------------------------------------------------------
# Fase 1: trafego sintetico + ciclos de caos
# --------------------------------------------------------------------------


def wait_for_services_healthy(timeout_seconds: float = 180.0) -> None:
    import httpx

    deadline = time.monotonic() + timeout_seconds
    pending = dict(SERVICE_HEALTH_URLS)
    while pending and time.monotonic() < deadline:
        for service, url in list(pending.items()):
            try:
                resp = httpx.get(url, timeout=3.0)
                if resp.status_code == 200:
                    pending.pop(service)
                    log("servico_saudavel", servico=service)
            except httpx.HTTPError:
                pass
        if pending:
            time.sleep(3.0)
    if pending:
        raise SystemExit(f"Servicos nao ficaram saudaveis a tempo: {sorted(pending)}")


def docker_compose_up(compose_file: Path, *, build: bool) -> None:
    args = ["docker", "compose", "-f", str(compose_file), "up", "-d"]
    if build:
        args.append("--build")
    log("subindo_ambiente", compose_file=str(compose_file), build=build)
    subprocess.run(args, cwd=REPO_ROOT, check=True)


def run_migrations() -> None:
    """`alembic upgrade head` e idempotente (nao reaplica revisao ja
    aplicada) - seguro rodar em todo start da janela, mesmo contra o
    ambiente principal persistente (onde so a primeira execucao faz
    algo)."""
    for service_dir, db_name in MIGRATION_SERVICES.items():
        component_dir = REPO_ROOT / service_dir
        python = _venv_python(component_dir)
        env = {**os.environ, "DATABASE_URL": f"postgresql://bank:bank@localhost:5432/{db_name}"}
        log("aplicando_migrations", servico=service_dir, banco=db_name)
        subprocess.run([str(python), "-m", "alembic", "upgrade", "head"], cwd=component_dir, env=env, check=True)


def start_traffic_generator(
    stop_file: Path, duration_seconds: int, log_path: Path, *, min_pace: float, max_pace: float
) -> subprocess.Popen:
    python = _venv_python(SCRIPTS_DIR)
    log_f = open(log_path, "w", encoding="utf-8")
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    log("trafego_sintetico_iniciado", duration_seconds=duration_seconds, stop_file=str(stop_file))
    return subprocess.Popen(
        [
            str(python),
            "synthetic_traffic.py",
            "--duration-seconds",
            str(duration_seconds),
            "--stop-file",
            str(stop_file),
            "--min-pace-seconds",
            str(min_pace),
            "--max-pace-seconds",
            str(max_pace),
        ],
        cwd=SCRIPTS_DIR,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        env=env,
    )


def resolve_scenario_path(scenario_arg: Path) -> Path:
    """Resolve --scenario contra a raiz do repo (nunca contra o cwd do
    processo atual) - achado real da issue #75: run_chaos_cycle invoca
    orchestrator.py com cwd=CHAOS_ORCHESTRATOR_DIR (o subprocesso ja roda de
    DENTRO de chaos-orchestrator/), entao um caminho relativo tipo
    'chaos-orchestrator/scenarios/x.yaml' (copiado do proprio repo, o jeito
    mais natural de passar o argumento) resolvia como
    'chaos-orchestrator/chaos-orchestrator/scenarios/x.yaml' - inexistente em
    todos os 40 ciclos da janela de 2h (docs/relatorio-janela-fase2b.md,
    secao "Aviso critico"), sem nenhum caos injetado.

    Um caminho absoluto (inclusive o DEFAULT_SCENARIO do proprio script)
    passa direto, sem essa reinterpretacao."""
    if scenario_arg.is_absolute():
        resolved = scenario_arg
    else:
        resolved = (REPO_ROOT / scenario_arg).resolve()
    if not resolved.is_file():
        raise SystemExit(
            f"Cenario de caos nao encontrado: {resolved} (--scenario={scenario_arg}). "
            f"Caminhos relativos sao resolvidos a partir da raiz do repo ({REPO_ROOT}), "
            "nao do cwd do subprocesso do orchestrator.py."
        )
    return resolved


def run_chaos_cycle(scenario_path: Path, log_path: Path, token: str) -> int:
    python = _venv_python(CHAOS_ORCHESTRATOR_DIR)
    env = {**os.environ, "CHAOS_INTERNAL_TOKEN": token, "PYTHONUNBUFFERED": "1"}
    with open(log_path, "w", encoding="utf-8") as log_f:
        result = subprocess.run(
            [str(python), "orchestrator.py", str(scenario_path)],
            cwd=CHAOS_ORCHESTRATOR_DIR,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            env=env,
        )
    return result.returncode


def _interruptible_sleep(seconds: float) -> None:
    remaining = seconds
    while remaining > 0:
        chunk = min(_SLEEP_CHUNK_SECONDS, remaining)
        time.sleep(chunk)
        remaining -= chunk


def chaos_cycle_loop(scenario_path: Path, out_dir: Path, token: str, deadline: float, cycle_gap_seconds: float) -> int:
    """Roda o cenario de cascata repetidamente ate o relogio da janela
    acabar. Cada execucao de orchestrator.py e sincrona/bloqueante (a
    timeline do proprio cenario, ~7 min no exemplo de referencia) - o loop
    so decide se vale a pena comecar MAIS UM ciclo, nunca interrompe um
    ciclo em andamento (mesma garantia dada aos agentes, aplicada aqui ao
    proprio caos: uma ativacao em curso sempre roda ate o fim natural ou ate
    Ctrl+C, nunca e cortada por tempo)."""
    cycle_index = 0
    while time.monotonic() < deadline:
        cycle_index += 1
        log_path = out_dir / f"chaos_cycle_{cycle_index:02d}.log"
        log("ciclo_de_caos_iniciado", ciclo=cycle_index, log=str(log_path))
        run_chaos_cycle(scenario_path, log_path, token)
        log("ciclo_de_caos_concluido", ciclo=cycle_index)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        gap = min(cycle_gap_seconds, remaining)
        log("aguardando_proximo_ciclo", segundos=round(gap, 1))
        _interruptible_sleep(gap)
    return cycle_index


# --------------------------------------------------------------------------
# Fase 2: espera pelos agentes
# --------------------------------------------------------------------------


def wait_for_agents_idle(
    pre_existing: set[int],
    *,
    poll_interval_seconds: float,
    settle_window_seconds: float,
    warn_after_seconds: float,
) -> None:
    settle_since: float | None = None
    last_warn = time.monotonic()

    log(
        "fase_de_espera_iniciada",
        settle_window_seconds=settle_window_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )

    while True:
        unassigned = list_eligible_unassigned_candidates()
        assigned = list_assigned_open_issues()
        state = compute_pending_state(pre_existing, unassigned, assigned)
        now = time.monotonic()

        if state.is_pending:
            settle_since = None
            log(
                "agentes_com_atividade_pendente",
                candidatas_novas=state.new_unassigned,
                atribuidas_em_andamento=state.assigned_in_progress,
            )
        else:
            if settle_since is None:
                settle_since = now
                log("nenhuma_pendencia_detectada_iniciando_estabilizacao")
            elapsed = now - settle_since
            if elapsed >= settle_window_seconds:
                log("janela_finalizada", motivo="sem atividade pendente durante todo o periodo de estabilizacao")
                return
            log("estabilizando", segundos_restantes=round(settle_window_seconds - elapsed, 1))

        if now - last_warn >= warn_after_seconds:
            log(
                "AVISO_espera_prolongada",
                mensagem=(
                    "A fase de espera esta demorando mais que o esperado. Isso NAO aborta "
                    "automaticamente (uma issue so vira terminal via merge/no-op/fechamento ou "
                    "escalonamento para agent-stuck) - confira manualmente se os daemons "
                    "agent-local/agent-preditivo ainda estao rodando."
                ),
            )
            last_warn = now

        time.sleep(poll_interval_seconds)


# --------------------------------------------------------------------------
# Fase 3: resumo de evidencias
# --------------------------------------------------------------------------


def _agent_ops_counts(pg_dsn: str, window_start_iso: str) -> dict:
    try:
        import psycopg2
    except ImportError:
        return {}
    try:
        conn = psycopg2.connect(pg_dsn)
    except Exception as exc:  # noqa: BLE001 - so para o resumo, nao pode quebrar o fechamento da janela
        log("aviso_nao_foi_possivel_consultar_agent_ops", erro=str(exc))
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM risk_decisions WHERE decided_at >= %s", (window_start_iso,))
            risk_decisions = cur.fetchone()[0]
            cur.execute("SELECT decision, count(*) FROM risk_decisions WHERE decided_at >= %s GROUP BY decision", (window_start_iso,))
            by_decision = dict(cur.fetchall())
            cur.execute("SELECT count(*) FROM flagged_signals WHERE first_seen_at >= %s", (window_start_iso,))
            flagged_signals = cur.fetchone()[0]
        return {"risk_decisions": risk_decisions, "risk_decisions_por_tipo": by_decision, "flagged_signals": flagged_signals}
    except Exception as exc:  # noqa: BLE001 - idem: tabelas podem nao existir ainda (migrations do
        # agent_ops nao aplicadas no ambiente efemero recem-criado - achado real
        # documentado em docs/licoes-aprendidas-operacao-real.md, "alembic upgrade
        # head rodado manualmente por fora") - o resumo deve degradar, nunca quebrar
        # depois de 2h de janela real ja terem rodado com sucesso.
        log("aviso_nao_foi_possivel_consultar_agent_ops", erro=str(exc))
        return {}
    finally:
        conn.close()


def print_summary(window_start_iso: str, compose_file: Path, out_dir: Path) -> None:
    try:
        issues_criadas = _gh_json(
            [
                "issue",
                "list",
                "--search",
                f"created:>={window_start_iso[:10]} label:{CANDIDATE_LABELS},{CHAOS_ORIGIN_LABEL}",
                "--json",
                "number,title,labels,createdAt",
                "--limit",
                "200",
            ]
        )
    except subprocess.CalledProcessError as exc:
        # O resumo e so leitura de evidencias apos a janela real ja ter
        # rodado com sucesso - uma falha aqui (rede, rate limit do gh) nao
        # pode derrubar o script neste ponto, so degradar o proprio resumo.
        log("aviso_nao_foi_possivel_listar_issues_da_janela", erro=str(exc))
        issues_criadas = []
    agent_ops = _agent_ops_counts("postgresql://bank:bank@localhost:5432/agent_ops", window_start_iso)

    print("\n" + "=" * 78)
    print("JANELA DE VALIDACAO FINALIZADA - ambiente permanece no ar (sem docker compose down)")
    print("=" * 78)
    print(f"Inicio da janela (UTC): {window_start_iso}")
    print(f"Compose usado: {compose_file}")
    print(f"Logs desta execucao: {out_dir}")
    print()
    print("Dashboards Grafana (login admin/admin):")
    for name, url in GRAFANA_DASHBOARDS:
        print(f"  - {name}: {url}")
    print()
    print("Tabelas agent_ops (Postgres, mesmas credenciais do docker-compose):")
    print("  docker exec bank-of-decoy-postgres psql -U bank -d agent_ops -c "
          f"\"SELECT * FROM risk_decisions WHERE decided_at >= '{window_start_iso}' ORDER BY decided_at;\"")
    print("  docker exec bank-of-decoy-postgres psql -U bank -d agent_ops -c "
          f"\"SELECT * FROM flagged_signals WHERE first_seen_at >= '{window_start_iso}' ORDER BY first_seen_at;\"")
    if agent_ops:
        print(f"  -> contagem rapida: {json.dumps(agent_ops, ensure_ascii=False)}")
    print()
    print(f"Issues abertas no GitHub durante a janela (desde {window_start_iso[:10]}, label {CANDIDATE_LABELS},{CHAOS_ORIGIN_LABEL}):")
    if issues_criadas:
        for item in issues_criadas:
            labels = ",".join(l["name"] for l in item["labels"])
            print(f"  - #{item['number']} [{labels}] {item['title']} ({item['createdAt']})")
    else:
        print("  (nenhuma issue nova encontrada com esse filtro - confira manualmente se o filtro de data e' preciso o bastante)")
    print()
    print("Logs estruturados dos servicos (JSON, specs/tech/logging.md):")
    print(f"  docker compose -f {compose_file} logs --since {window_start_iso} <servico>")
    print("  (servicos: onboarding-service, account-service, pix-key-service, transaction-service)")
    print("=" * 78 + "\n")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    # stdout default do Windows e cp1252, nao UTF-8 - sem isso, acentos no
    # titulo das issues impressas em print_summary saem corrompidos (mesma
    # classe de bug ja documentada em agent_local/github_client.py e
    # agent_local/logging_config.py para esses mesmos daemons).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--duration-minutes", type=float, default=120.0)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--cycle-gap-minutes", type=float, default=3.0)
    parser.add_argument("--traffic-min-pace-seconds", type=float, default=1.5)
    parser.add_argument("--traffic-max-pace-seconds", type=float, default=4.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=30.0)
    parser.add_argument("--settle-window-seconds", type=float, default=None, help="default: maior intervalo de polling entre agent-local/agent-preditivo + 60s")
    parser.add_argument("--warn-after-seconds", type=float, default=1800.0)
    parser.add_argument("--no-build", action="store_true", help="pula 'docker compose up --build' (assume imagens ja construidas)")
    parser.add_argument("--skip-up", action="store_true", help="assume que o ambiente ja esta no ar (nao chama docker compose up)")
    parser.add_argument("--skip-migrations", action="store_true", help="pula 'alembic upgrade head' nos 5 servicos (assume que ja foi aplicado)")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    token = os.environ.get("CHAOS_INTERNAL_TOKEN", "")
    if not token:
        raise SystemExit("CHAOS_INTERNAL_TOKEN nao definida no ambiente - necessaria para o chaos-orchestrator.")

    args.scenario = resolve_scenario_path(args.scenario)

    settle_window_seconds = args.settle_window_seconds
    if settle_window_seconds is None:
        settle_window_seconds = default_settle_window_seconds()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (SCRIPTS_DIR / "validation_window_logs" / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    window_start_iso = _utc_now_iso()
    log(
        "janela_iniciada",
        duration_minutes=args.duration_minutes,
        compose_file=str(args.compose_file),
        scenario=str(args.scenario),
        settle_window_seconds=settle_window_seconds,
        out_dir=str(out_dir),
    )

    if not args.skip_up:
        docker_compose_up(args.compose_file, build=not args.no_build)
        wait_for_services_healthy()

    if not args.skip_migrations:
        run_migrations()

    pre_existing = snapshot_pre_existing_candidates()
    log("snapshot_backlog_pre_existente", issues=sorted(pre_existing))

    stop_file = out_dir / "stop_traffic.flag"
    duration_seconds = int(args.duration_minutes * 60)
    deadline = time.monotonic() + duration_seconds

    traffic_proc = start_traffic_generator(
        stop_file,
        duration_seconds,
        out_dir / "synthetic_traffic.log",
        min_pace=args.traffic_min_pace_seconds,
        max_pace=args.traffic_max_pace_seconds,
    )

    try:
        chaos_cycle_loop(args.scenario, out_dir, token, deadline, args.cycle_gap_minutes * 60.0)
    except KeyboardInterrupt:
        log("interrompido_pelo_operador", acao="parando novas acoes com seguranca - ambiente e agentes NAO sao afetados")
    finally:
        stop_file.write_text("stop\n", encoding="utf-8")
        remaining = deadline - time.monotonic()
        if remaining > 0:
            log("aguardando_gerador_de_trafego_parar", segundos=round(remaining, 1))
        try:
            traffic_proc.wait(timeout=max(remaining, 0) + 30)
        except subprocess.TimeoutExpired:
            log("aviso_gerador_de_trafego_nao_parou_a_tempo_finalizando")
            traffic_proc.terminate()

    log("fase_de_trafego_e_caos_encerrada")

    try:
        wait_for_agents_idle(
            pre_existing,
            poll_interval_seconds=args.poll_interval_seconds,
            settle_window_seconds=settle_window_seconds,
            warn_after_seconds=args.warn_after_seconds,
        )
    except KeyboardInterrupt:
        log(
            "espera_interrompida_pelo_operador",
            aviso="saindo do script SEM esperar os agentes - ambiente permanece no ar, agentes continuam rodando por conta propria",
        )

    print_summary(window_start_iso, args.compose_file, out_dir)


if __name__ == "__main__":
    sys.exit(main())
