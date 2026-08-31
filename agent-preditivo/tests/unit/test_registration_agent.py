import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_preditivo.bug_detection import BugSignal
from agent_preditivo.opportunity_detection import OpportunityFinding
from agent_preditivo.registration_agent import (
    find_open_github_issue,
    format_bug_issue,
    format_opportunity_issue,
    register_bug,
    register_opportunity,
)


@pytest.fixture
def specs_dir(tmp_path, monkeypatch):
    """Isola o diretorio specs/business/ (e o _REPO_ROOT usado para
    calcular caminhos relativos) usado por format_opportunity_issue,
    evitando escrever no repositorio real durante os testes (issue #44)."""
    business_dir = tmp_path / "specs" / "business"
    business_dir.mkdir(parents=True)
    monkeypatch.setattr("agent_preditivo.registration_agent._REPO_ROOT", tmp_path)
    monkeypatch.setattr("agent_preditivo.registration_agent._BUSINESS_SPECS_DIR", business_dir)
    return business_dir


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


def test_format_bug_issue_prompt_usa_texto_guia_lido_do_template_real() -> None:
    """Issue #45: o prompt enviado ao LLM precisa vir do texto-guia lido de
    bug-report.md, nao de uma string fixa duplicada no Python."""
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x")
    capturado = {}

    def fake_chat(system_prompt: str, user_message: str) -> str:
        capturado["system_prompt"] = system_prompt
        return "SINAL_QUE_DISPAROU: x\nEVIDENCIA: y"

    with patch("agent_preditivo.registration_agent.chat", side_effect=fake_chat):
        format_bug_issue(signal)

    # frase que só existe no texto-guia real de bug-report.md, sob "Sinal que disparou"
    assert "taxa de erro > 5% em 5 min" in capturado["system_prompt"]
    # frase que só existe no texto-guia real, sob "Evidência"
    assert "Trecho relevante de log estruturado ou métrica" in capturado["system_prompt"]


def test_format_bug_issue_secao_nova_no_template_aparece_no_corpo_sem_mudanca_de_codigo(
    tmp_path, monkeypatch
) -> None:
    """Issue #45: adicionar uma secao nova ao template (sem tocar no codigo)
    precisa refletir no corpo da issue gerada."""
    template_path = tmp_path / "bug-report.md"
    template_path.write_text(
        """---
name: Bug (detectado pelo agente preditivo)
---

## Sinal que disparou

Qual threshold foi violado.

## Serviço afetado

Nome do serviço e criticidade.

## Impacto no cliente

Descreva o impacto percebido pelo usuário final.

## Evidência

Trecho relevante de log ou métrica.

## Passos de reprodução (se aplicável)

Sequência de ações, se identificável.

## Sinal de risco (para o score de subida)

Categoria da mudança: operacional (a maioria dos bugs técnicos se enquadra aqui)
Serviço(s) afetado(s) e criticidade: preencher conforme acima

## Dependências

Issues relacionadas, se houver.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_preditivo.registration_agent.BUG_TEMPLATE_PATH", template_path)

    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x")
    capturado = {}

    def fake_chat(system_prompt: str, user_message: str) -> str:
        capturado["system_prompt"] = system_prompt
        return (
            "SINAL_QUE_DISPAROU: taxa elevada\n"
            "IMPACTO_NO_CLIENTE: cliente não conseguiu completar o saque\n"
            "EVIDENCIA: log de erro"
        )

    with patch("agent_preditivo.registration_agent.chat", side_effect=fake_chat):
        _, body = format_bug_issue(signal)

    # o prompt pediu o campo novo usando o texto-guia da secao nova do template
    assert "IMPACTO_NO_CLIENTE" in capturado["system_prompt"]
    assert "Descreva o impacto percebido pelo usuário final." in capturado["system_prompt"]
    # o corpo final reflete a secao nova, na posição em que ela aparece no template
    assert "## Impacto no cliente" in body
    assert "cliente não conseguiu completar o saque" in body


def test_format_bug_issue_secao_removida_do_template_nao_aparece_no_corpo(tmp_path, monkeypatch) -> None:
    """Issue #45: remover uma secao do template (sem tocar no codigo)
    precisa fazer essa secao sumir do corpo da issue gerada."""
    template_path = tmp_path / "bug-report.md"
    template_path.write_text(
        """---
name: Bug (detectado pelo agente preditivo)
---

## Sinal que disparou

Qual threshold foi violado.

## Evidência

Trecho relevante de log ou métrica.

## Sinal de risco (para o score de subida)

Categoria da mudança: operacional (a maioria dos bugs técnicos se enquadra aqui)
Serviço(s) afetado(s) e criticidade: preencher conforme acima
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_preditivo.registration_agent.BUG_TEMPLATE_PATH", template_path)

    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x")

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value="SINAL_QUE_DISPAROU: x\nEVIDENCIA: y",
    ):
        _, body = format_bug_issue(signal)

    assert "## Dependências" not in body
    assert "## Passos de reprodução" not in body


