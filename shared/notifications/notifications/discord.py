"""Notificacoes Discord via webhook de entrada
(specs/business/20-notificacoes-discord-agentes.md) - compartilhado entre
agent-preditivo e agent-local, para nao duplicar a logica de envio.

`send_notification` NUNCA levanta excecao - falha ao notificar (Discord
indisponivel, webhook nao configurado, timeout) e logada e engolida, para
nunca travar o fluxo principal do agente que chamou (criterio de aceite
explicito da spec). Quem quiser saber se a notificacao foi enviada confere
o retorno bool.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5.0

COLOR_SUCCESS = 0x2ECC71  # verde - merge automatico
COLOR_WARNING = 0xF1C40F  # amarelo - aguardando revisao humana
COLOR_ERROR = 0xE74C3C  # vermelho - erro de execucao
COLOR_INFO = 0x3498DB
"""Azul - issue nova aberta. Nao especificado na spec (que so define
verde/amarelo/vermelho para os outros 3 eventos) - decisao de
implementacao documentada aqui."""


def _get_webhook_url() -> str | None:
    return os.environ.get("DISCORD_WEBHOOK_URL") or None


def send_notification(
    title: str, description: str, color: int, fields: dict[str, str] | None = None, webhook_url: str | None = None
) -> bool:
    """Envia um embed simples ao webhook Discord. Retorna True se enviado
    com sucesso, False em qualquer falha (webhook nao configurado, erro de
    rede, resposta de erro) - nunca levanta excecao."""
    webhook_url = webhook_url or _get_webhook_url()
    if not webhook_url:
        logger.warning(
            "DISCORD_WEBHOOK_URL nao configurada - notificacao nao enviada.",
            extra={"context": {"title": title}},
        )
        return False

    embed: dict = {"title": title, "description": description, "color": color}
    if fields:
        embed["fields"] = [{"name": name, "value": value, "inline": True} for name, value in fields.items()]

    try:
        response = httpx.post(webhook_url, json={"embeds": [embed]}, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.error(
            "Falha ao enviar notificacao Discord - fluxo principal do agente segue normalmente.",
            extra={"context": {"error": str(exc), "title": title}},
        )
        return False


def notify_issue_created(issue_number: int, title: str, label: str, url: str, webhook_url: str | None = None) -> bool:
    return send_notification(
        title=f"Nova issue #{issue_number}",
        description=title,
        color=COLOR_INFO,
        fields={"Label": label, "Link": url},
        webhook_url=webhook_url,
    )


def notify_pr_needs_review(
    pr_number: int, url: str, score: float, threshold: float, webhook_url: str | None = None
) -> bool:
    return send_notification(
        title=f"PR #{pr_number} aguardando revisão humana",
        description=f"Score de risco {score:.2f} ≥ threshold {threshold:.2f} - merge não é automático.",
        color=COLOR_WARNING,
        fields={"Score": f"{score:.2f}", "Threshold": f"{threshold:.2f}", "Link": url},
        webhook_url=webhook_url,
    )


def notify_auto_merge(
    issue_number: int, pr_number: int, score: float, url: str, webhook_url: str | None = None
) -> bool:
    return send_notification(
        title=f"Merge automático: issue #{issue_number}",
        description=f"PR #{pr_number} aprovado e mergeado automaticamente pelo agent-local (score {score:.2f}).",
        color=COLOR_SUCCESS,
        fields={"Score": f"{score:.2f}", "Link": url},
        webhook_url=webhook_url,
    )


def notify_agent_error(
    agent_name: str, error_message: str, context: dict[str, str] | None = None, webhook_url: str | None = None
) -> bool:
    fields = {"Agente": agent_name}
    if context:
        fields.update(context)
    return send_notification(
        title=f"Erro no {agent_name}",
        description=error_message,
        color=COLOR_ERROR,
        fields=fields,
        webhook_url=webhook_url,
    )
