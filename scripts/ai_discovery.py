from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from dotenv import load_dotenv
from groq import Groq
import google.generativeai as genai

log = logging.getLogger("hellsing.ai_discovery")
load_dotenv()


def _groq_models_sync(api_key: str) -> list[dict[str, Any]]:
    client = Groq(api_key=api_key, timeout=30.0, max_retries=2)
    try:
        response = client.models.list()
        models = []
        for model in response.data:
            context = getattr(model, "context_window", None)
            output = getattr(model, "max_completion_tokens", None)
            models.append({
                "id": model.id,
                "provider": "groq",
                "context_window": context,
                "max_input_tokens": max(0, context - output) if isinstance(context, int) and isinstance(output, int) else None,
                "max_output_tokens": output,
                "available": True,
            })
        return models
    finally:
        client.close()


def _gemini_models_sync(api_key: str) -> list[dict[str, Any]]:
    genai.configure(api_key=api_key)
    models = []
    for model in genai.list_models():
        methods = getattr(model, "supported_generation_methods", []) or []
        if "generateContent" not in methods:
            continue
        models.append({
            "id": model.name.removeprefix("models/"),
            "provider": "gemini",
            "context_window": getattr(model, "input_token_limit", None),
            "max_input_tokens": getattr(model, "input_token_limit", None),
            "max_output_tokens": getattr(model, "output_token_limit", None),
            "supported_methods": methods,
            "available": True,
        })
    return models


async def discover_ai_models() -> dict[str, Any]:
    """Consulta Groq e Gemini em threads, sem bloquear o event loop."""
    result: dict[str, Any] = {
        "groq": {"configured": False, "available": False, "models": [], "error": None},
        "gemini": {"configured": False, "available": False, "models": [], "error": None},
    }
    providers = {
        "groq": (os.getenv("GROQ_API_KEY", "").strip(), _groq_models_sync),
        "gemini": (os.getenv("GEMINI_API_KEY", "").strip(), _gemini_models_sync),
    }

    async def query(name: str, key: str, function) -> None:
        if not key:
            result[name]["error"] = "API key não configurada"
            return
        result[name]["configured"] = True
        try:
            models = await asyncio.to_thread(function, key)
            result[name]["models"] = models
            result[name]["available"] = bool(models)
        except Exception as exc:
            result[name]["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            log.exception("Falha na descoberta de modelos de %s", name)

    await asyncio.gather(*(query(name, key, fn) for name, (key, fn) in providers.items()))
    return result


async def main() -> None:
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    try:
        print(json.dumps(await discover_ai_models(), ensure_ascii=False, indent=2))
    except Exception:
        log.exception("Falha no diagnóstico de modelos")


if __name__ == "__main__":
    asyncio.run(main())
