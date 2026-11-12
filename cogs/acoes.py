"""Comandos de interação social com GIFs (abraçar, beijar, etc.).

Fontes em cascata (4 APIs):
1. nekos.best
2. nekos.life
3. otakugifs.xyz
4. kawaii.red
"""
from __future__ import annotations

from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from core import emb, log

NEKOS_BEST = "https://nekos.best/api/v2"
NEKOS_LIFE = "https://nekos.life/api/v2/img"
OTAKU_GIFS = "https://api.otakugifs.xyz/gif"
KAWAII = "https://kawaii.red/api/gif"

# comando → endpoints por API + textos
# best = nekos.best | life = nekos.life | otaku = otakugifs reaction
ACOES = {
    "abracar": {
        "best": "hug", "life": "hug", "otaku": "hug",
        "self": "{author} se abraçou... precisa de carinho?",
        "other": "{author} abraçou {target} com força!",
        "emoji": "🤗",
    },
    "beijar": {
        "best": "kiss", "life": "kiss", "otaku": "kiss",
        "self": "{author} beijou o ar... solitário(a)?",
        "other": "{author} deu um beijo em {target}!",
        "emoji": "💋",
    },
    "cafune": {
        "best": "pat", "life": "pat", "otaku": "pat",
        "self": "{author} fez cafuné em si mesmo(a).",
        "other": "{author} fez um cafuné gostoso em {target}.",
        "emoji": "✋",
    },
    "tapa": {
        "best": "slap", "life": "slap", "otaku": "slap",
        "self": "{author} se deu um tapa... acordou?",
        "other": "{author} deu um tapa em {target}!",
        "emoji": "👋",
    },
    "socar": {
        "best": "punch", "life": "slap", "otaku": "punch",
        "self": "{author} socou o ar com raiva.",
        "other": "{author} deu um soco em {target}!",
        "emoji": "👊",
    },
    "acariciar": {
        "best": "cuddle", "life": "cuddle", "otaku": "cuddle",
        "self": "{author} se aconchegou sozinho(a).",
        "other": "{author} se aconchegou com {target}.",
        "emoji": "🥰",
    },
    "morder": {
        "best": "bite", "life": "bite", "otaku": "bite",
        "self": "{author} mordeu a própria língua.",
        "other": "{author} mordeu {target}!",
        "emoji": "🦷",
    },
    "lambida": {
        "best": "lick", "life": "lick", "otaku": "lick",
        "self": "{author} lambeu os próprios lábios.",
        "other": "{author} deu uma lambida em {target}.",
        "emoji": "👅",
    },
    "dancar": {
        "best": "dance", "life": "dance", "otaku": "dance",
        "self": "{author} começou a dançar!",
        "other": "{author} puxou {target} para dançar!",
        "emoji": "💃",
    },
    "acenar": {
        "best": "wave", "life": "wave", "otaku": "wave",
        "self": "{author} acenou para todo mundo.",
        "other": "{author} acenou para {target}.",
        "emoji": "👋",
    },
    "piscar": {
        "best": "wink", "life": "wink", "otaku": "wink",
        "self": "{author} piscou misteriosamente.",
        "other": "{author} piscou para {target}.",
        "emoji": "😉",
    },
    "carinho": {
        "best": "handhold", "life": "pat", "otaku": "holdhands",
        "self": "{author} segurou a própria mão.",
        "other": "{author} segurou a mão de {target}.",
        "emoji": "🤝",
    },
    "toca_aqui": {
        "best": "highfive", "life": "highfive", "otaku": "highfive",
        "self": "{author} bateu palma sozinho(a).",
        "other": "{author} deu um toca aqui em {target}!",
        "emoji": "🙌",
    },
    "cocegas": {
        "best": "tickle", "life": "tickle", "otaku": "tickle",
        "self": "{author} se fez cócegas.",
        "other": "{author} fez cócegas em {target}!",
        "emoji": "🤭",
    },
}


