"""Downloader (/baixar) — yt-dlp via API Python, com allowlist de domínios, limite de tamanho e erros claros.

Plataformas públicas: Instagram e TikTok (multimídia); X/Twitter (vídeos).
Variáveis de ambiente (todas opcionais):
  YTDLP_COOKIES_INSTAGRAM caminho cookies Instagram
  MAX_UPLOAD_MB           teto base de upload (padrão 10)
  MAX_DURATION_SEC        duração máxima (padrão 600)
"""
import asyncio
import importlib.util
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse
import socket

import discord
from discord import app_commands
from discord.ext import commands

from core import emb, log

try:
    import yt_dlp
except ImportError:  # o cog carrega mesmo sem yt-dlp; os comandos avisam
    yt_dlp = None

try:
    import curl_cffi  # noqa: F401 — habilita impersonação HTTP no yt-dlp
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget
    HAS_IMPERSONATE = True
except (ImportError, AttributeError):
    ImpersonateTarget = None
    HAS_IMPERSONATE = False

def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Lê inteiros do ambiente sem derrubar o carregamento do Cog."""
    try:
        value = int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        log.warning("%s inválida; usando padrão %s.", name, default)
        return default
    return max(minimum, min(value, maximum))


BASE_UPLOAD_MB = _env_int("MAX_UPLOAD_MB", 10, 1, 500)
MAX_DURATION = _env_int("MAX_DURATION_SEC", 600, 30, 86400)
USER_COOLDOWN = 20          # segundos entre downloads por usuário
MAX_PARALLEL = 2            # downloads simultâneos (protege CPU/RAM de host gratuito)
DOWNLOAD_TIMEOUT = 240      # segundos por tentativa
MAX_ITEMS = 4               # máximo de itens de mídia por publicação/carrossel
GALLERY_TIMEOUT = 150       # segundos para buscar fotos/carrosséis
HEIGHT_LADDER = (720, 480, 360)
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    domains: Tuple[str, ...]
    cookies_env: Optional[str] = None


PLATFORMS = {
    "instagram": Platform("instagram", "Instagram", ("instagram.com", "instagr.am"), "YTDLP_COOKIES_INSTAGRAM"),
    "tiktok": Platform("tiktok", "TikTok", ("tiktok.com", "vt.tiktok.com"), "YTDLP_COOKIES_TIKTOK"),
    "twitter": Platform("twitter", "X/Twitter", ("twitter.com", "x.com"), "YTDLP_COOKIES_TWITTER"),
    "pinterest": Platform("pinterest", "Pinterest", ("pinterest.com", "pin.it", "www.pinterest.com"), "YTDLP_COOKIES_PINTEREST"),
}


class DownloadFailed(Exception):
    """Falha esperada, com mensagem já pronta para o usuário."""


class Cancelled(Exception):
    pass


@dataclass
class Result:
    files: List[Path] = field(default_factory=list)
    title: str = "Vídeo"
    uploader: str = ""
    duration: int = 0
    height_used: int = 0


# -----------------------------------------------------------------------------
# Funções puras (testáveis sem Discord)
# -----------------------------------------------------------------------------
def _ip_is_blocked(ip: object) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_public_host(host: str) -> None:
    """Resolve DNS e rejeita qualquer A/AAAA privado (mitiga DNS rebinding basico).

    Nao e a prova absoluta contra rebinding apos a resolucao (yt-dlp resolve de novo),
    mas barra hosts que ja resolvem para rede interna no momento da validacao.
    """
    host = host.strip("[]")
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DownloadFailed("Nao foi possivel resolver o dominio do link.") from exc
    if not infos:
        raise DownloadFailed("Dominio sem registros DNS validos.")
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            raise DownloadFailed("Links que resolvem para rede interna nao sao permitidos.")


async def validate_url_async(raw: str, platform: Platform) -> str:
    """Aceita HTTPS, allowlist de dominio e IP publico (sem rede interna)."""
    raw = raw.strip().strip("<>")
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DownloadFailed("Envie um link `https://` valido.")
    if parsed.username or parsed.password:
        raise DownloadFailed("URL com credenciais embutidas nao e permitida.")
    host = parsed.hostname.lower()
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.endswith(".local"):
        raise DownloadFailed("Links locais nao sao permitidos.")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        if _ip_is_blocked(ip):
            raise DownloadFailed("Links de rede interna nao sao permitidos.")
    else:
        # socket.getaddrinfo é síncrono; não pode bloquear o event loop do bot.
        await asyncio.to_thread(_resolve_public_host, host)
    if platform.domains:
        if not any(host == d or host.endswith("." + d) for d in platform.domains):
            raise DownloadFailed(
                f"Esse link nao e do {platform.name}. Dominios aceitos: {', '.join(platform.domains)}."
            )
    return raw


def upload_limit_bytes(premium_tier: int) -> int:
    """Teto de upload do servidor. Nível 1 não aumenta; 2 = 50 MB; 3 = 100 MB. 5% de margem."""
    mb = max(BASE_UPLOAD_MB, {2: 50, 3: 100}.get(premium_tier, 0))
    return int(mb * 1024 * 1024 * 0.95)


def format_for(height: int, has_ffmpeg: bool) -> str:
    if has_ffmpeg:
        return (
            f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/b[height<={height}][ext=mp4]/"
            f"bv*[height<={height}]+ba/b[height<={height}]/b/best"
        )
    return f"b[height<={height}][ext=mp4]/b[height<={height}]/b/best"


def explain_error(message: str, platform: Platform) -> str:
    m = message.lower()
    # Posts compostos apenas por fotos/slideshows podem não expor uma faixa de vídeo.
    photo_only_signatures = (
        "no video formats found",
        "nenhum formato de vídeo encontrado",
        "no video in this post",
        "there is no video in this post",
        "no video could be found",
    )
    if platform.key in {"instagram", "tiktok"} and any(term in m for term in photo_only_signatures):
        return (
            "Esta publicação não disponibilizou uma faixa de vídeo. O bot também tenta buscar fotos "
            "com gallery-dl; se nenhuma mídia foi encontrada, verifique `/baixar status`, o acesso "
            "à publicação e, se necessário, os cookies configurados."
        )
    if any(term in m for term in ("there is no video in this post", "no video in this post", "no video could be found")):
        return "Não há faixa de vídeo disponível. Tente o modo Somente fotos, se a publicação tiver imagens."
    if "sign in to confirm your age" in m or "age-restricted" in m or "inappropriate for some users" in m:
        return "Conteúdo com restrição de idade não é suportado neste comando público."
    if "in your country" in m or ("geo" in m and "restrict" in m):
        return "Vídeo bloqueado na região do servidor."
    if "requested format is not available" in m:
        return "Nenhum formato de vídeo compatível foi disponibilizado. O link pode não conter vídeo ou a plataforma pode estar temporariamente incompatível."
    if platform.key == "pinterest" and any(s in m for s in (
        "login required", "authentication", "cookies", "not authorized", "403", "forbidden",
        "rate limit", "rate-limit", "blocked", "captcha", "consent",
    )):
        return (
            "O Pinterest bloqueou ou não autorizou a extração desta publicação. Confira se o pin é público "
            "e, se sua sessão tiver acesso legítimo a ele, configure `YTDLP_COOKIES_PINTEREST` com um "
            "cookies.txt válido no formato Netscape. Atualize yt-dlp e gallery-dl e tente novamente."
        )
    if platform.key == "instagram" and any(s in m for s in (
        "login required", "rate-limit", "not available", "empty media response", "locked behind the login", "cookies",
    )):
        return ("O Instagram não liberou o conteúdo para esta sessão. Verifique se o post está disponível "
                "para a conta usada e se `YTDLP_COOKIES_INSTAGRAM` aponta para um cookies.txt válido. "
                "Veja `/baixar ajuda`.")
    if "no video" in m or "there is no video" in m:
        return "Não há faixa de vídeo disponível. Tente o modo Somente fotos, se a publicação tiver imagens."
    if "private video" in m or "this video is private" in m or ("private" in m and "account" in m):
        return "Conteúdo privado."
    if "video unavailable" in m or "has been removed" in m or "does not exist" in m or "been deleted" in m:
        return "Vídeo indisponível ou removido."
    if "ffmpeg" in m:
        return "Falta o `ffmpeg` no servidor para juntar vídeo e áudio."
    if "unsupported url" in m:
        return "Link não suportado."
    if platform.key == "pinterest" and any(term in m for term in (
        "no extractor", "no images", "no media", "empty", "not found", "404",
    )):
        return "Não encontrei imagens acessíveis nesse pin. O link pode estar removido, privado, ser um board não suportado ou ter mudado de formato."
    if "unable to download" in m or "timed out" in m or "connection" in m:
        return "Falha de rede ao acessar a plataforma. Tente de novo em instantes."
    return "Não consegui baixar este link."


def _clean_err(exc: Exception) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
    return text.replace("ERROR: ", "").strip()


def _collect_files(tmp: Path) -> List[Path]:
    return sorted(
        (p for p in tmp.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS and p.stat().st_size > 0),
        key=lambda p: p.name,
    )


def _collect_images(tmp: Path) -> List[Path]:
    """Reúne imagens baixadas pelo gallery-dl, inclusive em subpastas."""
    return sorted(
        (p for p in tmp.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS and p.stat().st_size > 0),
        key=lambda p: (p.parent.as_posix(), p.name),
    )


def _gallery_dl_command() -> Optional[List[str]]:
    """Localiza gallery-dl instalado globalmente ou no prefixo privado da hospedagem."""
    executable = shutil.which("gallery-dl")
    if executable:
        return [executable]
    # Prioriza o módulo no mesmo interpretador do bot. Em hospedagens que usam
    # pip --prefix .local, main.py já acrescentou site-packages ao sys.path.
    if importlib.util.find_spec("gallery_dl") is not None:
        return [sys.executable, "-m", "gallery_dl"]
    local_executable = Path.cwd() / ".local" / "bin" / ("gallery-dl.exe" if os.name == "nt" else "gallery-dl")
    if local_executable.is_file():
        return [str(local_executable)]
    return None


def _gallery_dl_env() -> dict:
    """Propaga o sys.path do bot para o subprocesso do gallery-dl.

    O pip --prefix .local não registra esse caminho no Python global. Sem
    PYTHONPATH, o executável filho pode existir, mas falhar ao importar
    gallery_dl e suas dependências.
    """
    env = os.environ.copy()
    paths = [entry for entry in sys.path if entry and Path(entry).is_dir()]
    existing = env.get("PYTHONPATH", "")
    if existing:
        paths.extend(part for part in existing.split(os.pathsep) if part)
    # Mantém a ordem e remove duplicatas sem alterar os paths originais.
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    return env


def _download_platform_images(
    url: str,
    platform: Platform,
    destination: Path,
    limit: int,
    cancel: threading.Event,
) -> List[Path]:
    """Baixa fotos/slideshows de Instagram e TikTok; yt-dlp cuida dos vídeos."""
    command = _gallery_dl_command()
    if not command:
        raise DownloadFailed(
            "O suporte a fotos precisa do `gallery-dl`. Instale as dependências atualizadas "
            "pelo painel da hospedagem e tente novamente."
        )

    destination.mkdir(parents=True, exist_ok=True)
    cookie_path = os.getenv(platform.cookies_env, "").strip() if platform.cookies_env else ""
    config_path = destination / ".gallery-dl-config.json"
    # Evita duplicar vídeos: yt-dlp trata vídeos; gallery-dl trata imagens.
    # gallery-dl fica responsável apenas por imagens. Vídeos continuam no yt-dlp.
    extractor_options = {"videos": False}
    if platform.key == "tiktok":
        extractor_options["photos"] = True
    elif platform.key == "twitter":
        extractor_options["cards"] = False
        extractor_options["replies"] = False
        extractor_options["retweets"] = False
    config_path.write_text(
        json.dumps({"extractor": {platform.key: extractor_options}}, ensure_ascii=False),
        encoding="utf-8",
    )
    args = command + [
        "--config-ignore",
        "--config-json", str(config_path),
        "--no-input",
        "--no-colors",
        "--quiet",
        "--directory", str(destination),
        "--range", f"1-{MAX_ITEMS}",
        "--filesize-max", f"{max(1, limit / (1024 * 1024)):.1f}M",
        "--http-timeout", "20",
        "--retries", "2",
    ]
    if cookie_path:
        cookie_file = Path(cookie_path).expanduser()
        if cookie_file.is_file():
            args.extend(["--cookies", str(cookie_file)])
        else:
            log.warning("Cookie configurado em %s não existe; gallery-dl seguirá sem cookies.", platform.cookies_env)
    args.append(url)

    try:
        if cancel.is_set():
            raise Cancelled("Download interrompido.")
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=GALLERY_TIMEOUT,
            check=False,
            env=_gallery_dl_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise DownloadFailed(f"A busca das fotos do {platform.name} excedeu o tempo limite.") from exc
    except OSError as exc:
        raise DownloadFailed("Não consegui iniciar o componente de download de fotos (gallery-dl).") from exc
    finally:
        config_path.unlink(missing_ok=True)

    images = _collect_images(destination)
    valid_images = []
    for image in images:
        if cancel.is_set():
            raise Cancelled("Download interrompido.")
        try:
            size = image.stat().st_size
        except OSError:
            continue
        if size <= limit:
            valid_images.append(image)
        else:
            image.unlink(missing_ok=True)

    if proc.returncode != 0 and not valid_images:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise DownloadFailed(explain_error(detail, platform))
    return valid_images[:MAX_ITEMS]


# -----------------------------------------------------------------------------
# Download (roda em thread; não bloqueia o event loop)
# -----------------------------------------------------------------------------
def _base_opts(platform: Platform, tmp: Path, limit: int, cancel: threading.Event) -> dict:
    def hook(_d):
        if cancel.is_set():
            raise Cancelled()

    opts = {
        "outtmpl": str(tmp / "%(id)s_%(autonumber)s.%(ext)s"),
        "noplaylist": platform.key not in ("instagram",),  # Instagram: carrossel como playlist
        "playlist_items": f"1-{MAX_ITEMS}",
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 15,
        "retries": 2,
        # max_filesize NÃO entra aqui: estimativas do TikTok/Twitter abortavam
        # a inspeção de metadados. O teto é validado no arquivo baixado.
        "merge_output_format": "mp4",
        "fragment_retries": 5,
        "extractor_retries": 2,
        "file_access_retries": 2,
        "concurrent_fragment_downloads": 2,
        "restrictfilenames": True,
        # Reduz superficie de abuso: sem playlists longas, sem geo-bypass generico.
        "geo_bypass": False,
        "progress_hooks": [hook],
    }
    cookie_path = os.getenv(platform.cookies_env, "") if platform.cookies_env else ""
    if cookie_path and Path(cookie_path).is_file():
        opts["cookiefile"] = cookie_path
    # Na API Python, impersonate exige ImpersonateTarget, não uma string.
    if HAS_CURL_CFFI and HAS_IMPERSONATE and ImpersonateTarget is not None:
        try:
            opts["impersonate"] = ImpersonateTarget.from_str("chrome")
        except (ValueError, TypeError, AssertionError) as exc:
            log.warning("Não foi possível configurar ImpersonateTarget; seguindo sem impersonação: %r", exc)
    return opts


def _download_blocking(
    url: str,
    platform: Platform,
    limit: int,
    cancel: threading.Event,
    media_mode: str = "auto",
) -> Result:
    if media_mode not in {"auto", "photos", "videos"}:
        raise DownloadFailed("Modo de mídia inválido. Escolha automático, fotos ou vídeos.")
    if yt_dlp is None and media_mode != "photos":
        raise DownloadFailed("yt-dlp não está instalado neste servidor (`pip install -U yt-dlp yt-dlp-ejs`).")
    has_ffmpeg = shutil.which("ffmpeg") is not None
    tmp = Path(tempfile.mkdtemp(prefix="hellsing_dl_"))
    try:
        result = Result(title=f"Publicação do {platform.name}" if platform.key in ("instagram", "tiktok") else "Vídeo")
        video_files: List[Path] = []
        video_problem = ""
        info = None

        if media_mode != "photos" and yt_dlp is not None:
            # 1) Tenta identificar os vídeos. Em posts de foto do Instagram o yt-dlp
            # pode retornar 'No video formats found'; nesse caso seguimos para gallery-dl.
            try:
                with yt_dlp.YoutubeDL({**_base_opts(platform, tmp, limit, cancel), "skip_download": True}) as ydl:
                    info = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as exc:
                video_problem = _clean_err(exc)
                # Publicações em formato de fotos/slideshow podem não expor
                # uma faixa de vídeo. Tenta o extrator de imagens em todas as
                # plataformas com suporte multimídia antes de encerrar.
                photo_fallback = platform.key in {"instagram", "tiktok", "pinterest"}
                if not photo_fallback:
                    raise DownloadFailed(explain_error(video_problem, platform)) from exc

            if info:
                entries = [e for e in (info.get("entries") or []) if e] or [info]
                durations = []
                for entry in entries:
                    try:
                        value = int(entry.get("duration") or 0)
                    except (TypeError, ValueError):
                        value = 0
                    if value > 0:
                        durations.append(value)
                duration = max(durations, default=0)
                if any(value > MAX_DURATION for value in durations):
                    raise DownloadFailed(
                        f"Um dos vídeos do post excede `{MAX_DURATION // 60}min`, que é o limite permitido."
                    )
                result.title = str(info.get("title") or entries[0].get("title") or result.title)[:200]
                result.uploader = str(info.get("uploader") or entries[0].get("uploader") or "")
                result.duration = duration

                # 2) Mantém a escada de qualidade original para os arquivos de vídeo.
                for height in HEIGHT_LADDER:
                    for old in list(tmp.iterdir()):
                        if old.is_dir():
                            shutil.rmtree(old, ignore_errors=True)
                        else:
                            old.unlink(missing_ok=True)
                    opts = {**_base_opts(platform, tmp, limit, cancel), "format": format_for(height, has_ffmpeg)}
                    try:
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            ydl.extract_info(url, download=True)
                    except yt_dlp.utils.DownloadError as exc:
                        msg = _clean_err(exc) or repr(exc)
                        lowered = msg.lower()
                        partial_files = _collect_files(tmp)
                        photo_fallback = platform.key in {"instagram", "tiktok", "pinterest"} and not partial_files
                        if photo_fallback:
                            video_problem = msg
                            video_files = [f for f in partial_files if f.stat().st_size <= limit]
                            break
                        retryable = (
                            "requested format is not available" in lowered
                            or "file is larger than max-filesize" in lowered
                            or "filesize exceeds" in lowered
                        )
                        if retryable and height != HEIGHT_LADDER[-1]:
                            continue
                        if platform.key in {"instagram", "tiktok", "pinterest"} and not partial_files:
                            # Pode ser uma publicação composta somente por fotos;
                            # deixa o gallery-dl tentar antes de retornar erro.
                            video_problem = msg
                            break
                        raise DownloadFailed(explain_error(msg, platform)) from exc

                    files = _collect_files(tmp)
                    if files and all(f.stat().st_size <= limit for f in files):
                        video_files = files
                        result.height_used = height
                        break
                    if height == HEIGHT_LADDER[-1] and files:
                        video_problem = (
                            f"Vídeo acima do limite de {limit // (1024 * 1024)} MB mesmo em {height}p."
                        )

        # 3) Busca fotos/carrosséis separadamente nas três plataformas.
        # yt-dlp trata vídeos; gallery-dl trata imagens e slideshows.
        image_files: List[Path] = []
        if platform.key in {"instagram", "tiktok", "pinterest"} and media_mode != "videos":
            photo_dir = tmp / f"{platform.key}_photos"
            try:
                image_files = _download_platform_images(url, platform, photo_dir, limit, cancel)
            except DownloadFailed as exc:
                if not video_files:
                    raise
                log.warning("Fotos do %s não foram obtidas: %s", platform.name, str(exc)[:400])

        # O limite é global para a publicação: não permita 4 vídeos + 4 fotos
        # quando o extrator de vídeo e o de imagens retornarem o mesmo carrossel.
        media_files = (video_files + image_files)[:MAX_ITEMS]
        if not media_files:
            if platform.key == "pinterest":
                raise DownloadFailed(
                    "Não encontrei imagens acessíveis nesse pin. Ele pode exigir uma sessão válida, "
                    "estar privado/removido ou ter sido bloqueado pela plataforma. Confira `/baixar status` "
                    "e a variável `YTDLP_COOKIES_PINTEREST`."
                )
            if platform.key in {"instagram", "tiktok"} and video_problem:
                raise DownloadFailed(
                    f"Não encontrei vídeo compatível nem fotos disponíveis nessa publicação do {platform.name}. "
                    "Ela pode estar indisponível, exigir uma sessão válida ou não permitir extração."
                )
            if video_problem:
                raise DownloadFailed(video_problem)
            raise DownloadFailed("Não encontrei mídia disponível nesse link.")

        # Move os arquivos válidos para uma pasta de saída que sobrevive à limpeza temporária.
        keep = Path(tempfile.mkdtemp(prefix="hellsing_out_"))
        for index, source in enumerate(media_files, start=1):
            if not source.exists() or source.stat().st_size <= 0 or source.stat().st_size > limit:
                continue
            target = keep / f"{index:02d}_{source.name}"
            result.files.append(Path(shutil.move(str(source), str(target))))
        if not result.files:
            raise DownloadFailed(
                f"Os arquivos encontrados ultrapassam o limite de upload de {limit // (1024 * 1024)} MB por arquivo."
            )
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -----------------------------------------------------------------------------
# Cog
# -----------------------------------------------------------------------------
HELP_TEXT = (
    "**Comandos:** `/baixar instagram`, `/baixar tiktok`, `/baixar twitter`, `/baixar pinterest`\n\n"
    "**TikTok:** escolha `Automático`, `Somente fotos/slideshow` ou `Somente vídeos`. "
    "No modo automático, o yt-dlp tenta vídeos e o gallery-dl tenta fotos/slideshows quando disponíveis. "
    "São processados até {items} itens por publicação.\n\n"
    "**Instagram:** mantém o suporte multimídia existente: `Automático`, `Somente fotos` ou `Somente vídeos`.\n\n"
    "**Pinterest:** baixa imagens de pins públicos com `gallery-dl`; pins que exigem sessão podem precisar de cookies válidos.\n\n"
    "**X/Twitter:** continua somente com download de vídeos.\n\n"
    "**Limites:** vídeos de até {dur} min; cada arquivo precisa caber no upload do servidor "
    "(base {base} MB; 50 MB no boost nível 2; 100 MB no nível 3). Para vídeo, o bot reduz a qualidade "
    "(720p → 480p → 360p) até caber.\n\n"
    "**Cookies:** se uma plataforma exigir sessão, configure a variável correspondente "
    "(`YTDLP_COOKIES_INSTAGRAM`, `YTDLP_COOKIES_TIKTOK`, `YTDLP_COOKIES_TWITTER` ou `YTDLP_COOKIES_PINTEREST`) com o caminho para um `cookies.txt` "
    "no formato Netscape. Mantenha-o privado e nunca o publique no GitHub. O bot não contorna bloqueios nem acessa conteúdo "
    "que sua sessão não esteja autorizada a visualizar.\n\n"
    "**Servidor:** instale as dependências de `requirements.txt`; `ffmpeg` e `curl-cffi` melhoram "
    "a compatibilidade de vídeo. Links privados sem autorização, removidos ou bloqueados pela plataforma não funcionam."
)


class Video(commands.Cog):
    baixar = app_commands.Group(name="baixar", description="Baixa vídeos e fotos de redes sociais.", guild_only=True)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._sem = asyncio.Semaphore(MAX_PARALLEL)
        self._last: dict[int, float] = {}
        self._last_prune = time.monotonic()
        if shutil.which("ffmpeg") is None:
            log.warning("ffmpeg não encontrado: só serão baixados formatos com áudio embutido.")
        log.info(
            "Downloader: yt-dlp=%s | ffmpeg=%s | curl-cffi=%s | impersonate_target=%s",
            getattr(getattr(yt_dlp, "version", None), "__version__", "desconhecida") if yt_dlp else "ausente",
            bool(shutil.which("ffmpeg")), HAS_CURL_CFFI, HAS_IMPERSONATE,
        )

    async def _run(
        self,
        interaction: discord.Interaction,
        platform: Platform,
        url: str,
        media_mode: str = "auto",
    ):
        try:
            url = await validate_url_async(url, platform)
        except DownloadFailed as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        now = time.monotonic()
        if now - self._last_prune >= 300:
            cutoff = now - max(USER_COOLDOWN * 3, 300)
            self._last = {uid: ts for uid, ts in self._last.items() if ts >= cutoff}
            self._last_prune = now
        if len(self._last) > 5000:
            # Limita memória mesmo em comunidades com muita rotatividade.
            oldest = sorted(self._last.items(), key=lambda item: item[1])[:1000]
            for uid, _ in oldest:
                self._last.pop(uid, None)
        wait = USER_COOLDOWN - (now - self._last.get(interaction.user.id, 0))
        if wait > 0:
            return await interaction.response.send_message(f"⏳ Aguarde {int(wait) + 1}s para baixar de novo.", ephemeral=True)
        self._last[interaction.user.id] = now

        await interaction.response.defer(thinking=True)
        # Respeita restrições de acesso impostas pela plataforma.
        # Limite de tamanho do Discord continua valendo.
        # discord.py 2.6+ informa o limite efetivo da interação; o limite local
        # configurado nunca pode ultrapassar o valor aceito pelo Discord.
        configured_limit = upload_limit_bytes(interaction.guild.premium_tier)
        discord_limit = getattr(interaction, "filesize_limit", None)
        limit = min(configured_limit, int(discord_limit)) if isinstance(discord_limit, int) and discord_limit > 0 else configured_limit
        cancel = threading.Event()
        result: Optional[Result] = None
        async def run_download():
            async with self._sem:
                downloaded = await asyncio.to_thread(_download_blocking, url, platform, limit, cancel, media_mode)
                # Se o usuário já recebeu timeout, não deixe arquivos órfãos.
                if cancel.is_set():
                    for path in downloaded.files:
                        shutil.rmtree(path.parent, ignore_errors=True)
                    raise Cancelled("Download interrompido após timeout.")
                return downloaded

        worker = asyncio.create_task(run_download(), name=f"download-{platform.key}")
        try:
            done, _ = await asyncio.wait({worker}, timeout=DOWNLOAD_TIMEOUT)
            if not done:
                cancel.set()
                # Não é possível matar uma thread Python com segurança. O evento
                # interrompe nos hooks; socket_timeout/retries limitam bloqueios
                # de rede. Mantemos a tarefa viva para preservar o semáforo.
                done, _ = await asyncio.wait({worker}, timeout=30)
                if not done:
                    worker.add_done_callback(self._consume_worker_result)
                    await interaction.followup.send(
                        embed=emb("⌛ Tempo esgotado", "O download excedeu o tempo limite. A operação foi sinalizada para cancelamento.")
                    )
                    return
                # Consome o resultado/erro após o cancelamento cooperativo.
                try:
                    worker.result()
                except Exception:
                    pass
                await interaction.followup.send(
                    embed=emb("⌛ Tempo esgotado", "O download excedeu o tempo limite e foi interrompido.")
                )
                return
            result = worker.result()
            await self._send(interaction, platform, result, limit)
        except DownloadFailed as e:
            await interaction.followup.send(embed=emb("❌ Download não concluído", str(e)))
        except Cancelled:
            await interaction.followup.send(embed=emb("⌛ Tempo esgotado", "O download foi interrompido."))
        except Exception as exc:  # erros do yt-dlp e inesperados
            cancel.set()
            raw = _clean_err(exc)
            # Algumas exceções (ex.: CancelledError/erros de transporte) têm
            # str(exc) vazio. Registra tipo + repr + traceback para diagnóstico.
            detail = raw or repr(exc) or "<exceção sem mensagem>"
            log.warning(
                "Falha em /baixar %s (%s) [%s]: %s",
                platform.key,
                url,
                type(exc).__name__,
                detail[:1000],
            )
            log.debug("Traceback completo de /baixar %s:\\n%s", platform.key, traceback.format_exc())
            user_error = raw or type(exc).__name__
            await interaction.followup.send(embed=emb("❌ Falha no download", explain_error(user_error, platform)))
        finally:
            if result:
                for f in result.files:
                    await asyncio.to_thread(shutil.rmtree, f.parent, True)

    @staticmethod
    def _consume_worker_result(task: asyncio.Task):
        """Consome exceção de tarefa que terminou após a resposta de timeout."""
        try:
            result = task.result()
            if result:
                for path in result.files:
                    asyncio.create_task(asyncio.to_thread(shutil.rmtree, path.parent, True))
        except Exception as exc:
            log.debug("Worker de download terminou após timeout: %r", exc)

    async def _send(self, interaction: discord.Interaction, platform: Platform, result: Result, limit: int):
        total = sum(f.stat().st_size for f in result.files)
        desc = f"**{result.title}**"
        if result.uploader:
            desc += f"\n👤 {result.uploader}"
        if result.duration:
            desc += f"\n⏱️ {result.duration // 60}:{result.duration % 60:02d}"
        image_count = sum(f.suffix.lower() in IMAGE_EXTS for f in result.files)
        video_count = sum(f.suffix.lower() in VIDEO_EXTS for f in result.files)
        media_parts = []
        if image_count:
            media_parts.append(f"🖼️ {image_count} foto(s)")
        if video_count:
            media_parts.append(f"🎬 {video_count} vídeo(s)")
        media_summary = " • ".join(media_parts) or f"{len(result.files)} arquivo(s)"
        desc += f"\n{media_summary} • 📦 {total / (1024 * 1024):.1f} MB"
        if result.height_used:
            desc += f" • {result.height_used}p máx."
        e = emb(f"📥 {platform.name}", desc)
        try:
            if total <= limit:
                await interaction.followup.send(embed=e, files=[discord.File(f) for f in result.files])
            else:  # vários itens que juntos passam do limite: envia um por mensagem
                await interaction.followup.send(embed=e)
                for f in result.files:
                    await interaction.followup.send(file=discord.File(f))
        except discord.HTTPException as exc:
            log.warning("Envio do /baixar falhou: %s", exc)
            await interaction.followup.send(
                embed=emb("❌ Envio falhou", "O Discord recusou o arquivo (provável limite de upload). "
                                           "Defina `MAX_UPLOAD_MB` menor ou use um servidor com boost.")
            )

    @baixar.command(name="instagram", description="Baixa vídeos, fotos e carrosséis do Instagram.")
    @app_commands.describe(
        link="Link do reel, publicação, carrossel ou story",
        modo="Escolha automático, somente fotos ou somente vídeos",
    )
    @app_commands.choices(modo=[
        app_commands.Choice(name="Automático (fotos + vídeos)", value="auto"),
        app_commands.Choice(name="Somente fotos", value="photos"),
        app_commands.Choice(name="Somente vídeos", value="videos"),
    ])
    async def ig(
        self,
        interaction: discord.Interaction,
        link: str,
        modo: app_commands.Choice[str] = None,
    ):
        media_mode = modo.value if modo else "auto"
        await self._run(interaction, PLATFORMS["instagram"], link, media_mode)

    @baixar.command(name="tiktok", description="Baixa fotos, slideshows e vídeos do TikTok.")
    @app_commands.describe(link="Link do post", modo="Escolha automático, somente fotos ou somente vídeos")
    @app_commands.choices(modo=[
        app_commands.Choice(name="Automático (fotos + vídeos)", value="auto"),
        app_commands.Choice(name="Somente fotos/slideshow", value="photos"),
        app_commands.Choice(name="Somente vídeos", value="videos"),
    ])
    async def tt(self, interaction: discord.Interaction, link: str, modo: app_commands.Choice[str] = None):
        await self._run(interaction, PLATFORMS["tiktok"], link, modo.value if modo else "auto")

    @baixar.command(name="twitter", description="Baixa vídeos públicos do X/Twitter.")
    @app_commands.describe(link="Link do vídeo")
    async def tw(self, interaction: discord.Interaction, link: str):
        await self._run(interaction, PLATFORMS["twitter"], link, "videos")


    @baixar.command(name="pinterest", description="Baixa imagens de um pin/board do Pinterest.")
    @app_commands.describe(link="URL do pin ou board (pinterest.com ou pin.it)")
    async def baixar_pinterest(self, interaction: discord.Interaction, link: str):
        await self._run(interaction, PLATFORMS["pinterest"], link, "photos")

    @baixar.command(name="status", description="Verifica dependências do downloader.")
    async def status(self, interaction: discord.Interaction):
        version = getattr(getattr(yt_dlp, "version", None), "__version__", "não instalado") if yt_dlp else "não instalado"
        ffmpeg_ok = bool(shutil.which("ffmpeg"))

        def _cookie_ok(env: str) -> bool:
            raw = (os.getenv(env) or "").strip()
            return bool(raw) and Path(raw).is_file()

        # Acesso a disco fora do event loop.
        ig_ok, tt_ok, tw_ok, pin_ok = await asyncio.to_thread(
            lambda: (
                _cookie_ok("YTDLP_COOKIES_INSTAGRAM"),
                _cookie_ok("YTDLP_COOKIES_TIKTOK"),
                _cookie_ok("YTDLP_COOKIES_TWITTER"),
                _cookie_ok("YTDLP_COOKIES_PINTEREST"),
            )
        )
        lines = [
            f"yt-dlp: `{version}`",
            f"gallery-dl: {'✅ disponível' if (_gallery_dl_command() is not None) else '❌ ausente (necessário para fotos/slideshows)'}",
            "Plataformas: Instagram, TikTok, X/Twitter e Pinterest.",
            "Modos: Instagram/TikTok (fotos e vídeos), Pinterest (imagens), X/Twitter (vídeos).",
            f"ffmpeg: {'✅ disponível' if ffmpeg_ok else '❌ ausente'}",
            f"curl-cffi: {'✅ disponível' if HAS_CURL_CFFI else '⚠️ ausente (impersonação desativada)'}",
            f"ImpersonateTarget: {'✅ disponível' if HAS_IMPERSONATE else '⚠️ indisponível'}",
            f"Instagram cookies: {'✅ arquivo encontrado' if ig_ok else '⚠️ não configurado/encontrado'}",
            f"TikTok cookies: {'✅ arquivo encontrado' if tt_ok else 'ℹ️ opcional/não configurado'}",
            f"X/Twitter cookies: {'✅ arquivo encontrado' if tw_ok else 'ℹ️ opcional/não configurado'}",
            f"Pinterest cookies: {'✅ arquivo encontrado' if pin_ok else 'ℹ️ opcional/não configurado'}",
        ]
        await interaction.response.send_message(embed=emb("📥 Diagnóstico do downloader", "\n".join(lines)), ephemeral=True)

    @baixar.command(name="ajuda", description="Como usar, limites e como configurar cookies.")
    async def ajuda(self, interaction: discord.Interaction):
        text = HELP_TEXT.format(dur=MAX_DURATION // 60, base=BASE_UPLOAD_MB, items=MAX_ITEMS)
        await interaction.response.send_message(embed=emb("📥 /baixar — ajuda", text), ephemeral=True)


    @app_commands.command(name="pinterest", description="Baixa imagens de um link do Pinterest.")
    @app_commands.guild_only()
    @app_commands.describe(link="URL do pin (pinterest.com ou pin.it)")
    async def pinterest_cmd(self, interaction: discord.Interaction, link: str):
        await self._run(interaction, PLATFORMS["pinterest"], link, "photos")


async def setup(bot: commands.Bot):
    await bot.add_cog(Video(bot))
