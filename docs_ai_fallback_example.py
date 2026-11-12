"""Exemplo de fallback Groq -> Gemini (aiohttp). Nao e carregado pelo bot automaticamente."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp

log = logging.getLogger("hellsing.ai_example")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# UNCERTAIN: verify official docs — Gemini REST pode usar v1beta generateContent
GEMINI_URL_TMPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class AIError(Exception):
    def __init__(self, provider: str, status: int | None, detail: str):
        self.provider = provider
        self.status = status
        self.detail = detail
        super().__init__(f"{provider}: {status} {detail}")


async def _post_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    try:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            text = await resp.text()
            if resp.status == 429:
                raise AIError("rate_limit", 429, text[:300])
            if resp.status >= 400:
                raise AIError("http", resp.status, text[:300])
            if not text.strip():
                raise AIError("empty", resp.status, "resposta vazia")
            return await resp.json(content_type=None)
    except asyncio.TimeoutError as exc:
        raise AIError("timeout", None, f"timeout {timeout}s") from exc
    except aiohttp.ClientError as exc:
        raise AIError("network", None, str(exc)[:300]) from exc


async def chat_with_fallback(
    messages: list[dict[str, str]],
    *,
    groq_key: str | None = None,
    gemini_key: str | None = None,
    groq_model: str = "llama-3.1-8b-instant",
    gemini_model: str = "gemini-2.0-flash",
    timeout: float = 20.0,
    max_retries: int = 2,
) -> tuple[str, str]:
    """Tenta Groq; em falha, Gemini. Retorna (texto, provedor)."""
    groq_key = groq_key or os.getenv("GROQ_API_KEY", "")
    gemini_key = gemini_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")

    async with aiohttp.ClientSession() as session:
        if groq_key:
            for attempt in range(max_retries + 1):
                try:
                    data = await _post_json(
                        session,
                        GROQ_URL,
                        headers={
                            "Authorization": f"Bearer {groq_key}",
                            "Content-Type": "application/json",
                        },
                        payload={
                            "model": groq_model,
                            "messages": messages,
                            "temperature": 0.7,
                        },
                        timeout=timeout,
                    )
                    content = data["choices"][0]["message"]["content"]
                    if not content:
                        raise AIError("groq", 200, "content vazio")
                    return str(content), "groq"
                except AIError as exc:
                    log.warning("Groq attempt %s failed: %s", attempt, exc)
                    if exc.status == 429:
                        await asyncio.sleep(min(2 ** attempt, 8))
                    elif attempt >= max_retries:
                        break
                    else:
                        await asyncio.sleep(0.5 * (attempt + 1))

        if gemini_key:
            # UNCERTAIN: verify official docs for exact model IDs and response shape
            url = GEMINI_URL_TMPL.format(model=gemini_model) + f"?key={gemini_key}"
            # Flatten OpenAI-style messages into a single user prompt for simplicity
            prompt = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)
            for attempt in range(max_retries + 1):
                try:
                    data = await _post_json(
                        session,
                        url,
                        headers={"Content-Type": "application/json"},
                        payload={
                            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        },
                        timeout=timeout,
                    )
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
                    if not text.strip():
                        raise AIError("gemini", 200, "resposta vazia")
                    return text, "gemini"
                except AIError as exc:
                    log.warning("Gemini attempt %s failed: %s", attempt, exc)
                    if exc.status == 429:
                        await asyncio.sleep(min(2 ** attempt, 8))
                    elif attempt >= max_retries:
                        break
                    else:
                        await asyncio.sleep(0.5 * (attempt + 1))

    raise AIError("all", None, "Nenhum provedor respondeu")