class Acoes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self) -> None:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8, connect=4),
            headers={"User-Agent": "RANDOM-HELLSING/3.0.30", "Accept": "application/json"},
        )

    async def cog_unload(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _session_ok(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=8, connect=4),
                headers={"User-Agent": "RANDOM-HELLSING/3.0.30", "Accept": "application/json"},
            )
        return self._session

    async def _fetch_nekos_best(self, endpoint: str) -> Optional[str]:
        try:
            async with self._session_ok().get(f"{NEKOS_BEST}/{endpoint}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                results = data.get("results") or []
                if results and isinstance(results[0], dict):
                    url = results[0].get("url")
                    if isinstance(url, str) and url.startswith("http"):
                        return url
        except Exception as exc:
            log.debug("nekos.best/%s: %s", endpoint, type(exc).__name__)
        return None

    async def _fetch_nekos_life(self, endpoint: str) -> Optional[str]:
        try:
            async with self._session_ok().get(f"{NEKOS_LIFE}/{endpoint}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                url = data.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    return url
        except Exception as exc:
            log.debug("nekos.life/%s: %s", endpoint, type(exc).__name__)
        return None

    async def _fetch_otaku(self, reaction: str) -> Optional[str]:
        try:
            async with self._session_ok().get(
                OTAKU_GIFS, params={"reaction": reaction}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                url = data.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    return url
        except Exception as exc:
            log.debug("otakugifs/%s: %s", reaction, type(exc).__name__)
        return None


    async def _fetch_kawaii(self, reaction: str) -> Optional[str]:
        try:
            async with self._session_ok().get(
                f"{KAWAII}/{reaction}", params={"token": "anonymous"}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                url = data.get("response") or data.get("url") or data.get("gif")
                if isinstance(url, str) and url.startswith("http"):
                    return url
        except Exception as exc:
            log.debug("kawaii/%s: %s", reaction, type(exc).__name__)
        return None

    async def _fetch_gif(self, best: str, life: str, otaku: str, kawaii: str = None) -> Optional[str]:
        """Tenta 4 APIs em sequência. Primeira que responder vence."""
        kawaii_ep = kawaii or best
        # Cria cada corrotina só na hora de usar: antes as 4 eram criadas de uma vez
        # e as não aguardadas geravam "coroutine was never awaited".
        for name, factory in (
            ("nekos.best", lambda: self._fetch_nekos_best(best)),
            ("nekos.life", lambda: self._fetch_nekos_life(life)),
            ("otakugifs", lambda: self._fetch_otaku(otaku)),
            ("kawaii", lambda: self._fetch_kawaii(kawaii_ep)),
        ):
            try:
                gif = await factory()
                if gif:
                    return gif
            except Exception as exc:
                log.debug("API de GIF %s falhou: %s", name, exc)
                continue
        log.warning("Nenhuma API de GIF respondeu (best=%s)", best)
        return None

    async def _run_acao(
        self,
        interaction: discord.Interaction,
        nome: str,
        membro: Optional[discord.Member],
    ) -> None:
        cfg = ACOES[nome]
        author = interaction.user

        if membro is None or membro.id == author.id:
            texto = cfg["self"].format(author=author.mention)
        else:
            if membro.bot:
                await interaction.response.send_message(
                    "❌ Não dá pra usar isso em bots.", ephemeral=True
                )
                return
            texto = cfg["other"].format(author=author.mention, target=membro.mention)

        await interaction.response.defer()

        gif = await self._fetch_gif(cfg["best"], cfg["life"], cfg["otaku"], cfg.get("best"))
        e = emb(f"{cfg['emoji']} {nome.replace('_', ' ').title()}")
        e.description = texto
        if gif:
            e.set_image(url=gif)
        else:
            e.set_footer(text="Não consegui buscar o GIF agora (4 APIs falharam). Tente de novo.")

        await interaction.followup.send(embed=e)

    async def _run_prefix(
        self, ctx: commands.Context, nome: str, membro: Optional[discord.Member]
    ) -> None:
        cfg = ACOES[nome]
        author = ctx.author

        if membro is None or membro.id == author.id:
            texto = cfg["self"].format(author=author.mention)
        else:
            if membro.bot:
                await ctx.reply("❌ Não dá pra usar isso em bots.", mention_author=False)
                return
            texto = cfg["other"].format(author=author.mention, target=membro.mention)

        async with ctx.typing():
            gif = await self._fetch_gif(cfg["best"], cfg["life"], cfg["otaku"], cfg.get("best"))

        e = emb(f"{cfg['emoji']} {nome.replace('_', ' ').title()}")
        e.description = texto
        if gif:
            e.set_image(url=gif)
        else:
            e.set_footer(text="Não consegui buscar o GIF agora (4 APIs falharam). Tente de novo.")
        await ctx.send(embed=e)

    # ---------- Slash ----------

    @app_commands.command(name="abracar", description="Abraça alguém (ou a si mesmo).")
    @app_commands.describe(membro="Quem você quer abraçar")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def abracar(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "abracar", membro)

    @app_commands.command(name="beijar", description="Beija alguém (ou o ar).")
    @app_commands.describe(membro="Quem você quer beijar")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def beijar(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "beijar", membro)

    @app_commands.command(name="cafune", description="Faz cafuné em alguém.")
    @app_commands.describe(membro="Quem recebe o cafuné")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def cafune(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "cafune", membro)

    @app_commands.command(name="tapa", description="Dá um tapa em alguém.")
    @app_commands.describe(membro="Quem leva o tapa")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def tapa(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "tapa", membro)

    @app_commands.command(name="socar", description="Dá um soco em alguém.")
    @app_commands.describe(membro="Quem leva o soco")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def socar(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "socar", membro)

    @app_commands.command(name="acariciar", description="Se aconchega com alguém.")
    @app_commands.describe(membro="Com quem se aconchegar")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def acariciar(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "acariciar", membro)

    @app_commands.command(name="morder", description="Morde alguém.")
    @app_commands.describe(membro="Quem é mordido")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def morder(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "morder", membro)

    @app_commands.command(name="lambida", description="Dá uma lambida em alguém.")
    @app_commands.describe(membro="Quem recebe a lambida")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def lambida(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "lambida", membro)

    @app_commands.command(name="dancar", description="Dança sozinho ou com alguém.")
    @app_commands.describe(membro="Parceiro(a) de dança (opcional)")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def dancar(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "dancar", membro)

    @app_commands.command(name="acenar", description="Acena para alguém.")
    @app_commands.describe(membro="Para quem acenar")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def acenar(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "acenar", membro)

    @app_commands.command(name="piscar", description="Pisca para alguém.")
    @app_commands.describe(membro="Para quem piscar")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def piscar(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "piscar", membro)

    @app_commands.command(name="carinho", description="Segura a mão de alguém.")
    @app_commands.describe(membro="Com quem segurar a mão")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def carinho(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "carinho", membro)

    @app_commands.command(name="toca_aqui", description="Dá um toca aqui / high five.")
    @app_commands.describe(membro="Com quem bater a mão")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def toca_aqui(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "toca_aqui", membro)

    @app_commands.command(name="cocegas", description="Faz cócegas em alguém.")
    @app_commands.describe(membro="Quem recebe as cócegas")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def cocegas(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        await self._run_acao(interaction, "cocegas", membro)

    # ---------- Prefix ----------

    @commands.command(name="abracar", aliases=["hug", "abraço", "abraco"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def abracar_p(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        await self._run_prefix(ctx, "abracar", membro)

    @commands.command(name="beijar", aliases=["kiss", "beijo"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def beijar_p(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        await self._run_prefix(ctx, "beijar", membro)

    @commands.command(name="cafune", aliases=["pat", "cafuné"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def cafune_p(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        await self._run_prefix(ctx, "cafune", membro)

    @commands.command(name="tapa", aliases=["slap"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def tapa_p(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        await self._run_prefix(ctx, "tapa", membro)

    @commands.command(name="socar", aliases=["punch"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def socar_p(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        await self._run_prefix(ctx, "socar", membro)

    @commands.command(name="acariciar", aliases=["cuddle"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def acariciar_p(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        await self._run_prefix(ctx, "acariciar", membro)

    @commands.command(name="morder", aliases=["bite"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def morder_p(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        await self._run_prefix(ctx, "morder", membro)

    @commands.command(name="dancar", aliases=["dance"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def dancar_p(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        await self._run_prefix(ctx, "dancar", membro)


async def setup(bot: commands.Bot):
    await bot.add_cog(Acoes(bot))
