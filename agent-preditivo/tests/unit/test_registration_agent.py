from unittest.mock import patch

from agent_preditivo.bug_detection import BugSignal
from agent_preditivo.opportunity_detection import OpportunityFinding
from agent_preditivo.registration_agent import (
    format_bug_issue,
    format_opportunity_issue,
    register_bug,
    register_opportunity,
)


def test_format_bug_issue_preenche_campos_estruturados_em_codigo() -> None:
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="taxa de erro 12% > 5%")

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value="SINAL_QUE_DISPAROU: taxa de erro elevada\nEVIDENCIA: 12% em 5 min",
    ):
        title, body = format_bug_issue(signal)

    assert "[BUG]" in title
    assert "transaction-service" in title
    assert "Categoria da mudança: operacional" in body
    assert "transaction-service (crítico)" in body


def test_format_bug_issue_marca_origem_de_caos_quando_chaos_ativo() -> None:
    signal = BugSignal(
        service="transaction-service", signal_type="erro_alto", detail="x", chaos_ativo=True
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value="SINAL_QUE_DISPAROU: taxa de erro elevada\nEVIDENCIA: 12% em 5 min",
    ):
        _, body = format_bug_issue(signal)

    assert "Origem: camada de caos" in body
    assert "CHAOS_ENABLED=true" in body
    assert "Não deve ser corrigido automaticamente" in body


def test_format_bug_issue_sem_aviso_de_caos_quando_chaos_inativo() -> None:
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x", chaos_ativo=False)

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value="SINAL_QUE_DISPAROU: x\nEVIDENCIA: y",
    ):
        _, body = format_bug_issue(signal)

    assert "Origem: camada de caos" not in body


def test_format_bug_issue_usa_detail_como_fallback_se_llm_nao_seguir_formato() -> None:
    signal = BugSignal(service="account-service", signal_type="saturacao_pool", detail="saturacao 90%")

    with patch("agent_preditivo.registration_agent.chat", return_value="texto fora do formato"):
        _, body = format_bug_issue(signal)

    assert "saturacao 90%" in body


def test_format_opportunity_issue_preenche_campos_estruturados() -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_x",
        veredito="GAP",
        racional="viola regra Y",
        observed_behavior="comportamento Z",
        rule_chunks=[],
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value="RESUMO: lacuna encontrada\nCONTRATO_AFETADO: regra Y",
    ):
        title, body = format_opportunity_issue(finding, scenario_path=None)

    assert "cenario_x" in title
    assert "Categoria da mudança: regra de negócio" in body


def test_register_bug_nao_cria_issue_se_sinal_ja_em_aberto() -> None:
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x")

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value={"id": "existing"}),
        patch("agent_preditivo.registration_agent.create_issue") as mock_create,
    ):
        result = register_bug(signal)

    assert result is None
    mock_create.assert_not_called()


def test_register_bug_cria_issue_e_registra_signal_quando_novo() -> None:
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x")

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch(
            "agent_preditivo.registration_agent.create_issue",
            return_value=(42, "https://github.com/x/y/issues/42"),
        ) as mock_create,
        patch("agent_preditivo.registration_agent.agent_ops_db.register_signal") as mock_register,
        patch("agent_preditivo.registration_agent.chat", return_value="SINAL_QUE_DISPAROU: x\nEVIDENCIA: y"),
        patch("agent_preditivo.registration_agent.notify_issue_created") as mock_notify,
    ):
        result = register_bug(signal)

    assert result == 42
    mock_create.assert_called_once()
    mock_register.assert_called_once_with("erro_alto", "transaction-service", issue_number=42)
    mock_notify.assert_called_once_with(42, "[BUG] erro_alto em transaction-service", "bug", "https://github.com/x/y/issues/42")


def test_register_bug_adiciona_label_chaos_test_quando_chaos_ativo() -> None:
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x", chaos_ativo=True)

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch(
            "agent_preditivo.registration_agent.create_issue",
            return_value=(42, "https://github.com/x/y/issues/42"),
        ) as mock_create,
        patch("agent_preditivo.registration_agent.agent_ops_db.register_signal"),
        patch("agent_preditivo.registration_agent.chat", return_value="SINAL_QUE_DISPAROU: x\nEVIDENCIA: y"),
        patch("agent_preditivo.registration_agent.notify_issue_created"),
    ):
        register_bug(signal)

    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["extra_labels"] == ["chaos-test"]


def test_register_bug_sem_label_extra_quando_chaos_inativo() -> None:
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x", chaos_ativo=False)

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch(
            "agent_preditivo.registration_agent.create_issue",
            return_value=(42, "https://github.com/x/y/issues/42"),
        ) as mock_create,
        patch("agent_preditivo.registration_agent.agent_ops_db.register_signal"),
        patch("agent_preditivo.registration_agent.chat", return_value="SINAL_QUE_DISPAROU: x\nEVIDENCIA: y"),
        patch("agent_preditivo.registration_agent.notify_issue_created"),
    ):
        register_bug(signal)

    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["extra_labels"] is None


def test_register_opportunity_cria_issue_e_notifica_quando_gap() -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_x", veredito="GAP", racional="viola regra Y", observed_behavior="Z", rule_chunks=[]
    )

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch(
            "agent_preditivo.registration_agent.create_issue",
            return_value=(99, "https://github.com/x/y/issues/99"),
        ) as mock_create,
        patch("agent_preditivo.registration_agent.agent_ops_db.register_signal"),
        patch(
            "agent_preditivo.registration_agent.chat", return_value="RESUMO: lacuna\nCONTRATO_AFETADO: regra Y"
        ),
        patch("agent_preditivo.registration_agent.notify_issue_created") as mock_notify,
    ):
        result = register_opportunity(finding, scenario_path=None)

    assert result == 99
    mock_create.assert_called_once()
    mock_notify.assert_called_once_with(99, "[FASE 3] Oportunidade: cenario_x", "business-story", "https://github.com/x/y/issues/99")


def test_register_opportunity_nao_cria_issue_quando_sem_gap() -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_x", veredito="SEM_GAP", racional="ok", observed_behavior="ok", rule_chunks=[]
    )

    with patch("agent_preditivo.registration_agent.create_issue") as mock_create:
        result = register_opportunity(finding, scenario_path=None)

    assert result is None
    mock_create.assert_not_called()
