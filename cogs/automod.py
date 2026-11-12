"""Automod avançado: filtro de palavras, links, caps, emojis, repetição,
flood de linhas, punição progressiva, anti-raid e idade mínima de conta (v3.1.0).

O anti-spam por volume, o anti-convite (/config antispam e /config antilink) e
o anti-menção em massa continuam em cogs/events.py.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from collections import OrderedDict, defaultdict, deque
from functools import lru_cache
from datetime import timedelta
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import RAID_JOINS, RAID_WINDOW, emb, get_feature, send_log, set_feature

log = logging.getLogger("hellsing.automod")

FEATURE = "automod"
DEFAULTS = {
    "words": [],
    "caps": False,
    "emoji": False,
    "repeat": False,
    "lines": False,
    "links": False,
    "links_allow": ["tenor.com", "giphy.com", "youtube.com", "youtu.be"],
    "exempt_roles": [],
    "exempt_channels": [],
    "strikes": 3,
    "timeout_min": 10,
    "raid_mode": "alerta",
    "raid_joins": RAID_JOINS,
    "raid_seconds": RAID_WINDOW,
    "raid_lock_min": 10,
    "min_age_days": 0,
}

FILTER_LABELS = {
    "caps": "excesso de MAIÚSCULAS",
    "emoji": "excesso de emojis",
    "repeat": "mensagem repetida",
    "lines": "flood de linhas",
    "links": "link não permitido",
    "words": "palavra proibida",
}

STRIKE_WINDOW = 600  # infrações contam por 10 minutos
REPEAT_WINDOW = 20
REPEAT_LIMIT = 3
CAPS_MIN_LETTERS = 12
CAPS_RATIO = 0.7
EMOJI_LIMIT = 10
LINES_LIMIT = 15

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})
_URL_RE = re.compile(r"(?:https?://|www\.)([^\s/<>\"']+)", re.IGNORECASE)
_CUSTOM_EMOJI_RE = re.compile(r"<a?:\w{2,32}:\d{15,25}>")
_UNICODE_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F1E6-\U0001F1FF]")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c)).translate(_LEET)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"(.)\1{2,}", r"\1", re.sub(r"\s+", " ", text)).strip()


def _merge_spelled(norm: str) -> str:
    """Junta letras soltas: "p u t a" / "p.u.t.a" -> "puta" (palavras normais ficam iguais)."""
    out, run = [], []
    for tok in norm.split():
        if len(tok) == 1:
            run.append(tok)
            continue
        if run:
            out.append("".join(run))
            run = []
        out.append(tok)
    if run:
        out.append("".join(run))
    return " ".join(out)


@lru_cache(maxsize=128)
def _compiled_word_filter(cleaned_words: tuple[str, ...]) -> re.Pattern:
    """Compila uma única expressão por conjunto de palavras (cache LRU)."""
    alternatives = sorted(set(cleaned_words), key=len, reverse=True)
    return re.compile(
        rf"(?<![a-z0-9])(?:{'|'.join(re.escape(word) for word in alternatives)})(?![a-z0-9])"
    )


def find_bad_word(content: str, words: list[str]) -> Optional[str]:
    if not words:
        return None
    norm = normalize(content)
    variants = (norm, _merge_spelled(norm))
    normalized_pairs = [(normalize(word), word) for word in words]
    cleaned_words = tuple(sorted({normalized for normalized, _ in normalized_pairs if normalized}))
    if not cleaned_words:
        return None

    pattern = _compiled_word_filter(cleaned_words)
    original_by_normalized = {}
    for normalized, original in normalized_pairs:
        if normalized:
            original_by_normalized.setdefault(normalized, original)

    for variant in variants:
        match = pattern.search(variant)
        if match:
            return original_by_normalized.get(match.group(0), match.group(0))
    return None


def domain_allowed(domain: str, allow: list[str]) -> bool:
    domain = domain.lower().split(":")[0].rstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    return any(domain == a or domain.endswith("." + a) for a in allow)


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._checks: "OrderedDict[int, asyncio.Future]" = OrderedDict()
        self._strikes: dict[tuple[int, int], deque] = defaultdict(deque)
        self._recent: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=REPEAT_LIMIT))
        self._joins: dict[int, deque] = defaultdict(lambda: deque(maxlen=200))
        self._raid_until: dict[int, float] = {}
        self._last_runtime_prune = time.monotonic()

    def _prune_runtime_state(self) -> None:
        """Remove chaves órfãs e janelas expiradas sem varrer em toda mensagem."""
        now = time.monotonic()
        if now - self._last_runtime_prune < 60:
            return
        for key, window in list(self._recent.items()):
            while window and now - window[0][0] > REPEAT_WINDOW:
                window.popleft()
            if not window:
                self._recent.pop(key, None)
        for key, window in list(self._strikes.items()):
            while window and now - window[0] > STRIKE_WINDOW:
                window.popleft()
            if not window:
                self._strikes.pop(key, None)
        for guild_id, window in list(self._joins.items()):
            while window and now - window[0] > max(RAID_WINDOW * 3, 60):
                window.popleft()
            if not window:
                self._joins.pop(guild_id, None)
        for guild_id, expires_at in list(self._raid_until.items()):
            if expires_at <= now:
                self._raid_until.pop(guild_id, None)
        # Só descarta futures concluídas; não interrompe verificações em andamento.
        for message_id, future in list(self._checks.items()):
            if future.done():
                self._checks.pop(message_id, None)
        self._last_runtime_prune = now

    grupo = app_commands.Group(
        name="automod",
        description="Moderação automática avançada",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # ---------------------------------------------------------- mensagens
    async def check_message(self, message: discord.Message) -> bool:
        """True se a mensagem foi bloqueada. Seguro para chamar mais de uma vez."""
        self._prune_runtime_state()
        fut = self._checks.get(message.id)
        if fut is None:
            fut = asyncio.ensure_future(self._check(message))
            self._checks[message.id] = fut
            while len(self._checks) > 500:
                self._checks.popitem(last=False)
        try:
            return await asyncio.shield(fut)
        except Exception:
            log.exception("Erro no automod (guild=%s, msg=%s)", getattr(message.guild, "id", None), message.id)
            return False

    def _is_exempt(self, member: discord.Member, channel, data: dict) -> bool:
        perms = member.guild_permissions
        if perms.administrator or perms.manage_messages or member.id == member.guild.owner_id:
            return True
        channel_ids = {channel.id, getattr(channel, "parent_id", None), getattr(channel, "category_id", None)}
        if channel_ids & {int(c) for c in data["exempt_channels"]}:
            return True
        return any(r.id in {int(x) for x in data["exempt_roles"]} for r in member.roles)

    def _violation(self, message: discord.Message, data: dict) -> Optional[tuple[str, str]]:
        content = message.content or ""
        word = find_bad_word(content, data["words"])
        if word:
            return "words", f"palavra filtrada: `{word}`"
        if data["links"]:
            for m in _URL_RE.finditer(content):
                if not domain_allowed(m.group(1), data["links_allow"]):
                    return "links", f"domínio `{m.group(1)[:80]}`"
        if data["caps"]:
            letters = [c for c in content if c.isalpha()]
            if len(letters) >= CAPS_MIN_LETTERS and sum(c.isupper() for c in letters) / len(letters) >= CAPS_RATIO:
                return "caps", f"{len(letters)} letras, maioria maiúscula"
        if data["emoji"]:
            count = len(_CUSTOM_EMOJI_RE.findall(content)) + len(_UNICODE_EMOJI_RE.findall(content))
            if count > EMOJI_LIMIT:
                return "emoji", f"{count} emojis"
        if data["lines"] and content.count("\n") >= LINES_LIMIT:
            return "lines", f"{content.count(chr(10)) + 1} linhas"
        if data["repeat"] and content:
            key = (message.guild.id, message.author.id)
            now = time.monotonic()
            norm = normalize(content) or content
            dq = self._recent[key]
            dq.append((now, norm))
            same = [t for t, c in dq if c == norm and now - t <= REPEAT_WINDOW]
            if len(same) >= REPEAT_LIMIT:
                dq.clear()
                return "repeat", f"{len(same)}x em {REPEAT_WINDOW}s"
        return None

    async def _check(self, message: discord.Message) -> bool:
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return False
        data = await get_feature(message.guild.id, FEATURE, DEFAULTS)
        if self._is_exempt(message.author, message.channel, data):
            return False
        hit = self._violation(message, data)
        if hit is None:
            return False
        kind, detail = hit
        await self._punish(message, data, kind, detail)
        return True

    async def _punish(self, message: discord.Message, data: dict, kind: str, detail: str) -> None:
        member, guild = message.author, message.guild
        label = FILTER_LABELS.get(kind, kind)
        deleted = True
        try:
            await message.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException as exc:
            deleted = False
            log.warning("Automod sem permissão para apagar (guild=%s, canal=%s): %s", guild.id, message.channel.id, exc)

        key = (guild.id, member.id)
        now = time.monotonic()
        dq = self._strikes[key]
        dq.append(now)
        while dq and now - dq[0] > STRIKE_WINDOW:
            dq.popleft()
        strikes, limit = len(dq), int(data["strikes"] or 0)
        punished = ""
        if limit and strikes >= limit:
            dq.clear()
            minutes = max(1, int(data["timeout_min"] or 10))
            try:
                await member.timeout(timedelta(minutes=minutes), reason=f"Automod: {limit} infrações em 10 min")
                punished = f"Timeout de {minutes} min ({limit} infrações)."
            except discord.HTTPException as exc:
                punished = f"Timeout falhou: {exc.__class__.__name__}."

        log.info(
            "Automod guild=%s user=%s (%s) canal=%s filtro=%s %s strikes=%s/%s %s",
            guild.id, member.id, member, message.channel.id, kind, detail, strikes, limit or "-", punished,
        )
        try:
            aviso = f"🚫 {member.mention}, sua mensagem foi removida ({label})."
            if punished.startswith("Timeout de"):
                aviso += f" {punished}"
            elif limit:
                aviso += f" Aviso {strikes}/{limit}."
            await message.channel.send(aviso, delete_after=8, allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.HTTPException:
            pass

        e = emb("🤖 Automod", f"**Membro:** {member.mention} (`{member.id}`)\n**Canal:** {message.channel.mention}\n**Filtro:** {label} — {detail}")
        content = (message.content or "").replace("```", "'''")
        if content:
            e.add_field(name="Conteúdo", value=content[:1000], inline=False)
        e.add_field(name="Ação", value=("Mensagem apagada. " if deleted else "Não consegui apagar. ") + (punished or ""), inline=False)
        e.timestamp = discord.utils.utcnow()
        await send_log(guild, e)

    # ------------------------------------------------------------ anti-raid
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        data = await get_feature(guild.id, FEATURE, DEFAULTS)
        now = time.monotonic()

        min_days = int(data["min_age_days"] or 0)
        if min_days and not member.bot:
            age_days = (discord.utils.utcnow() - member.created_at).total_seconds() / 86400
            if age_days < min_days:
                await self._kick(member, f"Automod: conta com menos de {min_days} dia(s)", f"Conta criada <t:{int(member.created_at.timestamp())}:R>, mínimo {min_days} dia(s).")
                return

        mode = data["raid_mode"]
        if mode == "off":
            return
        dq = self._joins[guild.id]
        dq.append(now)
        joins, window = int(data["raid_joins"]), int(data["raid_seconds"])
        recent = [t for t in dq if now - t <= window]
        raid_active = now < self._raid_until.get(guild.id, 0)
        if not raid_active and len(recent) >= joins:
            self._raid_until[guild.id] = now + int(data["raid_lock_min"]) * 60
            raid_active = True
            log.warning("Raid detectada guild=%s: %s entradas em %ss (modo=%s)", guild.id, len(recent), window, mode)
            desc = f"**{len(recent)} entradas em {window}s.**\n"
            if mode == "expulsar":
                desc += f"Novas entradas serão expulsas pelos próximos {data['raid_lock_min']} min. Encerre antes com `/automod raid_encerrar`."
            else:
                desc += "Modo alerta: nenhuma ação automática. Use `/automod antiraid modo:expulsar` para bloquear entradas."
            e = emb("🚨 Possível raid", desc)
            e.timestamp = discord.utils.utcnow()
            await send_log(guild, e)
        if raid_active and mode == "expulsar" and not member.bot:
            await self._kick(member, "Automod: proteção anti-raid ativa", "Entrou durante o bloqueio anti-raid.")

    async def _kick(self, member: discord.Member, reason: str, detail: str) -> None:
        guild = member.guild
        me = guild.me
        if me is None or not me.guild_permissions.kick_members or member.top_role >= me.top_role:
            log.warning("Automod não pode expulsar %s (guild=%s): sem permissão/hierarquia", member.id, guild.id)
            return
        try:
            await member.send(f"Você foi removido(a) de **{guild.name}** automaticamente: {reason.removeprefix('Automod: ')}. Tente novamente mais tarde.")
        except discord.HTTPException:
            pass
        try:
            await member.kick(reason=reason)
        except discord.HTTPException as exc:
            log.warning("Falha ao expulsar %s (guild=%s): %s", member.id, guild.id, exc)
            return
        log.info("Automod expulsou guild=%s user=%s (%s): %s", guild.id, member.id, member, reason)
        e = emb("🤖 Automod — expulsão", f"**Membro:** {member} (`{member.id}`)\n{detail}")
        e.timestamp = discord.utils.utcnow()
        await send_log(guild, e)

    # ------------------------------------------------------------- comandos
    @grupo.command(name="status", description="Mostra a configuração do automod.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        d = await get_feature(interaction.guild_id, FEATURE, DEFAULTS)

        def onoff(v):
            return "✅" if v else "⚪"

        filtros = "\n".join(
            f"{onoff(d[k])} {FILTER_LABELS[k]}" for k in ("caps", "emoji", "repeat", "lines", "links")
        )
        e = emb("🤖 Automod", None)
        e.add_field(name="Filtros", value=filtros)
        e.add_field(name="Palavras filtradas", value=str(len(d["words"])))
        e.add_field(name="Links permitidos", value=", ".join(d["links_allow"])[:1000] or "—", inline=False)
        e.add_field(
            name="Punição",
            value=f"Timeout de {d['timeout_min']} min após {d['strikes']} infrações em 10 min" if d["strikes"] else "Só apaga a mensagem",
            inline=False,
        )
        raid_on = time.monotonic() < self._raid_until.get(interaction.guild_id, 0)
        e.add_field(
            name="Anti-raid",
            value=f"Modo **{d['raid_mode']}** · {d['raid_joins']} entradas em {d['raid_seconds']}s · bloqueio {d['raid_lock_min']} min" + (" · 🚨 ATIVO" if raid_on else ""),
            inline=False,
        )
        e.add_field(name="Idade mínima da conta", value=f"{d['min_age_days']} dia(s)" if d["min_age_days"] else "off")
        isentos = " ".join([f"<@&{r}>" for r in d["exempt_roles"]] + [f"<#{c}>" for c in d["exempt_channels"]])
        e.add_field(name="Isentos", value=isentos or "— (staff com Gerenciar Mensagens é sempre isenta)", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @grupo.command(name="filtro", description="Liga/desliga um filtro.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(tipo=[
        app_commands.Choice(name="Maiúsculas em excesso", value="caps"),
        app_commands.Choice(name="Emojis em excesso (10+)", value="emoji"),
        app_commands.Choice(name="Mensagem repetida (3x em 20s)", value="repeat"),
        app_commands.Choice(name="Flood de linhas (15+)", value="lines"),
        app_commands.Choice(name="Links (exceto permitidos)", value="links"),
    ])
    async def filtro(self, interaction: discord.Interaction, tipo: app_commands.Choice[str], ativo: bool):
        await set_feature(interaction.guild_id, FEATURE, **{tipo.value: ativo})
        log.info("Automod filtro %s=%s guild=%s por %s", tipo.value, ativo, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(f"✅ {tipo.name}: {'on' if ativo else 'off'}.", ephemeral=True)

    @grupo.command(name="palavra", description="Adiciona ou remove uma palavra do filtro.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def palavra(
        self,
        interaction: discord.Interaction,
        acao: Literal["adicionar", "remover"],
        palavra: app_commands.Range[str, 2, 60],
    ):
        d = await get_feature(interaction.guild_id, FEATURE, DEFAULTS)
        words = list(d["words"])
        norm = normalize(palavra)
        if not norm:
            return await interaction.response.send_message("❌ Palavra inválida.", ephemeral=True)
        existing = [w for w in words if normalize(w) == norm]
        if acao == "adicionar":
            if existing:
                return await interaction.response.send_message("Essa palavra já está no filtro.", ephemeral=True)
            if len(words) >= 300:
                return await interaction.response.send_message("❌ Limite de 300 palavras.", ephemeral=True)
            words.append(palavra.strip().lower())
        else:
            if not existing:
                return await interaction.response.send_message("Essa palavra não está no filtro.", ephemeral=True)
            words = [w for w in words if normalize(w) != norm]
        await set_feature(interaction.guild_id, FEATURE, words=words)
        log.info("Automod palavra %s guild=%s por %s", acao, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            f"✅ {'Adicionada' if acao == 'adicionar' else 'Removida'}: ||{discord.utils.escape_markdown(palavra)}|| ({len(words)} no filtro).\n"
            "O filtro ignora acentos, maiúsculas, letras repetidas e trocas como `4` → `a`.",
            ephemeral=True,
        )

    @grupo.command(name="palavras", description="Lista as palavras filtradas (só você vê).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def palavras(self, interaction: discord.Interaction):
        d = await get_feature(interaction.guild_id, FEATURE, DEFAULTS)
        words = d["words"]
        text = ", ".join(f"||{discord.utils.escape_markdown(w)}||" for w in words) or "Nenhuma."
        await interaction.response.send_message(embed=emb(f"🤬 Filtro de palavras ({len(words)})", text[:4000]), ephemeral=True)

    @grupo.command(name="link_permitido", description="Adiciona/remove um domínio liberado no filtro de links.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def link_permitido(self, interaction: discord.Interaction, dominio: app_commands.Range[str, 3, 100]):
        dom = re.sub(r"^(https?://)?(www\.)?", "", dominio.strip().lower()).split("/")[0]
        if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", dom):
            return await interaction.response.send_message("❌ Domínio inválido. Exemplo: `youtube.com`.", ephemeral=True)
        d = await get_feature(interaction.guild_id, FEATURE, DEFAULTS)
        allow = list(d["links_allow"])
        if dom in allow:
            allow.remove(dom)
            msg = f"➖ `{dom}` removido."
        else:
            if len(allow) >= 50:
                return await interaction.response.send_message("❌ Limite de 50 domínios.", ephemeral=True)
            allow.append(dom)
            msg = f"➕ `{dom}` liberado (inclui subdomínios)."
        await set_feature(interaction.guild_id, FEATURE, links_allow=allow)
        await interaction.response.send_message(msg, ephemeral=True)

    @grupo.command(name="isentar", description="Adiciona/remove um cargo ou canal isento do automod.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def isentar(
        self,
        interaction: discord.Interaction,
        cargo: Optional[discord.Role] = None,
        canal: Optional[discord.abc.GuildChannel] = None,
    ):
        if cargo is None and canal is None:
            return await interaction.response.send_message("Informe um cargo ou um canal.", ephemeral=True)
        d = await get_feature(interaction.guild_id, FEATURE, DEFAULTS)
        roles, chans, msgs = [int(x) for x in d["exempt_roles"]], [int(x) for x in d["exempt_channels"]], []
        for obj, lst in ((cargo, roles), (canal, chans)):
            if obj is None:
                continue
            if obj.id in lst:
                lst.remove(obj.id)
                msgs.append(f"➖ {obj.mention} voltou a ser verificado.")
            else:
                lst.append(obj.id)
                msgs.append(f"➕ {obj.mention} agora é isento.")
        await set_feature(interaction.guild_id, FEATURE, exempt_roles=roles[:25], exempt_channels=chans[:25])
        await interaction.response.send_message("\n".join(msgs), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @grupo.command(name="punicao", description="Timeout automático após X infrações em 10 minutos (0 desativa).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def punicao(
        self,
        interaction: discord.Interaction,
        infracoes: app_commands.Range[int, 0, 20],
        minutos: app_commands.Range[int, 1, 10080] = 10,
    ):
        await set_feature(interaction.guild_id, FEATURE, strikes=infracoes, timeout_min=minutos)
        txt = f"✅ Timeout de {minutos} min após {infracoes} infrações." if infracoes else "✅ Punição desativada: o automod só apaga."
        await interaction.response.send_message(txt, ephemeral=True)

    @grupo.command(name="antiraid", description="Configura a proteção contra raids.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        modo="off = desligado · alerta = só avisa no log · expulsar = expulsa quem entrar durante o raid",
        entradas="Quantas entradas disparam o alerta",
        segundos="Em quantos segundos",
        bloqueio_min="Quanto tempo o bloqueio dura",
    )
    async def antiraid(
        self,
        interaction: discord.Interaction,
        modo: Literal["off", "alerta", "expulsar"],
        entradas: app_commands.Range[int, 3, 50] = RAID_JOINS,
        segundos: app_commands.Range[int, 5, 600] = RAID_WINDOW,
        bloqueio_min: app_commands.Range[int, 1, 120] = 10,
    ):
        if modo == "expulsar" and not interaction.guild.me.guild_permissions.kick_members:
            return await interaction.response.send_message("❌ Preciso da permissão **Expulsar membros** para esse modo.", ephemeral=True)
        await set_feature(interaction.guild_id, FEATURE, raid_mode=modo, raid_joins=entradas, raid_seconds=segundos, raid_lock_min=bloqueio_min)
        log.info("Anti-raid guild=%s modo=%s %s/%ss por %s", interaction.guild_id, modo, entradas, segundos, interaction.user.id)
        await interaction.response.send_message(
            f"✅ Anti-raid **{modo}**: {entradas} entradas em {segundos}s · bloqueio de {bloqueio_min} min.", ephemeral=True
        )

    @grupo.command(name="raid_encerrar", description="Encerra o bloqueio anti-raid em andamento.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def raid_encerrar(self, interaction: discord.Interaction):
        active = self._raid_until.pop(interaction.guild_id, 0) > time.monotonic()
        self._joins.pop(interaction.guild_id, None)
        if active:
            log.info("Bloqueio anti-raid encerrado guild=%s por %s", interaction.guild_id, interaction.user.id)
            await send_log(interaction.guild, emb("✅ Raid encerrada", f"Bloqueio encerrado por {interaction.user.mention}."))
        await interaction.response.send_message("✅ Bloqueio encerrado." if active else "Nenhum bloqueio ativo.", ephemeral=True)

    @grupo.command(name="idade_minima", description="Expulsa contas mais novas que X dias ao entrar (0 desativa).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def idade_minima(self, interaction: discord.Interaction, dias: app_commands.Range[int, 0, 90]):
        if dias and not interaction.guild.me.guild_permissions.kick_members:
            return await interaction.response.send_message("❌ Preciso da permissão **Expulsar membros**.", ephemeral=True)
        await set_feature(interaction.guild_id, FEATURE, min_age_days=dias)
        await interaction.response.send_message(
            f"✅ Contas com menos de {dias} dia(s) serão expulsas ao entrar." if dias else "✅ Idade mínima desativada.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
