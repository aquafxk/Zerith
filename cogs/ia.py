"""Integrações de IA e geração de imagens com diagnóstico real de conectividade."""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from core import (
    AI_CD,
    IMAGE_CD,
    OPENROUTER_KEY,
    GEMINI_KEY,
    NVIDIA_KEY,
    OPENAI_KEY,
    GROQ_KEY,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_ACCOUNT_ID,
    POLLINATIONS_KEY,
    STABLE_DIFFUSION_KEY,
    emb,
    get_user,
    update_user,
    send_private_after_defer,
    get_db,
    log,
)

SYSTEM_PROMPT = (
    "Você é Zerith, uma personagem original com personalidade de garota de anime, "
    "integrada ao bot RANDOM • HELLSING. Responda sempre em português brasileiro. "
    "Sua personalidade combina doçura, energia, humor caótico, provocações leves "
    "estilo tsundere e sarcasmo moderado. Você pode usar gírias e palavrões leves "
    "em brincadeiras quando a conversa já estiver descontraída, sem humilhar ou "
    "perseguir ninguém. Em assuntos técnicos, seja precisa e objetiva. Em assuntos "
    "sérios, abandone a zoeira e responda com calma e respeito. Não invente fatos, "
    "não finja ser uma pessoa real e não estabeleça relacionamento romântico com usuários."
)

_ZERITH_STYLE_GUIDANCE = {
    "fofa": "Use um tom mais gentil, acolhedor e expressivo, sem exagerar nos emojis.",
    "tsundere": "Use provocações leves e humor de falsa impaciência, mas continue prestativa e respeitosa.",
    "zoeira": "Use humor mais caótico e brincalhão; palavrões moderados só se combinarem com o contexto.",
    "energetica": "Use energia, entusiasmo e reações expressivas sem perder a clareza.",
    "direta": "Priorize respostas curtas, técnicas e objetivas; evite rodeios e floreios.",
    "acolhedora": "Reduza sarcasmo e brincadeiras; responda com paciência, empatia e clareza.",
    "equilibrada": "Misture os traços naturalmente e escolha o tom conforme o assunto e a mensagem atual.",
}


def build_zerith_system_prompt(current_style: str = "equilibrada", learned_style: str = "equilibrada") -> str:
    """Monta as instruções de Zerith usando o tom atual e a preferência observada."""
    current = _ZERITH_STYLE_GUIDANCE.get(current_style, _ZERITH_STYLE_GUIDANCE["equilibrada"])
    learned = _ZERITH_STYLE_GUIDANCE.get(learned_style, _ZERITH_STYLE_GUIDANCE["equilibrada"])
    return (
        f"{SYSTEM_PROMPT}\n"
        f"Ajuste de tom para esta mensagem: {current}\n"
        f"Tendência de conversa observada para este usuário: {learned}\n"
        "A mensagem atual e o contexto têm prioridade sobre qualquer tendência aprendida. "
        "Não force uma personalidade quando ela atrapalhar a resposta."
    )
MAX_DISCORD_IMAGE_BYTES = 7_500_000

OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip()
# glm-4.7-flash costuma devolver HTTP 200 com payload vazio em várias contas.
# llama-3.1-8b-instruct continua estável no endpoint /ai/run.
DEFAULT_CLOUDFLARE_MODEL = "@cf/meta/llama-3.1-8b-instruct"
CLOUDFLARE_MODEL = os.getenv("CLOUDFLARE_MODEL", DEFAULT_CLOUDFLARE_MODEL).strip() or DEFAULT_CLOUDFLARE_MODEL
# Modelos conhecidos por resposta vazia ou descontinuados — força o padrão estável.
_BROKEN_CLOUDFLARE_MODELS = {
    "@cf/zai-org/glm-4.7-flash",
    "@cf/meta/llama-3.1-8b-instruct-awq",
    "@cf/meta/llama-3.1-70b-instruct",
    "@cf/meta/llama-3-8b-instruct",
    "@cf/meta/llama-3-8b-instruct-awq",
}
if CLOUDFLARE_MODEL in _BROKEN_CLOUDFLARE_MODELS:
    CLOUDFLARE_MODEL = DEFAULT_CLOUDFLARE_MODEL
POLLINATIONS_IMAGE_MODEL = os.getenv("POLLINATIONS_IMAGE_MODEL", "black-forest-labs/flux.1-schnell")
STABILITY_IMAGE_ENDPOINT = os.getenv(
    "STABILITY_IMAGE_ENDPOINT",
    "https://api.stability.ai/v2beta/stable-image/generate/core",
)

PROVIDER_KEYS = {
    "openrouter": OPENROUTER_KEY,
    "gemini": GEMINI_KEY,
    "nvidia": NVIDIA_KEY,
    "openai": OPENAI_KEY,
    "groq": GROQ_KEY,
    "cloudflare": CLOUDFLARE_API_TOKEN if CLOUDFLARE_ACCOUNT_ID else None,
}
PROVIDER_MODELS = {
    "openrouter": OPENROUTER_MODEL,
    "gemini": GEMINI_MODEL,
    "nvidia": NVIDIA_MODEL or "catálogo automático",
    "openai": OPENAI_MODEL,
    "groq": GROQ_MODEL,
    "cloudflare": CLOUDFLARE_MODEL,
}
try:
    MODEL_PROBE_LIMIT = max(1, min(int(os.getenv("AI_MODEL_PROBE_LIMIT", "50")), 50))
except ValueError:
    MODEL_PROBE_LIMIT = 50
MODEL_CATALOG_CACHE_SECONDS = 3600
try:
    PROVIDER_TIMEOUT = max(8, min(int(os.getenv("AI_PROVIDER_TIMEOUT_SEC", "120")), 300))
except ValueError:
    PROVIDER_TIMEOUT = 120
# Prazo total somando todos os provedores do fallback. Fica abaixo dos 15 min em que o Discord
# invalida o token de uma interação; sem isso 5 provedores x 120 s estourariam esse limite.
try:
    TOTAL_TIMEOUT = max(PROVIDER_TIMEOUT, min(int(os.getenv("AI_TOTAL_TIMEOUT_SEC", "720")), 840))
except ValueError:
    TOTAL_TIMEOUT = max(PROVIDER_TIMEOUT, 720)
