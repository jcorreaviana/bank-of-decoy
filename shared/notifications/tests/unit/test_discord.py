from unittest.mock import MagicMock, patch

from notifications.discord import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_WARNING,
    notify_agent_error,
    notify_auto_merge,
    notify_issue_created,
    notify_pr_needs_review,
    send_notification,
)


def _mock_response(status_code: int = 204) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return response


def test_send_notification_sem_webhook_configurado_retorna_false_sem_lancar() -> None:
    with patch("notifications.discord._get_webhook_url", return_value=None), patch("httpx.post") as mock_post:
        result = send_notification("titulo", "descricao", COLOR_INFO)

    assert result is False
    mock_post.assert_not_called()


def test_send_notification_sucesso_retorna_true_e_envia_embed_correto() -> None:
    with patch("httpx.post", return_value=_mock_response(204)) as mock_post:
        result = send_notification(
            "titulo", "descricao", COLOR_SUCCESS, fields={"A": "1"}, webhook_url="https://discord.example/webhook"
        )

    assert result is True
    call_kwargs = mock_post.call_args
    assert call_kwargs.args[0] == "https://discord.example/webhook"
    payload = call_kwargs.kwargs["json"]
    embed = payload["embeds"][0]
    assert embed["title"] == "titulo"
    assert embed["description"] == "descricao"
    assert embed["color"] == COLOR_SUCCESS
    assert embed["fields"] == [{"name": "A", "value": "1", "inline": True}]


def test_send_notification_falha_de_rede_retorna_false_sem_lancar() -> None:
    with patch("httpx.post", side_effect=ConnectionError("timeout")):
        result = send_notification("titulo", "descricao", COLOR_ERROR, webhook_url="https://discord.example/webhook")

    assert result is False


def test_send_notification_resposta_de_erro_http_retorna_false_sem_lancar() -> None:
    with patch("httpx.post", return_value=_mock_response(500)):
        result = send_notification("titulo", "descricao", COLOR_ERROR, webhook_url="https://discord.example/webhook")

    assert result is False


def test_notify_issue_created_monta_embed_azul_com_label_e_link() -> None:
    with patch("httpx.post", return_value=_mock_response()) as mock_post:
        notify_issue_created(42, "Título da issue", "bug", "https://github.com/x/y/issues/42", webhook_url="https://x")

    embed = mock_post.call_args.kwargs["json"]["embeds"][0]
    assert embed["color"] == COLOR_INFO
    assert "42" in embed["title"]
    field_names = {f["name"]: f["value"] for f in embed["fields"]}
    assert field_names["Label"] == "bug"
    assert field_names["Link"] == "https://github.com/x/y/issues/42"


def test_notify_pr_needs_review_monta_embed_amarelo_com_score_e_threshold() -> None:
    with patch("httpx.post", return_value=_mock_response()) as mock_post:
        notify_pr_needs_review(7, "https://github.com/x/y/pull/7", score=56.0, threshold=20.0, webhook_url="https://x")

    embed = mock_post.call_args.kwargs["json"]["embeds"][0]
    assert embed["color"] == COLOR_WARNING
    field_names = {f["name"]: f["value"] for f in embed["fields"]}
    assert field_names["Score"] == "56.00"
    assert field_names["Threshold"] == "20.00"


def test_notify_auto_merge_monta_embed_verde() -> None:
    with patch("httpx.post", return_value=_mock_response()) as mock_post:
        notify_auto_merge(22, 23, score=21.06, url="https://github.com/x/y/pull/23", webhook_url="https://x")

    embed = mock_post.call_args.kwargs["json"]["embeds"][0]
    assert embed["color"] == COLOR_SUCCESS
    assert "22" in embed["title"]
    assert "23" in embed["description"]


def test_notify_agent_error_monta_embed_vermelho_com_contexto() -> None:
    with patch("httpx.post", return_value=_mock_response()) as mock_post:
        notify_agent_error("agent-preditivo", "Ollama indisponível", context={"servico": "pix-key-service"}, webhook_url="https://x")

    embed = mock_post.call_args.kwargs["json"]["embeds"][0]
    assert embed["color"] == COLOR_ERROR
    field_names = {f["name"]: f["value"] for f in embed["fields"]}
    assert field_names["Agente"] == "agent-preditivo"
    assert field_names["servico"] == "pix-key-service"