def test_format_opportunity_issue_prompt_usa_texto_guia_lido_do_template_real(specs_dir) -> None:
    """Issue #45: o prompt enviado ao LLM (incluindo a lista de specs
    tecnicas validas) precisa vir do texto-guia lido de business-story.md."""
    finding = OpportunityFinding(
        scenario_name="cenario_x", veredito="GAP", racional="x", observed_behavior="y", rule_chunks=[]
    )
    capturado = {}

    def fake_chat(system_prompt: str, user_message: str) -> str:
        capturado["system_prompt"] = system_prompt
        return "RESUMO: r\nCONTRATO_AFETADO: c\nSPECS_TECNICAS: nenhuma\nCRITERIO_ACEITE: - item 1\n- item 2"

    with patch("agent_preditivo.registration_agent.chat", side_effect=fake_chat):
        format_opportunity_issue(finding, scenario_path=None)

    # lista de specs tecnicas veio da leitura do template, nao de constante fixa
    assert "database.md" in capturado["system_prompt"]
    assert "infrastructure.md" in capturado["system_prompt"]
    # exemplo real do critério de aceite do template foi reaproveitado na instrução
    assert "Testes cobrindo caminho feliz e erros documentados na spec" in capturado["system_prompt"]


def test_format_opportunity_issue_nova_spec_tecnica_no_template_fica_disponivel_sem_mudanca_de_codigo(
    tmp_path, monkeypatch, specs_dir
) -> None:
    """Issue #45: adicionar uma spec tecnica nova a lista do template precisa
    deixá-la disponível para o LLM marcar e aparecer no corpo, sem editar
    a lista fixa que hoje vive em Python."""
    template_path = tmp_path / "business-story.md"
    template_path.write_text(
        """---
name: História de negócio
---

## Spec de referência

Link para a spec.

## Resumo

Resumo da história.

## Contrato afetado

Contrato afetado.

## Critério de aceite

- [ ] Item verificável 1

## Specs técnicas relevantes

- [ ] stack.md
- [ ] resiliencia.md

## Sinal de risco (para o score de subida)

Categoria da mudança: regra de negócio | operacional
Serviço(s) afetado(s) e criticidade: a definir

## Dependências

Nenhuma.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_preditivo.registration_agent.BUSINESS_STORY_TEMPLATE_PATH", template_path)

    finding = OpportunityFinding(
        scenario_name="cenario_x", veredito="GAP", racional="x", observed_behavior="y", rule_chunks=[]
    )
    capturado = {}

    def fake_chat(system_prompt: str, user_message: str) -> str:
        capturado["system_prompt"] = system_prompt
        return (
            "RESUMO: r\nCONTRATO_AFETADO: c\nSPECS_TECNICAS: resiliencia.md\n"
            "CRITERIO_ACEITE: - item 1\n- item 2"
        )

    with patch("agent_preditivo.registration_agent.chat", side_effect=fake_chat):
        _, body, _ = format_opportunity_issue(finding, scenario_path=None)

    assert "resiliencia.md" in capturado["system_prompt"]
    assert "database.md" not in capturado["system_prompt"]  # não fazia parte deste template reduzido
    assert "- [x] resiliencia.md" in body
    assert "- [ ] stack.md" in body


def test_format_opportunity_issue_preenche_campos_estruturados(specs_dir) -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_x",
        veredito="GAP",
        racional="viola regra Y",
        observed_behavior="comportamento Z",
        rule_chunks=[],
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value=(
            "RESUMO: lacuna encontrada\nCONTRATO_AFETADO: regra Y\n"
            "SPECS_TECNICAS: database.md\nCRITERIO_ACEITE: - item 1\n- item 2"
        ),
    ):
        title, body, spec_path = format_opportunity_issue(finding, scenario_path=None)

    assert "cenario_x" in title
    assert "Categoria da mudança: regra de negócio" in body
    assert spec_path.exists()


def test_format_opportunity_issue_gera_secao_specs_tecnicas_marcando_relevantes(specs_dir) -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_saldo",
        veredito="GAP",
        racional="viola regra de saldo",
        observed_behavior="transação aceita sem saldo",
        rule_chunks=[],
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value=(
            "RESUMO: lacuna de saldo\nCONTRATO_AFETADO: regra de saldo\n"
            "SPECS_TECNICAS: database.md, error-handling.md\n"
            "CRITERIO_ACEITE: - transação com saldo insuficiente retorna 422\n- teste cobrindo o caso"
        ),
    ):
        _, body, _ = format_opportunity_issue(finding, scenario_path=None)

    assert "## Specs técnicas relevantes" in body
    assert "- [x] database.md" in body
    assert "- [x] error-handling.md" in body
    assert "- [ ] stack.md" in body
    assert "- [ ] security.md" in body


def test_format_opportunity_issue_specs_tecnicas_sem_relevantes_marca_tudo_desmarcado(specs_dir) -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_y", veredito="GAP", racional="x", observed_behavior="y", rule_chunks=[]
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value="RESUMO: r\nCONTRATO_AFETADO: c\nSPECS_TECNICAS: nenhuma\nCRITERIO_ACEITE: - item 1\n- item 2",
    ):
        _, body, _ = format_opportunity_issue(finding, scenario_path=None)

    for spec in [
        "stack.md",
        "logging.md",
        "database.md",
        "error-handling.md",
        "api-conventions.md",
        "testing.md",
        "observability.md",
        "messaging.md",
        "security.md",
        "infrastructure.md",
    ]:
        assert f"- [ ] {spec}" in body


def test_format_opportunity_issue_gera_criterio_de_aceite_real_nao_generico(specs_dir) -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_z", veredito="GAP", racional="x", observed_behavior="y", rule_chunks=[]
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value=(
            "RESUMO: r\nCONTRATO_AFETADO: c\nSPECS_TECNICAS: nenhuma\n"
            "CRITERIO_ACEITE: - chave inexistente retorna 404\n- chave inativa retorna 422\n- teste cobrindo os dois casos"
        ),
    ):
        _, body, _ = format_opportunity_issue(finding, scenario_path=None)

    assert "A definir após triagem humana/agente local" not in body
    assert "- [ ] chave inexistente retorna 404" in body
    assert "- [ ] chave inativa retorna 422" in body
    assert "- [ ] teste cobrindo os dois casos" in body


def test_format_opportunity_issue_criterio_de_aceite_remove_marcadores_empilhados(specs_dir) -> None:
    """Achado real na validacao ponta a ponta da issue #44: o LLM as vezes
    devolve linhas com marcador duplicado (ex. "- - item"), que sem stripping
    recursivo vazava um "- " residual dentro do texto do item."""
    finding = OpportunityFinding(
        scenario_name="cenario_v", veredito="GAP", racional="x", observed_behavior="y", rule_chunks=[]
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value=(
            "RESUMO: r\nCONTRATO_AFETADO: c\nSPECS_TECNICAS: nenhuma\n"
            "CRITERIO_ACEITE: - - O comportamento observado não respeita a regra\n- [ ] - outro item duplicado"
        ),
    ):
        _, body, _ = format_opportunity_issue(finding, scenario_path=None)

    assert "- [ ] O comportamento observado não respeita a regra" in body
    assert "- [ ] outro item duplicado" in body
    assert "- [ ] - " not in body


def test_format_opportunity_issue_criterio_de_aceite_fallback_generico_quando_llm_nao_retorna_itens(
    specs_dir,
) -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_w", veredito="GAP", racional="x", observed_behavior="y", rule_chunks=[]
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value="RESUMO: r\nCONTRATO_AFETADO: c\nSPECS_TECNICAS: nenhuma\nCRITERIO_ACEITE: ",
    ):
        _, body, _ = format_opportunity_issue(finding, scenario_path=None)

    assert "- [ ] A definir após triagem humana/agente local" in body


def test_format_opportunity_issue_cria_spec_de_negocio_com_numeracao_sequencial(specs_dir) -> None:
    (specs_dir / "22-existente.md").write_text("x", encoding="utf-8")
    (specs_dir / "23-outra-existente.md").write_text("x", encoding="utf-8")

    finding = OpportunityFinding(
        scenario_name="pix_key_conta_inexistente",
        veredito="GAP",
        racional="conta nunca validada",
        observed_behavior="chave criada mesmo com account_id inexistente",
        rule_chunks=[],
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value=(
            "RESUMO: lacuna de validação\nCONTRATO_AFETADO: contrato de criação de chave\n"
            "SPECS_TECNICAS: database.md\nCRITERIO_ACEITE: - item 1\n- item 2"
        ),
    ):
        _, _, spec_path = format_opportunity_issue(finding, scenario_path=None)

    assert spec_path.name == "24-pix-key-conta-inexistente.md"
    assert spec_path.parent == specs_dir
    content = spec_path.read_text(encoding="utf-8")
    assert content.startswith("# 24 —")
    assert "## Contexto" in content
    assert "## Objetivo" in content
    assert "## Critério de aceite" in content
    assert "## Sinal de risco" in content
    assert "## Dependências" in content


def test_format_opportunity_issue_numera_a_partir_de_1_quando_diretorio_vazio(specs_dir) -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_inicial", veredito="GAP", racional="x", observed_behavior="y", rule_chunks=[]
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value="RESUMO: r\nCONTRATO_AFETADO: c\nSPECS_TECNICAS: nenhuma\nCRITERIO_ACEITE: - item 1\n- item 2",
    ):
        _, _, spec_path = format_opportunity_issue(finding, scenario_path=None)

    assert spec_path.name == "1-cenario-inicial.md"


def test_format_opportunity_issue_spec_de_referencia_aponta_para_arquivo_criado_nao_para_cenario(
    specs_dir,
) -> None:
    repo_root = specs_dir.parent.parent  # _REPO_ROOT, patchado pela fixture specs_dir
    scenario_path = repo_root / "tests" / "scenarios" / "cenario_x.md"
    scenario_path.parent.mkdir(parents=True, exist_ok=True)
    scenario_path.write_text("x", encoding="utf-8")

    finding = OpportunityFinding(
        scenario_name="cenario_x", veredito="GAP", racional="x", observed_behavior="y", rule_chunks=[]
    )

    with patch(
        "agent_preditivo.registration_agent.chat",
        return_value="RESUMO: r\nCONTRATO_AFETADO: c\nSPECS_TECNICAS: nenhuma\nCRITERIO_ACEITE: - item 1\n- item 2",
    ):
        _, body, spec_path = format_opportunity_issue(finding, scenario_path=scenario_path)

    spec_section = body.split("## Resumo")[0]
    assert spec_path.name in spec_section
    assert "tests/scenarios/cenario_x.md" not in spec_section.split("Cenário reproduzível:")[0]
    assert "Cenário reproduzível: `tests/scenarios/cenario_x.md`" in body


def test_register_bug_nao_cria_issue_se_sinal_ja_em_aberto() -> None:
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x")

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value={"id": "existing"}),
        patch("agent_preditivo.registration_agent.find_open_github_issue") as mock_gh_find,
        patch("agent_preditivo.registration_agent.create_issue") as mock_create,
    ):
        result = register_bug(signal)

    assert result is None
    mock_create.assert_not_called()
    # checagem local (flagged_signals) ja bastou - nao precisa consultar o GitHub
    mock_gh_find.assert_not_called()


def test_register_bug_cria_issue_e_registra_signal_quando_novo() -> None:
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x")

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch("agent_preditivo.registration_agent.find_open_github_issue", return_value=None),
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
        patch("agent_preditivo.registration_agent.find_open_github_issue", return_value=None),
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
        patch("agent_preditivo.registration_agent.find_open_github_issue", return_value=None),
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


def test_register_bug_nao_duplica_quando_issue_equivalente_ja_aberta_no_github() -> None:
    """Issue #77: flagged_signals (Postgres efemero) nao tinha o sinal, mas
    o GitHub ja tem uma issue aberta equivalente - nao deve criar duplicata,
    deve comentar a nova ocorrência na issue existente."""
    signal = BugSignal(service="pix-key-service", signal_type="latencia_alta", detail="p95 alto")

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch(
            "agent_preditivo.registration_agent.find_open_github_issue",
            return_value={"number": 63, "title": "[BUG] latencia_alta em pix-key-service", "url": "x"},
        ),
        patch("agent_preditivo.registration_agent.agent_ops_db.register_signal") as mock_register,
        patch("agent_preditivo.registration_agent._comment_duplicate_occurrence") as mock_comment,
        patch("agent_preditivo.registration_agent.create_issue") as mock_create,
    ):
        result = register_bug(signal)

    assert result is None
    mock_create.assert_not_called()
    mock_register.assert_called_once_with("latencia_alta", "pix-key-service", issue_number=63)
    mock_comment.assert_called_once()
    assert mock_comment.call_args.args[0] == 63


def test_find_open_github_issue_faz_match_por_substring_case_insensitive_no_titulo() -> None:
    fake_result = MagicMock()
    fake_result.stdout = (
        '[{"number": 63, "title": "[FASE 3] Oportunidade: onboarding_get_inexistente", "url": "x"},'
        '{"number": 70, "title": "[BUG] latencia_alta em account-service", "url": "y"}]'
    )

    with patch("agent_preditivo.registration_agent.subprocess.run", return_value=fake_result) as mock_run:
        found = find_open_github_issue("business-story", "ONBOARDING_GET_INEXISTENTE")

    assert found is not None
    assert found["number"] == 63
    assert mock_run.call_args.args[0][:6] == ["gh", "issue", "list", "--state", "open", "--label"]


def test_find_open_github_issue_retorna_none_quando_nao_ha_match() -> None:
    fake_result = MagicMock()
    fake_result.stdout = '[{"number": 70, "title": "[BUG] latencia_alta em account-service", "url": "y"}]'

    with patch("agent_preditivo.registration_agent.subprocess.run", return_value=fake_result):
        found = find_open_github_issue("bug", "erro_alto em transaction-service")

    assert found is None


def test_find_open_github_issue_retorna_none_e_loga_aviso_quando_gh_falha(caplog) -> None:
    """Falha ao consultar o GitHub (rede, auth, CLI ausente) e fail-open -
    nao trava o ciclo do agente, so loga aviso (issue #77)."""
    with (
        caplog.at_level(logging.WARNING, logger="agent_preditivo.registration_agent"),
        patch(
            "agent_preditivo.registration_agent.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["gh"]),
        ),
    ):
        found = find_open_github_issue("bug", "erro_alto em transaction-service")

    assert found is None
    assert any("Falha ao consultar issues abertas" in record.message for record in caplog.records)


def test_register_opportunity_cria_issue_e_notifica_quando_gap(specs_dir) -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_x", veredito="GAP", racional="viola regra Y", observed_behavior="Z", rule_chunks=[]
    )

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch("agent_preditivo.registration_agent.find_open_github_issue", return_value=None),
        patch(
            "agent_preditivo.registration_agent.create_issue",
            return_value=(99, "https://github.com/x/y/issues/99"),
        ) as mock_create,
        patch("agent_preditivo.registration_agent.agent_ops_db.register_signal"),
        patch(
            "agent_preditivo.registration_agent.chat",
            return_value="RESUMO: lacuna\nCONTRATO_AFETADO: regra Y\nSPECS_TECNICAS: nenhuma\nCRITERIO_ACEITE: - item 1\n- item 2",
        ),
        patch("agent_preditivo.registration_agent.notify_issue_created") as mock_notify,
        patch("agent_preditivo.registration_agent._commit_and_push_spec") as mock_commit,
    ):
        result = register_opportunity(finding, scenario_path=None)

    assert result == 99
    mock_create.assert_called_once()
    mock_commit.assert_called_once()
    mock_notify.assert_called_once_with(99, "[FASE 3] Oportunidade: cenario_x", "business-story", "https://github.com/x/y/issues/99")