MIN_ATTEMPT_SECONDS = 5  # não inicia uma tentativa com menos tempo que isso no prazo total
# O timeout HTTP precisa ser maior que o do provedor; senão o aiohttp corta a chamada antes (total=30 antigo).
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=PROVIDER_TIMEOUT + 15, connect=8, sock_read=PROVIDER_TIMEOUT + 5)
# Cada modelo da NVIDIA recebe uma fração do tempo do provedor (até 6 candidatos dividem o total).
NVIDIA_MODEL_TIMEOUT = max(12, min(PROVIDER_TIMEOUT // 3, 60))


# Padrões que não servem para chat completion (áudio, visão-only, guard, TTS, descontinuados).
_CHAT_INCOMPATIBLE = {
    "groq": (
        "whisper", "canopylabs", "prompt-guard", "llama-guard", "llama-prompt-guard",
        "distil-whisper", "playai", "orpheus",
    ),
    "openai": (
        "whisper", "tts", "dall-e", "davinci", "babbage", "curie", "ada",
        "moderation", "embedding", "text-embedding", "gpt-image",
    ),
    "gemini": (
        "gemini-2.5", "tts", "preview-tts", "imagen", "veo", "embedding",
    ),
    "openrouter": (
        "whisper", "tts", "vision", "image", "moderation", "embedding",
    ),
    "nvidia": (
        "whisper", "tts", "vision", "embed", "rerank", "nemotron-3-nano-omni",
        "ai-synthetic-video", "yi-large", "fuyu", "jamba", "adept/",
        "kosmos", "phi-3-vision", "phi-3.5-moe", "muse-glimmer",
        "codellama", "llama2", "llama-guard", "starcoder", "dbrx",
        "deepseek-coder-6.7", "codegemma", "granite-3.0", "granite-34b",
        "sea-lion", "minimax", "recurrentgemma", "gemma-2b", "gemma-3-",
        "nemotron-3-ultra", "nemotron-3.5-super",
    ),
}


def _filter_chat_compatible_models(provider: str, models: list[str]) -> list[str]:
    """Remove modelos incompatíveis com chat completion para deixar a varredura limpa."""
    bad = _CHAT_INCOMPATIBLE.get(provider, ())
    if not bad:
        return models
    filtered = []
    for m in models:
        low = m.lower()
        if any(b in low for b in bad):
            continue
        # Groq: o llama-3.3-70b-versatile retorna 404 em várias contas.
        if provider == "groq" and "llama-3.3-70b-versatile" in low:
            continue
        filtered.append(m)
    return filtered


class ProviderError(RuntimeError):
    def __init__(self, provider: str, status: Optional[int], detail: str):
        self.provider = provider
        self.status = status
        self.detail = detail[:280]
        super().__init__(f"{provider}: HTTP {status or 'network'} — {self.detail}")


class IA(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_checks: dict[str, tuple[float, bool, str]] = {}
        # Evita rajadas simultâneas contra provedores externos. O limite é local
        # ao processo; cada provedor ainda pode impor cotas próprias.
        self._api_semaphore = asyncio.Semaphore(4)
        # Catálogos dinâmicos: evita consultar a API a cada mensagem.
        self._model_catalog_cache: dict[str, tuple[float, list[str]]] = {}
        self._model_catalog_locks = {
            name: asyncio.Lock() for name in ("openrouter", "gemini", "nvidia", "openai", "groq", "cloudflare")
        }
        # Primeiro modelo de cada provedor que passou por uma geração real.
        self._working_models: dict[str, str] = {}

    async def build_user_zerith_prompt(self, guild_id: int, user_id: int, message: str) -> str:
        """Atualiza preferências não sensíveis e gera o prompt contextual do usuário."""
        text = message.casefold().strip()
        if re.search(r"\b(sem brincadeira|falando sério|assunto sério|preciso de ajuda|é urgente)\b", text):
            current_style = "acolhedora"
        elif re.search(r"(kkkk+|rsrs+|haha+|😂|🤣|zoeira|brincadeira|meme)", text):
            current_style = "zoeira"
        elif re.search(r"\b(por favor|obrigad[oa]|valeu|por gentileza)\b", text):
            current_style = "fofa"
        elif text.count("!") >= 2 or re.search(r"(🔥|✨|🎉|!!!)", text):
            current_style = "energetica"
        elif re.match(r"^(faz|manda|mostra|resume|resuma|explica|corrige|resolve|implementa)\b", text):
            current_style = "direta"
        else:
            current_style = "equilibrada"

        db = get_db()
        cursor = await db.execute(
            "SELECT style_scores FROM ai_user_profiles WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        try:
            scores = json.loads(row["style_scores"]) if row and row["style_scores"] else {}
        except (TypeError, ValueError):
            scores = {}
        if not isinstance(scores, dict):
            scores = {}
        allowed = {"fofa", "zoeira", "energetica", "direta", "acolhedora"}
        clean_scores = {}
        for key, value in scores.items():
            if str(key) in allowed:
                try:
                    clean_scores[str(key)] = max(0, min(int(value), 100))
                except (TypeError, ValueError):
                    continue
        scores = clean_scores
        if current_style != "equilibrada":
            scores[current_style] = min(scores.get(current_style, 0) + 1, 100)
            await db.execute(
                "INSERT INTO ai_user_profiles (guild_id, user_id, style_scores, interactions, updated_at) "
                "VALUES (?, ?, ?, 1, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "style_scores=excluded.style_scores, interactions=ai_user_profiles.interactions+1, "
                "updated_at=excluded.updated_at",
                (guild_id, user_id, json.dumps(scores, ensure_ascii=False), int(time.time())),
            )
            await db.commit()
        learned_style = max(scores, key=scores.get) if scores and max(scores.values()) >= 2 else "equilibrada"
        return build_zerith_system_prompt(current_style, learned_style)

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession(timeout=HTTP_TIMEOUT)

    async def cog_unload(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def _json_post(self, provider: str, url: str, *, headers: dict, payload: dict) -> dict:
        """POST com concorrência limitada e retentativa curta para 429/5xx."""
        if not self.session or self.session.closed:
            raise ProviderError(provider, None, "sessão HTTP indisponível")

        async with self._api_semaphore:
            for attempt in range(3):
                retry_delay: Optional[float] = None
                try:
                    async with self.session.post(url, headers=headers, json=payload) as response:
                        raw = await response.text()
                        status = response.status

                        if status == 429 or 500 <= status < 600:
                            if attempt < 2:
                                header_value = response.headers.get("Retry-After")
                                try:
                                    retry_delay = float(header_value) if header_value else None
                                except (TypeError, ValueError):
                                    retry_delay = None
                                if retry_delay is None:
                                    retry_delay = float(2 ** attempt)
                                # Não repete antes do tempo solicitado pelo provedor.
                                # Se a espera exigida for longa, deixa o fallback agir.
                                if 0.25 <= retry_delay <= 8:
                                    log.warning(
                                        "API %s respondeu HTTP %s; nova tentativa %d/2 em %.1fs.",
                                        provider,
                                        status,
                                        attempt + 1,
                                        retry_delay,
                                    )
                                else:
                                    retry_delay = None

                        if retry_delay is None and not 200 <= status < 300:
                            # Não registra cabeçalhos nem URLs com credenciais.
                            log.warning("API %s respondeu HTTP %s: %s", provider, status, raw[:280])
                            raise ProviderError(provider, status, raw)

                        if retry_delay is None:
                            try:
                                import json
                                return json.loads(raw)
                            except ValueError as exc:
                                raise ProviderError(
                                    provider, status, "resposta não era JSON válido"
                                ) from exc

                    await asyncio.sleep(retry_delay)
                except asyncio.TimeoutError as exc:
                    raise ProviderError(provider, None, "tempo limite excedido") from exc
                except aiohttp.ClientError as exc:
                    raise ProviderError(provider, None, type(exc).__name__) from exc

        raise ProviderError(provider, 429, "limite temporário do provedor; retentativas esgotadas")

    async def call_openai_compatible(
        self,
        provider: str,
        url: str,
        key: str,
        model: str,
        prompt: str,
        *,
        max_tokens: int = 450,
        temperature: float = 0.7,
        chat_messages: Optional[list[dict[str, str]]] = None,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        payload = {
            "model": model,
            "messages": chat_messages if chat_messages else [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt[:7000]},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = await self._json_post(
            provider,
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            payload=payload,
        )
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(provider, 200, "a API não retornou choices")
        text = choices[0].get("message", {}).get("content")
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        if not isinstance(text, str) or not text.strip():
            raise ProviderError(provider, 200, "resposta vazia")
        return text.strip()

    async def call_openrouter(self, prompt: str, *, max_tokens: int = 450, system_prompt: str = SYSTEM_PROMPT) -> str:
        if not OPENROUTER_KEY:
            raise ProviderError("openrouter", None, "chave ausente")
        endpoint = "https://openrouter.ai/api/v1/chat/completions"
        selected = self._working_models.get("openrouter", OPENROUTER_MODEL)
        try:
            answer = await self.call_openai_compatible(
                "openrouter", endpoint, OPENROUTER_KEY, selected, prompt, max_tokens=max_tokens, system_prompt=system_prompt
            )
            self._working_models["openrouter"] = selected
            return answer
        except ProviderError as primary_error:
            # Chave inválida ou cota esgotada não melhora trocando o modelo.
            if primary_error.status not in (400, 404, 422):
                raise
            try:
                candidates = await self._openrouter_free_models()
            except ProviderError:
                raise primary_error
            last_error = primary_error
            for model in [item for item in candidates if item != selected][:5]:
                try:
                    answer = await self.call_openai_compatible(
                        "openrouter", endpoint, OPENROUTER_KEY, model, prompt, max_tokens=max_tokens, system_prompt=system_prompt
                    )
                    self._working_models["openrouter"] = model
                    return answer
                except ProviderError as exc:
                    last_error = exc
                    if exc.status in (401, 403, 429):
                        break
            raise last_error

    async def _get_json(self, provider: str, url: str, *, headers: dict | None = None, params: dict | None = None) -> dict:
        if not self.session or self.session.closed:
            raise ProviderError(provider, None, "sessão HTTP indisponível")
        try:
            async with self.session.get(url, headers=headers or {}, params=params) as response:
                raw = await response.text()
                if not 200 <= response.status < 300:
                    raise ProviderError(provider, response.status, raw[:240])
                try:
                    import json
                    payload = json.loads(raw)
                except ValueError as exc:
                    raise ProviderError(provider, response.status, "catálogo não retornou JSON válido") from exc
                if not isinstance(payload, dict):
                    raise ProviderError(provider, response.status, "formato inesperado no catálogo")
                return payload
        except asyncio.TimeoutError as exc:
            raise ProviderError(provider, None, "tempo limite ao consultar catálogo") from exc
        except aiohttp.ClientError as exc:
            raise ProviderError(provider, None, type(exc).__name__) from exc

    async def _nvidia_models(self, *, refresh: bool = False) -> list[str]:
        """Retorna os modelos publicados no catálogo da NVIDIA, com cache de uma hora."""
        if not NVIDIA_KEY:
            return []
        now = time.time()
        cached = self._model_catalog_cache.get("nvidia")
        if cached and not refresh and now - cached[0] < MODEL_CATALOG_CACHE_SECONDS:
            return list(cached[1])

        async with self._model_catalog_locks["nvidia"]:
            cached = self._model_catalog_cache.get("nvidia")
            if cached and not refresh and time.time() - cached[0] < MODEL_CATALOG_CACHE_SECONDS:
                return list(cached[1])
            try:
                payload = await self._get_json(
                    "nvidia",
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {NVIDIA_KEY}"},
                )
                entries = payload.get("data", [])
                if not isinstance(entries, list):
                    entries = payload.get("models", []) if isinstance(payload.get("models"), list) else []
                model_ids = [
                    str(item.get("id") or item.get("name", "")).removeprefix("models/")
                    for item in entries
                    if isinstance(item, dict) and (item.get("id") or item.get("name"))
                ]
                model_ids = list(dict.fromkeys(model_ids))
                if NVIDIA_MODEL:
                    model_ids = [NVIDIA_MODEL] + [item for item in model_ids if item != NVIDIA_MODEL]
                model_ids = _filter_chat_compatible_models("nvidia", model_ids)
                self._model_catalog_cache["nvidia"] = (time.time(), model_ids)
                return list(model_ids)
            except ProviderError:
                # Mantém a lista anterior caso uma falha temporária impeça atualizar o catálogo.
                if cached:
                    log.warning("Catálogo NVIDIA indisponível; usando cache antigo.")
                    return list(cached[1])
                raise

    async def call_nvidia(self, prompt: str, *, max_tokens: int = 450, system_prompt: str = SYSTEM_PROMPT) -> str:
        if not NVIDIA_KEY:
            raise ProviderError("nvidia", None, "chave ausente")
        models = await self._nvidia_models()
        if not models:
            raise ProviderError("nvidia", None, "catálogo não retornou modelos disponíveis")
        failures = []
        # A chamada normal usa poucos modelos por vez; o diagnóstico dedicado verifica o catálogo.
        last_ok = self.last_checks.get("nvidia_model")
        preferred = self._working_models.get("nvidia") or (last_ok[2] if last_ok and last_ok[1] else None)
        if preferred in models:
            models = [preferred] + [item for item in models if item != preferred]
        candidates = models[:6]
        for model in candidates:
            try:
                answer = await asyncio.wait_for(
                    self.call_openai_compatible(
                        "nvidia", "https://integrate.api.nvidia.com/v1/chat/completions",
                        NVIDIA_KEY, model, prompt, max_tokens=max_tokens, system_prompt=system_prompt,
                    ), timeout=NVIDIA_MODEL_TIMEOUT
                )
                self.last_checks["nvidia_model"] = (time.time(), True, model)
                self._working_models["nvidia"] = model
                return answer
            except asyncio.TimeoutError:
                failures.append(f"{model}: timeout")
                continue
            except ProviderError as exc:
                failures.append(f"{model}: HTTP {exc.status or 'rede'}")
                if exc.status in (401, 403, 429):
                    break
                # 404 = modelo morto no catálogo; tenta o próximo
                if exc.status == 404:
                    continue
        raise ProviderError("nvidia", 400, "; ".join(failures)[:260] or "nenhum modelo respondeu")

    async def _call_gemini_model(self, prompt: str, model_name: str, max_output_tokens: int, system_prompt: str = SYSTEM_PROMPT) -> str:
        model = urllib.parse.quote(model_name, safe="")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": prompt[:7000]}]}],
            "generationConfig": {"maxOutputTokens": max_output_tokens, "temperature": 0.7},
        }
        data = await self._json_post(
            "gemini", url,
            headers={"x-goog-api-key": GEMINI_KEY or "", "Content-Type": "application/json"},
            payload=payload,
        )
        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback", {}).get("blockReason", "sem candidatos")
            raise ProviderError("gemini", 200, str(feedback))
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text.strip():
            raise ProviderError("gemini", 200, "resposta vazia")
        return text.strip()

    async def call_gemini(
        self, prompt: str, *, model_name: Optional[str] = None, max_output_tokens: int = 450,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> str:
        if not GEMINI_KEY:
            raise ProviderError("gemini", None, "chave ausente")
        selected = model_name or self._working_models.get("gemini") or GEMINI_MODEL
        try:
            answer = await self._call_gemini_model(prompt, selected, max_output_tokens, system_prompt)
            if model_name is None:
                self._working_models["gemini"] = selected
            return answer
        except ProviderError as primary_error:
            # A varredura precisa testar exatamente o modelo recebido, sem fallback oculto.
            if model_name is not None or primary_error.status not in (400, 404, 422):
                raise
            try:
                candidates = await self._gemini_models()
            except ProviderError:
                raise primary_error
            last_error = primary_error
            for model in [item for item in candidates if item != selected][:5]:
                try:
                    answer = await self._call_gemini_model(prompt, model, max_output_tokens, system_prompt)
                    self._working_models["gemini"] = model
                    return answer
                except ProviderError as exc:
                    last_error = exc
                    if exc.status in (401, 403, 429):
                        break
            raise last_error

    async def _compatible_models(self, provider: str, url: str, key: str, *, refresh: bool = False) -> list[str]:
        """Lista modelos de endpoints compatíveis com OpenAI; cache por uma hora."""
        if not key:
            return []
        cached = self._model_catalog_cache.get(provider)
        if cached and not refresh and time.time() - cached[0] < MODEL_CATALOG_CACHE_SECONDS:
            return list(cached[1])
        async with self._model_catalog_locks[provider]:
            cached = self._model_catalog_cache.get(provider)
            if cached and not refresh and time.time() - cached[0] < MODEL_CATALOG_CACHE_SECONDS:
                return list(cached[1])
            payload = await self._get_json(
                provider, url, headers={"Authorization": f"Bearer {key}"}
            )
            entries = payload.get("data", [])
            models = [
                str(item.get("id")) for item in entries
                if isinstance(item, dict) and item.get("id")
            ] if isinstance(entries, list) else []
            preferred = {"openai": OPENAI_MODEL, "groq": GROQ_MODEL}.get(provider)
            if preferred:
                models = [preferred] + [m for m in models if m != preferred]
            models = list(dict.fromkeys(models))
            models = _filter_chat_compatible_models(provider, models)
            self._model_catalog_cache[provider] = (time.time(), models)
            return list(models)

    async def _openai_models(self, *, refresh: bool = False) -> list[str]:
        return await self._compatible_models(
            "openai", "https://api.openai.com/v1/models", OPENAI_KEY or "", refresh=refresh
        )

    async def _groq_models(self, *, refresh: bool = False) -> list[str]:
        return await self._compatible_models(
            "groq", "https://api.groq.com/openai/v1/models", GROQ_KEY or "", refresh=refresh
        )

    async def _cloudflare_models(self, *, refresh: bool = False) -> list[str]:
        """Descobre modelos Workers AI com tarefa de geração de texto."""
        if not CLOUDFLARE_API_TOKEN or not CLOUDFLARE_ACCOUNT_ID:
            return []
        cached = self._model_catalog_cache.get("cloudflare")
        if cached and not refresh and time.time() - cached[0] < MODEL_CATALOG_CACHE_SECONDS:
            return list(cached[1])
        async with self._model_catalog_locks["cloudflare"]:
            cached = self._model_catalog_cache.get("cloudflare")
            if cached and not refresh and time.time() - cached[0] < MODEL_CATALOG_CACHE_SECONDS:
                return list(cached[1])
            url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/models/search"
            payload = await self._get_json(
                "cloudflare", url,
                headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
                params={"task": "text-generation", "per_page": "100"},
            )
            entries = payload.get("result", [])
            models = []
            if isinstance(entries, list):
                for item in entries:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") or item.get("id")
                    if name and str(name).startswith("@cf/"):
                        models.append(str(name))
            models = list(dict.fromkeys(models))
            if CLOUDFLARE_MODEL:
                models = [CLOUDFLARE_MODEL] + [m for m in models if m != CLOUDFLARE_MODEL]
            self._model_catalog_cache["cloudflare"] = (time.time(), models)
            return list(models)

    async def call_openai(self, prompt: str, *, max_tokens: int = 450, system_prompt: str = SYSTEM_PROMPT) -> str:
        if not OPENAI_KEY:
            raise ProviderError("openai", None, "chave ausente")
        models = await self._openai_models()
        model = self._working_models.get("openai") or (models[0] if models else OPENAI_MODEL)
        answer = await self.call_openai_compatible(
            "openai", "https://api.openai.com/v1/chat/completions",
            OPENAI_KEY, model, prompt, max_tokens=max_tokens, system_prompt=system_prompt,
        )
        self._working_models["openai"] = model
        return answer

    async def call_groq(self, prompt: str, *, max_tokens: int = 450, system_prompt: str = SYSTEM_PROMPT) -> str:
        if not GROQ_KEY:
            raise ProviderError("groq", None, "chave ausente")
        models = await self._groq_models()
        model = self._working_models.get("groq") or (models[0] if models else GROQ_MODEL)
        answer = await self.call_openai_compatible(
            "groq", "https://api.groq.com/openai/v1/chat/completions",
            GROQ_KEY, model, prompt, max_tokens=max_tokens, system_prompt=system_prompt,
        )
        self._working_models["groq"] = model
        return answer

    async def call_cloudflare(
        self, prompt: str, *, max_tokens: int = 450, system_prompt: str = SYSTEM_PROMPT,
        chat_messages: Optional[list[dict[str, str]]] = None,
    ) -> str:
        if not CLOUDFLARE_API_TOKEN or not CLOUDFLARE_ACCOUNT_ID:
            raise ProviderError("cloudflare", None, "configure CLOUDFLARE_ACCOUNT_ID e CLOUDFLARE_API_TOKEN")
        # A geração não depende do endpoint de catálogo /ai/models/search.
        # Assim, uma falha de listagem (por exemplo, HTTP 403) não bloqueia
        # a inferência quando o token tem acesso ao endpoint /ai/run.
        model = self._working_models.get("cloudflare") or CLOUDFLARE_MODEL
        encoded_model = urllib.parse.quote(model, safe="/@")
        url = (
            f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
            f"/ai/run/{encoded_model}"
        )
        payload = {
            "messages": chat_messages if chat_messages else [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt[:7000]},
            ],
            "max_tokens": max_tokens,
        }
        data = await self._json_post(
            "cloudflare", url,
            headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"},
            payload=payload,
        )
        # Formatos possíveis: result.response | result (str) | result.text | result.output
        result = data.get("result")
        answer = None
        if isinstance(result, str) and result.strip():
            answer = result
        elif isinstance(result, dict):
            for key in ("response", "text", "output", "generated_text", "content"):
                val = result.get(key)
                if isinstance(val, str) and val.strip():
                    answer = val
                    break
                # alguns modelos devolvem content como lista de partes
                if isinstance(val, list):
                    parts = [
                        p.get("text", "") if isinstance(p, dict) else str(p)
                        for p in val
                    ]
                    joined = "".join(parts).strip()
                    if joined:
                        answer = joined
                        break
        if not isinstance(answer, str) or not answer.strip():
            raise ProviderError("cloudflare", 200, "resposta vazia ou formato inesperado")
        self._working_models["cloudflare"] = model
        return answer.strip()

    def _provider_call(self, provider: str):
        return {
            "openrouter": self.call_openrouter,
            "gemini": self.call_gemini,
            "nvidia": self.call_nvidia,
            "openai": self.call_openai,
            "groq": self.call_groq,
            "cloudflare": self.call_cloudflare,
        }.get(provider)

    async def ask_ai(
        self,
        prompt: str,
        provider: str = "auto",
        *,
        fallback: bool = True,
        max_tokens: int = 450,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> tuple[str, str]:
        # OpenAI fora da ordem automática (checklist). OpenRouter primeiro.
        providers = ["openrouter", "groq", "gemini", "nvidia", "openai", "cloudflare"]
        if provider == "auto":
            # Prioriza o último provedor que respondeu, evitando começar sempre por um
            # endpoint lento ou temporariamente indisponível.
            healthy = [
                name for name in providers
                if name != "openai" and self.last_checks.get(name, (0, False, ""))[1]
            ]
            preferred = max(healthy, key=lambda name: self.last_checks[name][0]) if healthy else None
            order = ([preferred] if preferred else []) + [
                name for name in providers if name != preferred and name != "openai"
            ]
            if not order:
                order = ["openrouter", "groq", "cloudflare", "gemini", "nvidia"]
        elif provider in providers:
            # Mesmo quando alguém seleciona um provedor específico, os demais entram
            # como fallback se o primeiro estiver fora do ar ou sem cota.
            order = [provider] + [
                name for name in providers if name != provider and name != "openai"
            ] if fallback else [provider]
        else:
            order = [p for p in providers if p != "openai"]

        attempted = False
        issues: list[str] = []
        deadline = time.monotonic() + TOTAL_TIMEOUT
        for name in order:
            call = self._provider_call(name)
            if not call or not PROVIDER_KEYS.get(name):
                continue
            remaining = deadline - time.monotonic()
            if remaining < MIN_ATTEMPT_SECONDS:
                issues.append("tempo total esgotado")
                break
            attempted = True
            attempt_timeout = min(PROVIDER_TIMEOUT, remaining)
            try:
                if name == "openrouter":
                    operation = self.call_openrouter(prompt, max_tokens=max_tokens, system_prompt=system_prompt)
                elif name == "gemini":
                    operation = self.call_gemini(prompt, max_output_tokens=max_tokens, system_prompt=system_prompt)
                elif name == "nvidia":
                    operation = self.call_nvidia(prompt, max_tokens=max_tokens, system_prompt=system_prompt)
                else:
                    operation = call(prompt, max_tokens=max_tokens, system_prompt=system_prompt)
                answer = await asyncio.wait_for(operation, timeout=attempt_timeout)
                self.last_checks[name] = (time.time(), True, "respondeu")
                return answer, name
            except ProviderError as exc:
                self.last_checks[name] = (time.time(), False, str(exc))
                issues.append(f"{name}: HTTP {exc.status or 'rede'}")
            except asyncio.TimeoutError:
                self.last_checks[name] = (time.time(), False, f"timeout de {attempt_timeout:.0f}s")
                issues.append(f"{name}: timeout")
            except Exception as exc:
                log.exception("Erro inesperado na API %s", name)
                self.last_checks[name] = (time.time(), False, type(exc).__name__)
                issues.append(f"{name}: erro interno")
        if not attempted:
            return "❌ Nenhum provedor de texto está configurado. Cadastre pelo menos uma chave no Ambiente da hospedagem.", "nenhum"
        return f"❌ Nenhum provedor respondeu. Verifique `/ia_status` e `/ia_testar`. Ocorrências: {', '.join(issues)}", "nenhum"

    async def _call_gemini_conversation(
        self, messages: list[dict[str, str]], *, max_output_tokens: int = 450
    ) -> str:
        if not GEMINI_KEY:
            raise ProviderError("gemini", None, "chave ausente")

        system_text = next(
            (str(m.get("content", "")) for m in messages if m.get("role") == "system"),
            SYSTEM_PROMPT,
        )

        # Gemini exige que contents comece com user e alterne user/model.
        # Junta turnos consecutivos do mesmo papel antes de limitar o histórico.
        normalized_contents: list[dict] = []
        for item in messages:
            role = item.get("role")
            if role not in {"user", "assistant"}:
                continue
            target_role = "model" if role == "assistant" else "user"
            content = str(item.get("content", "")).strip()[:1200]
            if not content:
                continue
            if not normalized_contents and target_role != "user":
                # Uma conversa não pode começar com a resposta do modelo.
                continue
            if normalized_contents and normalized_contents[-1]["role"] == target_role:
                normalized_contents[-1]["parts"][0]["text"] += "\n" + content
            else:
                normalized_contents.append({
                    "role": target_role,
                    "parts": [{"text": content}],
                })

        if not normalized_contents or normalized_contents[0]["role"] != "user":
            raise ProviderError("gemini", None, "histórico sem mensagem inicial de usuário")

        # O corte acontece depois da normalização; se cair no meio de um par,
        # descartamos o turno model órfão para manter a alternância válida.
        selected_contents = normalized_contents[-12:]
        if selected_contents and selected_contents[0]["role"] == "model":
            selected_contents = selected_contents[1:]
        if not selected_contents or selected_contents[0]["role"] != "user":
            raise ProviderError("gemini", None, "histórico inválido após truncamento")

        payload = {
            "system_instruction": {"parts": [{"text": system_text}]},
            "contents": selected_contents,
            "generationConfig": {"maxOutputTokens": max_output_tokens, "temperature": 0.7},
        }

        async def _try(model_name: str) -> str:
            model = urllib.parse.quote(model_name, safe="")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            data = await self._json_post(
                "gemini", url,
                headers={"x-goog-api-key": GEMINI_KEY, "Content-Type": "application/json"},
                payload=payload,
            )
            candidates = data.get("candidates") or []
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            answer = "".join(
                part.get("text", "") for part in parts if isinstance(part, dict)
            ).strip()
            if not answer:
                raise ProviderError("gemini", 200, "resposta vazia")
            self._working_models["gemini"] = model_name
            return answer

        selected = self._working_models.get("gemini") or GEMINI_MODEL
        try:
            return await _try(selected)
        except ProviderError as primary_error:
            # Modelo inexistente/descontinuado: tenta o catálogo disponível.
            if primary_error.status not in (400, 404, 422):
                raise
            log.warning(
                "Gemini (conversa): modelo %s falhou com HTTP %s; tentando catálogo.",
                selected, primary_error.status,
            )
            try:
                catalog = await self._gemini_models()
            except ProviderError:
                raise primary_error
            last_error = primary_error
            for model_name in [m for m in catalog if m != selected][:5]:
                try:
                    return await _try(model_name)
                except ProviderError as exc:
                    last_error = exc
                    if exc.status in (401, 403, 429):
                        break
            raise last_error

    async def ask_ai_conversation(
        self, messages: list[dict[str, str]], *, max_tokens: int = 450
    ) -> tuple[str, str]:
        """Envia histórico real (system/user/assistant) a endpoints OpenAI-compatible."""
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
        # Mesma regra do ask_ai: OpenAI fica fora da ordem automática.
        providers = ["openrouter", "groq", "gemini", "nvidia", "cloudflare"]
        healthy = [p for p in providers if self.last_checks.get(p, (0, False, ""))[1]]
        preferred = max(healthy, key=lambda p: self.last_checks[p][0]) if healthy else None
        order = ([preferred] if preferred else []) + [p for p in providers if p != preferred]
        deadline = time.monotonic() + min(TOTAL_TIMEOUT, 90)
        issues = []
        for name in order:
            if not PROVIDER_KEYS.get(name):
                continue
            try:
                if name == "gemini":
                    answer = await asyncio.wait_for(
                        self._call_gemini_conversation(messages, max_output_tokens=max_tokens),
                        timeout=min(PROVIDER_TIMEOUT, max(5, deadline - time.monotonic())),
                    )
                    self.last_checks[name] = (time.time(), True, "respondeu")
                    return answer, name
                if name == "cloudflare":
                    answer = await asyncio.wait_for(
                        self.call_cloudflare("", max_tokens=max_tokens, chat_messages=messages),
                        timeout=min(PROVIDER_TIMEOUT, max(5, deadline - time.monotonic())),
                    )
                    self.last_checks[name] = (time.time(), True, "respondeu")
                    return answer, name
                if name == "openrouter":
                    key, url = OPENROUTER_KEY, "https://openrouter.ai/api/v1/chat/completions"
                    model = self._working_models.get(name, OPENROUTER_MODEL)
                elif name == "groq":
                    models = await self._groq_models()
                    key, url = GROQ_KEY, "https://api.groq.com/openai/v1/chat/completions"
                    model = self._working_models.get(name) or (models[0] if models else GROQ_MODEL)
                elif name == "nvidia":
                    models = await self._nvidia_models()
                    key, url = NVIDIA_KEY, "https://integrate.api.nvidia.com/v1/chat/completions"
                    model = self._working_models.get(name) or (models[0] if models else "")
                else:
                    models = await self._openai_models()
                    key, url = OPENAI_KEY, "https://api.openai.com/v1/chat/completions"
                    model = self._working_models.get(name) or (models[0] if models else OPENAI_MODEL)
                if not model:
                    continue
                remaining = deadline - time.monotonic()
                if remaining < 5:
                    break
                answer = await asyncio.wait_for(
                    self.call_openai_compatible(
                        name, url, key or "", model, "", max_tokens=max_tokens,
                        chat_messages=messages[-13:],
                    ), timeout=min(PROVIDER_TIMEOUT, remaining),
                )
                self._working_models[name] = model
                self.last_checks[name] = (time.time(), True, "respondeu")
                return answer, name
            except Exception as exc:
                self.last_checks[name] = (time.time(), False, type(exc).__name__)
                issues.append(f"{name}: {type(exc).__name__}")
                if isinstance(exc, (ProviderError, asyncio.TimeoutError)):
                    log.warning("IA (conversa): %s falhou: %s", name, exc or type(exc).__name__)
                else:
                    log.exception("IA (conversa): erro inesperado em %s", name)
        return ("❌ Não consegui obter resposta dos provedores de IA. Tente novamente em instantes.", "nenhum")

    async def _openrouter_free_models(self, *, refresh: bool = False) -> list[str]:
        """Descobre modelos gratuitos de texto do OpenRouter, com cache de uma hora."""
        if not OPENROUTER_KEY:
            return []
        cached = self._model_catalog_cache.get("openrouter")
        if cached and not refresh and time.time() - cached[0] < MODEL_CATALOG_CACHE_SECONDS:
            return list(cached[1])
        async with self._model_catalog_locks["openrouter"]:
            cached = self._model_catalog_cache.get("openrouter")
            if cached and not refresh and time.time() - cached[0] < MODEL_CATALOG_CACHE_SECONDS:
                return list(cached[1])
            try:
                payload = await self._get_json(
                    "openrouter",
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                             "HTTP-Referer": "https://discord.com",
                             "X-Title": "RANDOM HELLSING"},
                    params={"output_modalities": "text", "max_price": "0", "sort": "most-popular"},
                )
                entries = payload.get("data", [])
                result = []
                if isinstance(entries, list):
                    for item in entries:
                        if not isinstance(item, dict) or not item.get("id"):
                            continue
                        if str(item["id"]).endswith(":free"):
                            result.append(str(item["id"]))
                if OPENROUTER_MODEL == "openrouter/free":
                    result.insert(0, "openrouter/free")
                models = list(dict.fromkeys(result))
                models = _filter_chat_compatible_models("openrouter", models)
                self._model_catalog_cache["openrouter"] = (time.time(), models)
                return list(models)
            except ProviderError:
                if cached:
                    log.warning("Catálogo OpenRouter indisponível; usando cache antigo.")
                    return list(cached[1])
                raise

    async def _gemini_models(self, *, refresh: bool = False) -> list[str]:
        """Descobre modelos Gemini compatíveis com generateContent, com cache de uma hora."""
        if not GEMINI_KEY:
            return []
        cached = self._model_catalog_cache.get("gemini")
        if cached and not refresh and time.time() - cached[0] < MODEL_CATALOG_CACHE_SECONDS:
            return list(cached[1])
        async with self._model_catalog_locks["gemini"]:
            cached = self._model_catalog_cache.get("gemini")
            if cached and not refresh and time.time() - cached[0] < MODEL_CATALOG_CACHE_SECONDS:
                return list(cached[1])
            try:
                result = []
                page_token = None
                for _page in range(5):
                    params = {"pageSize": "1000"}
                    if page_token:
                        params["pageToken"] = page_token
                    payload = await self._get_json(
                        "gemini",
                        "https://generativelanguage.googleapis.com/v1beta/models",
                        headers={"x-goog-api-key": GEMINI_KEY},
                        params=params,
                    )
                    entries = payload.get("models", [])
                    if isinstance(entries, list):
                        for item in entries:
                            if not isinstance(item, dict):
                                continue
                            methods = item.get("supportedGenerationMethods", [])
                            name = item.get("name")
                            if isinstance(name, str) and "generateContent" in methods:
                                result.append(name.removeprefix("models/"))
                    page_token = payload.get("nextPageToken")
                    if not page_token:
                        break
                models = list(dict.fromkeys(result))
                models = _filter_chat_compatible_models("gemini", models)
                self._model_catalog_cache["gemini"] = (time.time(), models)
                return list(models)
            except ProviderError:
                if cached:
                    log.warning("Catálogo Gemini indisponível; usando cache antigo.")
                    return list(cached[1])
                raise

    async def _test_model(self, provider: str, model: str) -> tuple[bool, str]:
        try:
            prompt = "Responda somente OK."
            if provider == "gemini":
                answer = await asyncio.wait_for(
                    self.call_gemini(prompt, model_name=model, max_output_tokens=8), timeout=18
                )
            elif provider == "nvidia":
                answer = await asyncio.wait_for(
                    self.call_openai_compatible(
                        "nvidia", "https://integrate.api.nvidia.com/v1/chat/completions",
                        NVIDIA_KEY or "", model, prompt, max_tokens=8, temperature=0,
                    ), timeout=18
                )
            elif provider == "openrouter":
                answer = await asyncio.wait_for(
                    self.call_openai_compatible(
                        "openrouter", "https://openrouter.ai/api/v1/chat/completions",
                        OPENROUTER_KEY or "", model, prompt, max_tokens=8, temperature=0,
                    ), timeout=18
                )
            elif provider in ("openai", "groq"):
                key = OPENAI_KEY if provider == "openai" else GROQ_KEY
                base = "https://api.openai.com/v1" if provider == "openai" else "https://api.groq.com/openai/v1"
                answer = await asyncio.wait_for(
                    self.call_openai_compatible(
                        provider, f"{base}/chat/completions", key or "", model,
                        prompt, max_tokens=8, temperature=0,
                    ), timeout=18
                )
            elif provider == "cloudflare":
                old_model = self._working_models.get("cloudflare")
                self._working_models["cloudflare"] = model
                try:
                    answer = await asyncio.wait_for(self.call_cloudflare(prompt, max_tokens=8), timeout=18)
                finally:
                    # O bloco comum abaixo grava o modelo apenas se o teste passou.
                    if old_model is None:
                        self._working_models.pop("cloudflare", None)
                    else:
                        self._working_models["cloudflare"] = old_model
            else:
                return False, "provedor desconhecido"
            if not answer.strip():
                return False, "resposta vazia"
            self._working_models[provider] = model
            if provider == "nvidia":
                self.last_checks["nvidia_model"] = (time.time(), True, model)
            return True, "geração OK"
        except asyncio.TimeoutError:
            return False, "timeout de 18s"
        except ProviderError as exc:
            return False, f"HTTP {exc.status or 'rede'}: {exc.detail[:90]}"
        except Exception as exc:
            log.exception("Teste do modelo %s/%s falhou", provider, model)
            return False, type(exc).__name__

    async def test_all_models(self) -> list[str]:
        """Descobre e testa modelos de texto acessíveis, limitando chamadas por provedor."""
        results: list[str] = []
        catalogs = {
            "openrouter": lambda: self._openrouter_free_models(refresh=True),
            "gemini": lambda: self._gemini_models(refresh=True),
            "nvidia": lambda: self._nvidia_models(refresh=True),
            "openai": lambda: self._openai_models(refresh=True),
            "groq": lambda: self._groq_models(refresh=True),
            "cloudflare": lambda: self._cloudflare_models(refresh=True),
        }
        for provider in ("openrouter", "groq", "cloudflare", "gemini", "nvidia", "openai"):
            if not PROVIDER_KEYS.get(provider):
                results.append(f"⚪ **{provider}:** chave ausente; ignorado")
                continue
            try:
                if provider == "cloudflare":
                    # Testa a inferência com o modelo configurado sem tornar
                    # o catálogo administrativo uma dependência obrigatória.
                    models = [self._working_models.get("cloudflare") or CLOUDFLARE_MODEL]
                else:
                    models = await catalogs[provider]()
            except ProviderError as exc:
                results.append(f"❌ **{provider}:** catálogo falhou — {exc.detail[:100]}")
                continue
            if not models:
                results.append(f"⚠️ **{provider}:** nenhum modelo de texto retornado pelo catálogo")
                continue
            total = len(models)
            candidates = models[:MODEL_PROBE_LIMIT]
            passed = 0
            failed = 0
            lines = []
            tested = 0
            for model in candidates:
                ok, detail = await self._test_model(provider, model)
                tested += 1
                passed += int(ok)
                failed += int(not ok)
                lines.append(f"{'✅' if ok else '❌'} `{model[:72]}` — {detail[:100]}")
                # Credencial inválida, autorização negada ou cota esgotada não serão resolvidas
                # testando mais modelos; evita dezenas de requisições inúteis.
                if not ok and ("HTTP 401" in detail or "HTTP 403" in detail or "HTTP 429" in detail):
                    lines.append("⏭️ Restante interrompido por autenticação/cota do provedor.")
                    break
            self.last_checks[provider] = (
                time.time(), passed > 0, f"{passed}/{tested} modelos responderam"
            )
            results.append(
                f"**{provider.upper()}** — `{passed}` OK / `{failed}` falha(s); "
                f"testados `{tested}` de `{total}` modelos encontrados.\n"
                + "\n".join(lines)
            )
            if total > MODEL_PROBE_LIMIT:
                results[-1] += f"\n-# Limite por provedor: {MODEL_PROBE_LIMIT}."
        return results

    async def _test_provider(self, provider: str) -> tuple[bool, str]:
        call = self._provider_call(provider)
        if not call or not PROVIDER_KEYS.get(provider):
            result = "chave ausente ou provedor inválido"
            self.last_checks[provider] = (time.time(), False, result)
            return False, result
        try:
            await call("Responda somente com: OK")
            result = "conexão e geração confirmadas"
            self.last_checks[provider] = (time.time(), True, result)
            return True, result
        except ProviderError as exc:
            self.last_checks[provider] = (time.time(), False, str(exc))
            return False, str(exc)
        except Exception as exc:
            log.exception("Teste da API %s falhou", provider)
            result = type(exc).__name__
            self.last_checks[provider] = (time.time(), False, result)
            return False, result

    def _status_lines(self) -> list[str]:
        names = {
            "openai": "OpenAI", "groq": "Groq", "cloudflare": "Cloudflare Workers AI",
            "openrouter": "OpenRouter", "gemini": "Gemini", "nvidia": "NVIDIA NIM",
        }
        lines = []
        for key, title in names.items():
            if not PROVIDER_KEYS.get(key):
                lines.append(f"⚪ **{title}:** não configurada")
                continue
            last = self.last_checks.get(key)
            if not last:
                lines.append(f"🔑 **{title}:** chave configurada, ainda não testada")
            else:
                timestamp, ok, detail = last
                icon = "✅" if ok else "⚠️"
                when = datetime.fromtimestamp(timestamp, timezone.utc).astimezone().strftime("%H:%M:%S")
                lines.append(f"{icon} **{title}:** {'respondeu' if ok else 'falhou'} às `{when}` — {detail[:90]}")
                if key == "nvidia" and self.last_checks.get("nvidia_model"):
                    lines.append(f"   Modelo ativo selecionado: `{self.last_checks['nvidia_model'][2]}`")
        lines.append(
            f"{'🔑' if POLLINATIONS_KEY else '⚪'} **Pollinations:** "
            f"{'chave configurada; teste em /gerar_imagem' if POLLINATIONS_KEY else 'chave não configurada'}"
        )
        lines.append(
            f"{'🔑' if STABLE_DIFFUSION_KEY else '⚪'} **Stability AI:** "
            f"{'chave configurada; teste em /gerar_imagem' if STABLE_DIFFUSION_KEY else 'chave não configurada'}"
        )
        return lines

    async def generate_image(self, prompt: str, provider: str = "auto") -> tuple[bytes, str, str]:
        if not self.session or self.session.closed:
            raise ProviderError("imagem", None, "sessão HTTP indisponível")
        prompt = f"{prompt[:700]}, gothic anime illustration, dramatic lighting, detailed background"
        choices = [provider] if provider != "auto" else [
            name for name, configured in (
                ("stability", bool(STABLE_DIFFUSION_KEY)),
                ("pollinations", bool(POLLINATIONS_KEY)),
            ) if configured
        ]
        if not choices:
            raise ProviderError("imagem", None, "configure STABLE_DIFFUSION_KEY ou POLLINATIONS_KEY")

        last_error: Optional[Exception] = None
        for name in choices:
            try:
                if name == "stability":
                    if not STABLE_DIFFUSION_KEY:
                        raise ProviderError(name, None, "STABLE_DIFFUSION_KEY ausente")
                    form = aiohttp.FormData()
                    form.add_field("prompt", prompt)
                    form.add_field("aspect_ratio", "1:1")
                    form.add_field("style_preset", "anime")
                    form.add_field("output_format", "png")
                    async with self.session.post(
                        STABILITY_IMAGE_ENDPOINT,
                        headers={"Authorization": f"Bearer {STABLE_DIFFUSION_KEY}", "Accept": "image/*"},
                        data=form,
                    ) as response:
                        if response.status != 200:
                            body = (await response.text())[:280]
                            raise ProviderError(name, response.status, body)
                        data = await response.read()
                        content_type = response.headers.get("Content-Type", "")
                elif name == "pollinations":
                    if not POLLINATIONS_KEY:
                        raise ProviderError(name, None, "POLLINATIONS_KEY ausente")
                    encoded = urllib.parse.quote(prompt, safe="")
                    url = f"https://gen.pollinations.ai/image/{encoded}"
                    params = {
                        "model": POLLINATIONS_IMAGE_MODEL,
                        "width": "1024",
                        "height": "1024",
                        "nologo": "true",
                    }
                    async with self.session.get(
                        url,
                        params=params,
                        headers={"Authorization": f"Bearer {POLLINATIONS_KEY}", "Accept": "image/*"},
                    ) as response:
                        if response.status != 200:
                            body = (await response.text())[:280]
                            raise ProviderError(name, response.status, body)
                        data = await response.read()
                        content_type = response.headers.get("Content-Type", "")
                else:
                    raise ProviderError(name, None, "provedor de imagem desconhecido")
                if not content_type.lower().startswith("image/") or not data:
                    raise ProviderError(name, 200, "a API não retornou um arquivo de imagem")
                if len(data) > MAX_DISCORD_IMAGE_BYTES:
                    raise ProviderError(name, 200, "imagem ultrapassa o limite local de anexo de 7,5 MB")
                extension = "jpg" if "jpeg" in content_type.lower() else "webp" if "webp" in content_type.lower() else "png"
                return data, f"hellsing_{int(time.time())}.{extension}", name
            except (ProviderError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = exc
                log.warning("Geração de imagem via %s falhou: %s", name, str(exc)[:220])
        if isinstance(last_error, ProviderError):
            raise last_error
        raise ProviderError("imagem", None, str(last_error or "falha desconhecida"))

    @app_commands.command(name="ia", description="Converse com os provedores de IA do Hellsing.")
    @app_commands.describe(pergunta="Sua pergunta", provedor="Provedor a utilizar")
    @app_commands.choices(provedor=[
        app_commands.Choice(name="Automático (fallback)", value="auto"),
        app_commands.Choice(name="OpenRouter", value="openrouter"),
        app_commands.Choice(name="Google Gemini", value="gemini"),
        app_commands.Choice(name="NVIDIA NIM", value="nvidia"),
        app_commands.Choice(name="OpenAI", value="openai"),
        app_commands.Choice(name="Groq", value="groq"),
        app_commands.Choice(name="Cloudflare Workers AI", value="cloudflare"),
    ])
    @app_commands.guild_only()
    async def ia(self, interaction: discord.Interaction, pergunta: str, provedor: Optional[app_commands.Choice[str]] = None):
        gid, uid = interaction.guild_id, interaction.user.id
        user = await get_user(gid, uid)
        now = int(time.time())
        wait = AI_CD - (now - int(user["last_ai"] or 0))
        if wait > 0:
            return await interaction.response.send_message(f"⏳ Aguarde {wait}s.", ephemeral=True)
        await interaction.response.defer(thinking=True)
        await update_user(gid, uid, last_ai=now)
        system_prompt = await self.build_user_zerith_prompt(gid, uid, pergunta[:2500])
        response, used = await self.ask_ai(
            pergunta[:2500], provedor.value if provedor else "auto", system_prompt=system_prompt
        )
        embed = emb("🩸 Zerith responde", response[:3900])
        embed.add_field(name="Provedor", value=f"`{used}`")
        await interaction.followup.send(embed=embed)

    @commands.command(name="ia")
    @commands.guild_only()
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def ia_prefix(self, ctx: commands.Context, *, pergunta: str):
        user = await get_user(ctx.guild.id, ctx.author.id)
        now = int(time.time())
        wait = AI_CD - (now - int(user["last_ai"] or 0))
        if wait > 0:
            return await ctx.reply(f"⏳ Aguarde {wait}s.", mention_author=False)
        await update_user(ctx.guild.id, ctx.author.id, last_ai=now)
        system_prompt = await self.build_user_zerith_prompt(ctx.guild.id, ctx.author.id, pergunta[:2500])
        async with ctx.typing():
            response, used = await self.ask_ai(pergunta[:2500], "auto", system_prompt=system_prompt)
        embed = emb("🩸 Zerith responde", response[:3900])
        embed.add_field(name="Provedor", value=f"`{used}`")
        await ctx.send(embed=embed)

    @app_commands.command(name="ia_status", description="Mostra as chaves configuradas e os últimos testes reais.")
    @app_commands.guild_only()
    async def ia_status(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=emb("🦇 Status dos provedores", "\n".join(self._status_lines())),
            ephemeral=True,
        )

    @commands.command(name="ia_status", aliases=["iastatus"])
    @commands.guild_only()
    async def ia_status_prefix(self, ctx: commands.Context):
        await ctx.reply(embed=emb("🦇 Status dos provedores", "\n".join(self._status_lines())), mention_author=False)

    @app_commands.command(name="ia_testar", description="Testa uma chamada real em um provedor (pode consumir cota).")
    @app_commands.describe(provedor="Provedor que será testado")
    @app_commands.choices(provedor=[
        app_commands.Choice(name="OpenRouter", value="openrouter"),
        app_commands.Choice(name="Gemini", value="gemini"),
        app_commands.Choice(name="NVIDIA NIM", value="nvidia"),
        app_commands.Choice(name="OpenAI", value="openai"),
        app_commands.Choice(name="Groq", value="groq"),
        app_commands.Choice(name="Cloudflare Workers AI", value="cloudflare"),
        app_commands.Choice(name="Todos configurados", value="all"),
    ])
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 60, key=lambda interaction: interaction.guild_id)
    async def ia_testar(self, interaction: discord.Interaction, provedor: app_commands.Choice[str]):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Você precisa de Gerenciar Servidor para testar provedores.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        names = list(PROVIDER_KEYS) if provedor.value == "all" else [provedor.value]
        results = []
        for name in names:
            if not PROVIDER_KEYS.get(name):
                results.append(f"⚪ **{name}:** chave ausente")
                continue
            ok, detail = await self._test_provider(name)
            results.append(f"{'✅' if ok else '❌'} **{name}:** {detail[:160]}")
        await interaction.followup.send(
            embed=emb("🧪 Resultado dos testes de IA", "\n".join(results)),
            ephemeral=True,
        )

    @commands.command(name="ia_testar")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def ia_testar_prefix(self, ctx: commands.Context, provedor: str = "all"):
        allowed = {"openrouter", "gemini", "nvidia", "openai", "groq", "cloudflare", "all"}
        name = provedor.casefold()
        if name not in allowed:
            return await ctx.reply(
                "Use: `;ia_testar all|openai|groq|cloudflare|openrouter|gemini|nvidia`.",
                mention_author=False,
            )
        names = list(PROVIDER_KEYS) if name == "all" else [name]
        results = []
        async with ctx.typing():
            for item in names:
                if not PROVIDER_KEYS.get(item):
                    results.append(f"⚪ **{item}:** chave ausente")
                    continue
                ok, detail = await self._test_provider(item)
                results.append(f"{'✅' if ok else '❌'} **{item}:** {detail[:150]}")
        await ctx.send(embed=emb("🧪 Resultado dos testes de IA", "\n".join(results)))

    @app_commands.command(name="ia_modelos", description="Descobre e testa modelos de texto liberados nas APIs configuradas.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.cooldown(1, 300, key=lambda interaction: interaction.guild_id)
    async def ia_modelos(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Você precisa de Gerenciar Servidor.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        results = await self.test_all_models()
        message = "\n\n".join(results)
        # O Discord limita a descrição do embed a 4096 caracteres.
        for start in range(0, len(message), 3900):
            part = message[start:start + 3900]
            if start == 0:
                await interaction.followup.send(embed=emb("🧪 Varredura de modelos de IA", part), ephemeral=True)
            else:
                await interaction.followup.send(part, ephemeral=True)

    @commands.command(name="ia_modelos")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.cooldown(1, 300, commands.BucketType.guild)
    async def ia_modelos_prefix(self, ctx: commands.Context):
        async with ctx.typing():
            results = await self.test_all_models()
        message = "\n\n".join(results)
        for start in range(0, len(message), 1900):
            await ctx.send(message[start:start + 1900])

    @app_commands.command(name="gerar_imagem", description="Gera uma imagem com Pollinations ou Stability AI.")
    @app_commands.describe(prompt="Descrição da imagem", provedor="Motor de imagem")
    @app_commands.choices(provedor=[
        app_commands.Choice(name="Automático", value="auto"),
        app_commands.Choice(name="Pollinations", value="pollinations"),
        app_commands.Choice(name="Stability AI", value="stability"),
    ])
    @app_commands.guild_only()
    async def gerar_imagem(
        self,
        interaction: discord.Interaction,
        prompt: str,
        provedor: Optional[app_commands.Choice[str]] = None,
    ):
        gid, uid = interaction.guild_id, interaction.user.id
        user = await get_user(gid, uid)
        now = int(time.time())
        wait = IMAGE_CD - (now - int(user["last_image"] or 0))
        if wait > 0:
            return await interaction.response.send_message(f"⏳ Aguarde {wait}s.", ephemeral=True)
        await interaction.response.defer(thinking=True, ephemeral=True)
        await update_user(gid, uid, last_image=now)
        selected = provedor.value if provedor else "auto"
        try:
            data, filename, used = await self.generate_image(prompt, selected)
        except ProviderError as exc:
            return await interaction.followup.send(f"❌ Geração falhou: `{exc}`", ephemeral=True)
        file = discord.File(io.BytesIO(data), filename=filename)
        embed = emb("🎨 Criação das Sombras", f"**Prompt:** {prompt[:700]}\n**Motor:** `{used}`")
        embed.set_image(url=f"attachment://{filename}")
        await interaction.followup.send(embed=embed, file=file)

    @commands.command(name="gerar_imagem", aliases=["imagem"])
    @commands.guild_only()
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def gerar_imagem_prefix(self, ctx: commands.Context, *, prompt: str):
        user = await get_user(ctx.guild.id, ctx.author.id)
        now = int(time.time())
        wait = IMAGE_CD - (now - int(user["last_image"] or 0))
        if wait > 0:
            return await ctx.reply(f"⏳ Aguarde {wait}s.", mention_author=False)
        await update_user(ctx.guild.id, ctx.author.id, last_image=now)
        async with ctx.typing():
            try:
                data, filename, used = await self.generate_image(prompt, "auto")
            except ProviderError as exc:
                return await ctx.reply(f"❌ Geração falhou: `{exc}`", mention_author=False)
        file = discord.File(io.BytesIO(data), filename=filename)
        embed = emb("🎨 Criação das Sombras", f"**Prompt:** {prompt[:700]}\n**Motor:** `{used}`")
        embed.set_image(url=f"attachment://{filename}")
        await ctx.send(embed=embed, file=file)


async def setup(bot: commands.Bot):
    await bot.add_cog(IA(bot))
