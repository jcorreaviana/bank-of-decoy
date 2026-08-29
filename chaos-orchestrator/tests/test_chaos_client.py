"""Testes do cliente HTTP contra POST /internal/chaos/config (issue #53) -
sem subir servidor real, via httpx.MockTransport."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pytest

from chaos_client import TOKEN_HEADER, post_chaos_config


def test_envia_url_header_e_payload_corretos(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["header"] = request.headers.get(TOKEN_HEADER)
        captured["body"] = request.read()
        return httpx.Response(200, json={"enabled": True})

    transport = httpx.MockTransport(handler)

    def fake_post(url, *, json, headers, timeout):
        with httpx.Client(transport=transport) as client:
            return client.post(url, json=json, headers=headers, timeout=timeout)

    import chaos_client

    monkeypatch.setattr(chaos_client.httpx, "post", fake_post)

    result = post_chaos_config(
        "http://localhost:8002",
        {"enabled": True, "failure_types": ["degradacao_progressiva"]},
        token="segredo-teste",
    )

    assert captured["url"] == "http://localhost:8002/internal/chaos/config"
    assert captured["header"] == "segredo-teste"
    assert b'"degradacao_progressiva"' in captured["body"]
    assert result == {"enabled": True}


def test_propaga_erro_http_sem_engolir(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error_code": "CHAOS_CONFIG_FORBIDDEN"})

    transport = httpx.MockTransport(handler)

    def fake_post(url, *, json, headers, timeout):
        with httpx.Client(transport=transport) as client:
            return client.post(url, json=json, headers=headers, timeout=timeout)

    import chaos_client

    monkeypatch.setattr(chaos_client.httpx, "post", fake_post)

    with pytest.raises(httpx.HTTPStatusError):
        post_chaos_config("http://localhost:8002", {"enabled": True}, token="token-errado")