def test_register_opportunity_commita_e_empurra_spec_antes_de_criar_issue(specs_dir) -> None:
    """Issue #44: a spec precisa existir no remoto antes da issue ser
    aberta, ja que o agent-local roda em um clone separado."""
    finding = OpportunityFinding(
        scenario_name="cenario_x", veredito="GAP", racional="viola regra Y", observed_behavior="Z", rule_chunks=[]
    )
    chamadas = []

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch("agent_preditivo.registration_agent.find_open_github_issue", return_value=None),
        patch(
            "agent_preditivo.registration_agent.create_issue",
            side_effect=lambda *a, **k: chamadas.append("create_issue") or (99, "https://github.com/x/y/issues/99"),
        ),
        patch("agent_preditivo.registration_agent.agent_ops_db.register_signal"),
        patch(
            "agent_preditivo.registration_agent.chat",
            return_value="RESUMO: lacuna\nCONTRATO_AFETADO: regra Y\nSPECS_TECNICAS: nenhuma\nCRITERIO_ACEITE: - item 1\n- item 2",
        ),
        patch("agent_preditivo.registration_agent.notify_issue_created"),
        patch(
            "agent_preditivo.registration_agent._commit_and_push_spec",
            side_effect=lambda *a, **k: chamadas.append("commit_and_push"),
        ),
    ):
        register_opportunity(finding, scenario_path=None)

    assert chamadas == ["commit_and_push", "create_issue"]


