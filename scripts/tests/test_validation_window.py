"""Testes da logica pura do runbook da janela de validacao (issue #54) -
sem gh/docker/subprocessos reais. A parte que fala com o mundo real
(snapshot_pre_existing_candidates, list_assigned_open_issues,
list_eligible_unassigned_candidates, docker_compose_up, etc.) e validada
manualmente contra o ambiente/GitHub reais (ver README.md, secao "Janela de
validacao organica de 2h")."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation_window import _read_interval_from_env_file, compute_pending_state


def test_sem_pendencia_quando_nada_novo_e_nada_atribuido():
    state = compute_pending_state(pre_existing={50, 54, 55}, unassigned_candidates=[50, 54, 55], assigned_open=[])
    assert state.is_pending is False
    assert state.new_unassigned == []
    assert state.assigned_in_progress == []


def test_pendente_por_candidata_nova_ainda_nao_atribuida():
    # #55 ja existia antes da janela (backlog antigo, nao deve bloquear);
    # #60 e nova (surgiu durante a janela) e ainda nao foi pega - pendente.
    state = compute_pending_state(pre_existing={55}, unassigned_candidates=[55, 60], assigned_open=[])
    assert state.is_pending is True
    assert state.new_unassigned == [60]


def test_pendente_por_issue_atribuida_em_andamento():
    state = compute_pending_state(pre_existing=set(), unassigned_candidates=[], assigned_open=[61])
    assert state.is_pending is True
    assert state.assigned_in_progress == [61]


def test_issue_atribuida_conta_mesmo_se_pre_existente():
    # Se uma issue que ja existia (desatribuida) no snapshot foi pega pelo
    # agent-local durante a janela, ela aparece em assigned_open (nao em
    # unassigned_candidates) - deve continuar contando como pendencia,
    # mesmo nao sendo "nova": esta em processamento agora, e o que importa.
    state = compute_pending_state(pre_existing={55}, unassigned_candidates=[], assigned_open=[55])
    assert state.is_pending is True
    assert state.assigned_in_progress == [55]


def test_agent_stuck_ja_vem_filtrado_antes_de_chegar_aqui():
    # list_assigned_open_issues() exclui `-label:agent-stuck` na propria
    # busca `gh` - compute_pending_state so decide sobre o que recebe, e
    # confia que uma issue agent-stuck nunca aparece em assigned_open.
    state = compute_pending_state(pre_existing=set(), unassigned_candidates=[], assigned_open=[])
    assert state.is_pending is False


def test_read_interval_from_env_file(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("SOME_OTHER_VAR=1\nAGENT_LOCAL_INTERVAL_SECONDS=180\n", encoding="utf-8")
    assert _read_interval_from_env_file(env_path, "AGENT_LOCAL_INTERVAL_SECONDS", 300.0) == 180.0


def test_read_interval_from_env_file_ausente_usa_default(tmp_path):
    assert _read_interval_from_env_file(tmp_path / "nao-existe.env", "X", 300.0) == 300.0


def test_read_interval_from_env_file_valor_invalido_usa_default(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("AGENT_LOCAL_INTERVAL_SECONDS=nao-e-numero\n", encoding="utf-8")
    assert _read_interval_from_env_file(env_path, "AGENT_LOCAL_INTERVAL_SECONDS", 300.0) == 300.0
