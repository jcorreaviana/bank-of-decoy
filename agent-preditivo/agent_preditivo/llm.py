"""Wrapper fino sobre o Ollama local (llama3.2:3b), usado tanto pelo
agente preditivo (classificacao bug/oportunidade, julgamento de gap)
quanto pelo agente de registro (escrita da issue), com system prompts
diferentes conforme quem chama (specs/business/13-agente-preditivo-registro.md)."""

import ollama

from agent_preditivo.config import get_settings


def chat(system_prompt: str, user_message: str, model: str | None = None, temperature: float = 0.2) -> str:
    model = model or get_settings().ollama_model
    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        options={"temperature": temperature},
    )
    return response["message"]["content"]