def test_commit_and_push_spec_executa_add_commit_push_do_arquivo(specs_dir) -> None:
    from agent_preditivo.registration_agent import _commit_and_push_spec

    spec_path = specs_dir / "24-exemplo.md"
    spec_path.write_text("x", encoding="utf-8")

    with patch("agent_preditivo.registration_agent.subprocess.run") as mock_run:
        _commit_and_push_spec(spec_path)

    commands = [call.args[0] for call in mock_run.call_args_list]
    assert commands[0][:2] == ["git", "add"]
    assert "specs/business/24-exemplo.md" in commands[0][2]
    assert commands[1][:2] == ["git", "commit"]
    assert commands[2] == ["git", "push", "origin", "main"]


def test_register_opportunity_nao_cria_issue_quando_sem_gap() -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_x", veredito="SEM_GAP", racional="ok", observed_behavior="ok", rule_chunks=[]
    )

    with patch("agent_preditivo.registration_agent.create_issue") as mock_create:
        result = register_opportunity(finding, scenario_path=None)

    assert result is None
    mock_create.assert_not_called()


def test_register_opportunity_nao_duplica_quando_issue_equivalente_ja_aberta_no_github(specs_dir) -> None:
    """Issue #77, requisito 3: reproduz o caso real #63/#68 - mesmo cenario
    ('onboarding_get_inexistente') gerando issue e spec de negocio
    duplicadas em execucoes diferentes do agente de oportunidade, porque
    flagged_signals (Postgres efemero) nao sobrevive entre ambientes. Com a
    checagem no GitHub, a segunda execucao nao deve criar issue NEM spec
    nova (a spec so e escrita depois da checagem, ver format_opportunity_issue)."""
    finding = OpportunityFinding(
        scenario_name="onboarding_get_inexistente",
        veredito="GAP",
        racional="404 com ONBOARDING_NOT_FOUND confirmado de novo",
        observed_behavior="GET /v1/onboarding/{id inexistente} retornou 404",
        rule_chunks=[],
    )

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch(
            "agent_preditivo.registration_agent.find_open_github_issue",
            return_value={
                "number": 63,
                "title": "[FASE 3] Oportunidade: onboarding_get_inexistente",
                "url": "x",
            },
        ),
        patch("agent_preditivo.registration_agent.agent_ops_db.register_signal") as mock_register,
        patch("agent_preditivo.registration_agent._comment_duplicate_occurrence") as mock_comment,
        patch("agent_preditivo.registration_agent.create_issue") as mock_create,
        patch("agent_preditivo.registration_agent._commit_and_push_spec") as mock_commit,
    ):
        result = register_opportunity(finding, scenario_path=None)

    assert result is None
    mock_create.assert_not_called()
    mock_commit.assert_not_called()  # nenhuma spec nova commitada - evita o caso real 25/26
    assert list(specs_dir.glob("*.md")) == []  # nenhuma spec nova escrita em disco
    mock_register.assert_called_once_with("onboarding_get_inexistente", "oportunidade", issue_number=63)
    mock_comment.assert_called_once()
    assert mock_comment.call_args.args[0] == 63


