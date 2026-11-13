"""Descoberta automatica de modelos de IA (Groq, Gemini, Hugging Face)."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp

log = logging.getLogger("hellsing.ai_discovery")


def _groq_models_sync(api_key: str) -> list[dict[str, Any]]:
    from groq import Groq
    client = Groq(api_key=api_key)
    try:
        models = []
        for item in client.models.list().data:
            mid = getattr(item, "id", None)
            if not mid:
                continue
            models.append({
                "id": mid,
                "provider": "groq",
                "available": True,
            })
        return models
    finally:
        try:
            client.close()
        except Exception:
            pass


def _gemini_models_sync(api_key: str) -> list[dict[str, Any]]:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    models = []
    for model in genai.list_models():
        methods = getattr(model, "supported_generation_methods", []) or []
        if "generateContent" not in methods:
            continue
        models.append({
            "id": model.name.removeprefix("models/"),
            "provider": "gemini",
            "supported_methods": list(methods),
            "available": True,
        })
    return models


async def _hf_models(api_key: str) -> list[dict[str, Any]]:
    url = "https://router.huggingface.co/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = aiohttp.ClientTimeout(total=25)
    models: list[dict[str, Any]] = []
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                body = (await resp.text())[:200]
                raise RuntimeError(f"HF HTTP {resp.status}: {body}")
            data = await resp.json(content_type=None)
    items = data if isinstance(data, list) else data.get("data") or data.get("models") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        mid = item.get("id") or item.get("name")
        if not mid:
            continue
        models.append({"id": mid, "provider": "huggingface", "available": True})
    return models[:80]


async def discover_ai_models() -> dict[str, Any]:
    result: dict[str, Any] = {
        "groq": {"configured": False, "available": False, "models": [], "error": None},
        "gemini": {"configured": False, "available": False, "models": [], "error": None},
        "huggingface": {"configured": False, "available": False, "models": [], "error": None},
    }

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    hf_key = (
        os.getenv("HUGGINGFACE_API_TOKEN", "").strip()
        or os.getenv("HF_TOKEN", "").strip()
    )

    async def query_sync(name: str, key: str, function) -> None:
        if not key:
            result[name]["error"] = "API key nao configurada"
            return
        result[name]["configured"] = True
        try:
            models = await asyncio.to_thread(function, key)
            result[name]["models"] = models
            result[name]["available"] = bool(models)
        except Exception as exc:
            result[name]["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            log.exception("Falha na descoberta de modelos de %s", name)

    async def query_hf() -> None:
        if not hf_key:
            result["huggingface"]["error"] = "API key nao configurada"
            return
        result["huggingface"]["configured"] = True
        try:
            models = await _hf_models(hf_key)
            result["huggingface"]["models"] = models
            result["huggingface"]["available"] = bool(models)
        except Exception as exc:
            result["huggingface"]["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            log.exception("Falha na descoberta HF")

    await asyncio.gather(
        query_sync("groq", groq_key, _groq_models_sync),
        query_sync("gemini", gemini_key, _gemini_models_sync),
        query_hf(),
    )
    return result


async def main() -> None:
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    print(json.dumps(await discover_ai_models(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