def test_register_opportunity_cria_issue_quando_github_nao_tem_equivalente(specs_dir) -> None:
    """Sinal genuinamente novo (sem equivalente nem no banco local nem no
    GitHub) continua gerando issue normalmente (issue #77, requisito 4)."""
    finding = OpportunityFinding(
        scenario_name="cenario_inedito", veredito="GAP", racional="viola regra Z", observed_behavior="W", rule_chunks=[]
    )

    with (
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch("agent_preditivo.registration_agent.find_open_github_issue", return_value=None),
        patch(
            "agent_preditivo.registration_agent.create_issue",
            return_value=(101, "https://github.com/x/y/issues/101"),
        ) as mock_create,
        patch("agent_preditivo.registration_agent.agent_ops_db.register_signal"),
        patch(
            "agent_preditivo.registration_agent.chat",
            return_value="RESUMO: r\nCONTRATO_AFETADO: c\nSPECS_TECNICAS: nenhuma\nCRITERIO_ACEITE: - item 1\n- item 2",
        ),
        patch("agent_preditivo.registration_agent.notify_issue_created"),
        patch("agent_preditivo.registration_agent._commit_and_push_spec") as mock_commit,
    ):
        result = register_opportunity(finding, scenario_path=None)

    assert result == 101
    mock_create.assert_called_once()
    mock_commit.assert_called_once()


def test_register_bug_loga_info_quando_dedup(caplog) -> None:
    """Issue #33: decisao de nao reabrir issue (dedup) precisa ficar
    visivel no log, nao so no retorno None silencioso."""
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x")

    with (
        caplog.at_level(logging.INFO, logger="agent_preditivo.registration_agent"),
        patch(
            "agent_preditivo.registration_agent.agent_ops_db.find_open_signal",
            return_value={"id": "existing", "issue_number": 7},
        ),
        patch("agent_preditivo.registration_agent.create_issue") as mock_create,
    ):
        result = register_bug(signal)

    assert result is None
    mock_create.assert_not_called()
    messages = [record.message for record in caplog.records]
    assert any("dedup" in m for m in messages)


def test_register_bug_loga_info_quando_issue_criada(caplog) -> None:
    signal = BugSignal(service="transaction-service", signal_type="erro_alto", detail="x")

    with (
        caplog.at_level(logging.INFO, logger="agent_preditivo.registration_agent"),
        patch("agent_preditivo.registration_agent.agent_ops_db.find_open_signal", return_value=None),
        patch(
            "agent_preditivo.registration_agent.create_issue",
            return_value=(42, "https://github.com/x/y/issues/42"),
        ),
        patch("agent_preditivo.registration_agent.agent_ops_db.register_signal"),
        patch("agent_preditivo.registration_agent.chat", return_value="SINAL_QUE_DISPAROU: x\nEVIDENCIA: y"),
        patch("agent_preditivo.registration_agent.notify_issue_created"),
    ):
        register_bug(signal)

    messages = [record.message for record in caplog.records]
    assert any("Issue de bug criada" in m for m in messages)


def test_register_opportunity_loga_info_quando_sem_gap(caplog) -> None:
    finding = OpportunityFinding(
        scenario_name="cenario_x", veredito="SEM_GAP", racional="ok", observed_behavior="ok", rule_chunks=[]
    )

    with caplog.at_level(logging.INFO, logger="agent_preditivo.registration_agent"):
        result = register_opportunity(finding, scenario_path=None)

    assert result is None
    messages = [record.message for record in caplog.records]
    assert any("sem gap" in m.lower() for m in messages)
