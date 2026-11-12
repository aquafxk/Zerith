"""Boas-vindas, despedida, DM de entrada, cartão de imagem e autorole (v3.1.0)."""
from __future__ import annotations

import asyncio
import io
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import COLOR, FOOTER, emb, get_config, get_feature, set_config, set_feature
from cogs.roles import role_problem

log = logging.getLogger("hellsing.boasvindas")

FEATURE = "welcome"
DEFAULTS = {
    "join_message": "",
    "image": True,
    "dm_enabled": False,
    "dm_message": "",
    "leave_channel": None,
    "leave_message": "",
    "autoroles": [],
    "bot_roles": [],
}

DEFAULT_JOIN = (
    "Bem-vindo(a), {membro}!\n"
    "Você é o membro **#{contador}** de **{servidor}**.\n"
    "📜 {regras}"
)
DEFAULT_LEAVE = "**{usuario}** saiu do servidor. Agora somos **{contador}**."
DEFAULT_DM = "Olá, {nome}! Seja bem-vindo(a) a **{servidor}**. {regras}"

PLACEHOLDERS_HELP = (
    "`{membro}` menção · `{nome}` apelido · `{usuario}` nome de usuário · "
    "`{servidor}` · `{contador}` nº de membros · `{regras}` canal de regras"
)

try:  # Pillow é opcional: sem ele, a boas-vindas sai só em embed.
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    HAS_PIL = True
except ImportError:  # pragma: no cover - depende do ambiente
    HAS_PIL = False


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_template(template: str, member: discord.Member, rules_channel_id: Optional[int]) -> str:
    guild = member.guild
    rules = guild.get_channel(int(rules_channel_id)) if rules_channel_id else None
    values = _SafeDict(
        membro=member.mention,
        nome=discord.utils.escape_markdown(member.display_name),
        usuario=discord.utils.escape_markdown(member.name),
        servidor=discord.utils.escape_markdown(guild.name),
        contador=guild.member_count or len(guild.members),
        regras=f"Leia as regras em {rules.mention}." if rules else "Respeite as regras do servidor.",
    )
    try:
        return template.format_map(values)[:4000]
    except (ValueError, IndexError):  # chaves mal formadas: mostra o texto cru
        return template[:4000]


def _load_font(size: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _fit(text: str, font, max_width: int, draw) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"



# Pool pequeno para render Pillow (CPU-bound). 1 worker evita estourar RAM na hospedagem.


def build_card(avatar_bytes: Optional[bytes], title: str, name: str, subtitle: str) -> bytes:
    """Gera um cartão 1000x340 em PNG (executar em thread)."""
    w, h = 1000, 340
    img = Image.new("RGB", (w, h), (18, 8, 10))
    draw = ImageDraw.Draw(img)
    top, bottom = (137, 40, 43), (20, 6, 8)
    for y in range(h):
        t = y / (h - 1)
        draw.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    draw.rounded_rectangle([18, 18, w - 18, h - 18], radius=28, outline=(220, 70, 70), width=4)

    size = 220
    x0, y0 = 50, (h - size) // 2
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            av = ImageOps.fit(av, (size, size))
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
            img.paste(av, (x0, y0), mask)
        except Exception:
            log.debug("Avatar inválido no cartão de boas-vindas", exc_info=True)
    draw.ellipse([x0 - 5, y0 - 5, x0 + size + 5, y0 + size + 5], outline=(240, 240, 240), width=6)

    tx, max_w = x0 + size + 45, w - (x0 + size + 45) - 50
    f_title, f_name, f_sub = _load_font(54), _load_font(44), _load_font(30)
    draw.text((tx, 70), _fit(title, f_title, max_w, draw), font=f_title, fill=(255, 255, 255))
    draw.text((tx, 145), _fit(name, f_name, max_w, draw), font=f_name, fill=(255, 210, 210))
    draw.text((tx, 215), _fit(subtitle, f_sub, max_w, draw), font=f_sub, fill=(220, 190, 190))

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


async def make_card_file(member: discord.Member, title: str, subtitle: str) -> Optional[discord.File]:
    if not HAS_PIL:
        return None
    try:
        avatar = await member.display_avatar.replace(size=256, static_format="png").read()
    except (discord.HTTPException, ValueError):
        avatar = None
    try:
        data = await asyncio.to_thread(build_card, avatar, title, member.display_name, subtitle)
    except Exception:
        log.exception("Falha ao gerar cartão de boas-vindas (guild=%s)", member.guild.id)
        return None
    return discord.File(io.BytesIO(data), filename="boasvindas.png")


def _sendable(channel, guild: discord.Guild, *, files: bool = False) -> bool:
    if not isinstance(channel, (discord.TextChannel, discord.Thread)) or guild.me is None:
        return False
    perms = channel.permissions_for(guild.me)
    return perms.send_messages and perms.embed_links and (perms.attach_files or not files)


class BoasVindas(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


    grupo = app_commands.Group(
        name="boasvindas",
        description="Boas-vindas, despedida e cargos automáticos",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # ------------------------------------------------------------------ envio
    async def send_welcome(self, member: discord.Member, *, channel=None, test: bool = False) -> bool:
        guild = member.guild
        cfg = await get_config(guild.id)
        data = await get_feature(guild.id, FEATURE, DEFAULTS)
        channel = channel or (guild.get_channel(int(cfg["welcome_channel"])) if cfg.get("welcome_channel") else None)
        if channel is None:
            return False
        text = render_template(data["join_message"] or DEFAULT_JOIN, member, cfg.get("rules_channel"))
        e = discord.Embed(title="🦇 Novo recruta" + (" (teste)" if test else ""), description=text, color=COLOR)
        e.set_footer(text=FOOTER)
        file = None
        if data.get("image"):
            file = await make_card_file(member, "BEM-VINDO(A)", f"Membro #{guild.member_count or len(guild.members)}")
        if file is not None and _sendable(channel, guild, files=True):
            e.set_image(url="attachment://boasvindas.png")
        else:
            file = None
            e.set_thumbnail(url=member.display_avatar.url)
        if not _sendable(channel, guild):
            log.warning("Sem permissão para enviar boas-vindas em #%s (guild=%s)", channel, guild.id)
            return False
        try:
            kwargs = {"embed": e, "allowed_mentions": discord.AllowedMentions(users=[member], roles=False, everyone=False)}
            if file is not None:
                kwargs["file"] = file
            await channel.send(content=member.mention if not test else None, **kwargs)
            return True
        except discord.HTTPException as exc:
            log.warning("Falha ao enviar boas-vindas (guild=%s): %s", guild.id, exc)
            return False

    async def send_dm(self, member: discord.Member) -> None:
        data = await get_feature(member.guild.id, FEATURE, DEFAULTS)
        if not data.get("dm_enabled"):
            return
        cfg = await get_config(member.guild.id)
        text = render_template(data["dm_message"] or DEFAULT_DM, member, cfg.get("rules_channel"))
        try:
            await member.send(embed=emb(f"🦇 {member.guild.name}", text))
        except discord.HTTPException:
            log.debug("DM de boas-vindas recusada por %s (guild=%s)", member.id, member.guild.id)

    async def give_autoroles(self, member: discord.Member) -> None:
        data = await get_feature(member.guild.id, FEATURE, DEFAULTS)
        ids = data["bot_roles"] if member.bot else data["autoroles"]
        roles = []
        for rid in ids:
            role = member.guild.get_role(int(rid))
            if role is None or role in member.roles:
                continue
            problem = role_problem(member.guild, role)
            if problem:
                log.warning("Autorole %s bloqueado (guild=%s): %s", rid, member.guild.id, problem)
                continue
            roles.append(role)
        if not roles:
            return
        try:
            await member.add_roles(*roles, reason="Autorole de entrada")
            log.info("Autorole guild=%s user=%s: %s", member.guild.id, member.id, [r.id for r in roles])
        except discord.HTTPException as exc:
            log.warning("Falha no autorole (guild=%s, user=%s): %s", member.guild.id, member.id, exc)

    # -------------------------------------------------------------- listeners
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Com a triagem de membros ativa, o cargo só é dado depois do aceite (on_member_update).
        if not member.pending:
            await self.give_autoroles(member)
        if member.bot:
            return
        await self.send_welcome(member)
        await self.send_dm(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.pending and not after.pending:
            await self.give_autoroles(after)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        data = await get_feature(member.guild.id, FEATURE, DEFAULTS)
        cid = data.get("leave_channel")
        channel = member.guild.get_channel(int(cid)) if cid else None
        if channel is None or not _sendable(channel, member.guild):
            return
        cfg = await get_config(member.guild.id)
        text = render_template(data["leave_message"] or DEFAULT_LEAVE, member, cfg.get("rules_channel"))
        e = discord.Embed(title="🌑 Até mais", description=text, color=0x555555)
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text=FOOTER)
        try:
            await channel.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.warning("Falha ao enviar despedida (guild=%s): %s", member.guild.id, exc)

    # --------------------------------------------------------------- comandos
    @grupo.command(name="configurar", description="Configura canal, mensagens, imagem, DM e despedida.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        canal="Canal de entrada; deixe vazio para manter o atual.",
        mensagem="Texto de entrada; use 'padrao' para restaurar.",
        imagem="Ativa ou desativa o cartão de imagem.",
        dm="Ativa ou desativa a mensagem privada.",
        mensagem_dm="Texto da DM; use 'padrao' para restaurar.",
        canal_saida="Canal de despedida; deixe vazio para manter o atual.",
        mensagem_saida="Texto de despedida; use 'padrao' para restaurar.",
        desativar_canal="Desativa o canal de entrada configurado.",
        desativar_saida="Desativa o canal de despedida configurado.",
    )
    async def configurar(
        self,
        interaction: discord.Interaction,
        canal: Optional[discord.TextChannel] = None,
        mensagem: Optional[app_commands.Range[str, 1, 1500]] = None,
        imagem: Optional[bool] = None,
        dm: Optional[bool] = None,
        mensagem_dm: Optional[app_commands.Range[str, 1, 1500]] = None,
        canal_saida: Optional[discord.TextChannel] = None,
        mensagem_saida: Optional[app_commands.Range[str, 1, 1500]] = None,
        desativar_canal: bool = False,
        desativar_saida: bool = False,
    ):
        """Atualiza somente os campos enviados; campos omitidos permanecem intactos."""
        try:
            if desativar_canal and canal is not None:
                return await interaction.response.send_message(
                    "Não informe `canal` e `desativar_canal` ao mesmo tempo.", ephemeral=True
                )
            if desativar_saida and canal_saida is not None:
                return await interaction.response.send_message(
                    "Não informe `canal_saida` e `desativar_saida` ao mesmo tempo.", ephemeral=True
                )

            config_changes = {}
            feature_changes = {}
            if canal is not None:
                config_changes["welcome_channel"] = canal.id
            elif desativar_canal:
                config_changes["welcome_channel"] = None
            if mensagem is not None:
                feature_changes["join_message"] = (
                    "" if mensagem.strip().lower() in {"padrao", "padrão", "reset"}
                    else mensagem.replace("\\n", "\n")
                )
            if imagem is not None:
                feature_changes["image"] = imagem
            if dm is not None:
                feature_changes["dm_enabled"] = dm
            if mensagem_dm is not None:
                feature_changes["dm_message"] = (
                    "" if mensagem_dm.strip().lower() in {"padrao", "padrão", "reset"}
                    else mensagem_dm.replace("\\n", "\n")
                )
            if canal_saida is not None:
                feature_changes["leave_channel"] = canal_saida.id
            elif desativar_saida:
                feature_changes["leave_channel"] = None
            if mensagem_saida is not None:
                feature_changes["leave_message"] = (
                    "" if mensagem_saida.strip().lower() in {"padrao", "padrão", "reset"}
                    else mensagem_saida.replace("\\n", "\n")
                )

            if not config_changes and not feature_changes:
                return await interaction.response.send_message(
                    "Informe pelo menos uma opção para alterar. Use `/boasvindas ver` para consultar a configuração.",
                    ephemeral=True,
                )
            if config_changes:
                await set_config(interaction.guild_id, **config_changes)
            if feature_changes:
                await set_feature(interaction.guild_id, FEATURE, **feature_changes)

            changed = []
            if "welcome_channel" in config_changes:
                changed.append("canal de entrada")
            if "join_message" in feature_changes:
                changed.append("mensagem de entrada")
            if "image" in feature_changes:
                changed.append("cartão de imagem")
            if "dm_enabled" in feature_changes or "dm_message" in feature_changes:
                changed.append("mensagem privada")
            if "leave_channel" in feature_changes or "leave_message" in feature_changes:
                changed.append("despedida")
            log.info("Boas-vindas configuradas guild=%s por=%s campos=%s", interaction.guild_id, interaction.user.id, changed)
            await interaction.response.send_message(
                "Configuração atualizada: " + ", ".join(changed) + ".\nUse `/boasvindas testar` para conferir a prévia.",
                ephemeral=True,
            )
        except Exception as exc:
            log.exception("Falha ao configurar boas-vindas (guild=%s)", interaction.guild_id)
            message = "Não foi possível salvar a configuração. Consulte os logs do bot."
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)

    @grupo.command(name="cargo", description="Configura um cargo automático para membros ou bots.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(tipo=[
        app_commands.Choice(name="Membros", value="autoroles"),
        app_commands.Choice(name="Bots", value="bot_roles"),
    ])
    async def cargo(
        self,
        interaction: discord.Interaction,
        tipo: app_commands.Choice[str],
        cargo: discord.Role,
    ):
        key = tipo.value
        label = "autorole de membros" if key == "autoroles" else "autorole de bots"
        await self._toggle_role(interaction, cargo, key, label)

    async def _toggle_role(self, interaction: discord.Interaction, cargo: discord.Role, key: str, label: str):
        try:
            problem = role_problem(interaction.guild, cargo, interaction.user)
            data = await get_feature(interaction.guild_id, FEATURE, DEFAULTS)
            ids = [int(r) for r in data[key]]
            if cargo.id in ids:
                ids.remove(cargo.id)
                msg = f"{cargo.mention} removido do {label}."
            else:
                if problem:
                    return await interaction.response.send_message(problem, ephemeral=True)
                if len(ids) >= 10:
                    return await interaction.response.send_message("Limite de 10 cargos.", ephemeral=True)
                ids.append(cargo.id)
                msg = f"{cargo.mention} adicionado ao {label}."
            await set_feature(interaction.guild_id, FEATURE, **{key: ids})
            log.info("Autorole %s guild=%s por=%s: %s", key, interaction.guild_id, interaction.user.id, ids)
            await interaction.response.send_message(msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            log.exception("Falha ao alterar autorole (guild=%s)", interaction.guild_id)
            await interaction.response.send_message("Não foi possível alterar o cargo automático.", ephemeral=True)

    @grupo.command(name="ver", description="Mostra a configuração atual.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ver(self, interaction: discord.Interaction):
        guild = interaction.guild
        cfg = await get_config(guild.id)
        data = await get_feature(guild.id, FEATURE, DEFAULTS)

        def ch(cid):
            c = guild.get_channel(int(cid)) if cid else None
            return c.mention if c else "—"

        def roles(ids):
            return " ".join(f"<@&{r}>" for r in ids) or "—"

        e = emb("🦇 Boas-vindas", None)
        e.add_field(name="Canal", value=ch(cfg.get("welcome_channel")))
        e.add_field(name="Cartão de imagem", value=("on" if data["image"] else "off") + ("" if HAS_PIL else " (sem Pillow)"))
        e.add_field(name="DM", value="on" if data["dm_enabled"] else "off")
        e.add_field(name="Despedida", value=ch(data["leave_channel"]))
        e.add_field(name="Autorole", value=roles(data["autoroles"]), inline=False)
        e.add_field(name="Autorole de bots", value=roles(data["bot_roles"]), inline=False)
        e.add_field(name="Mensagem", value=(data["join_message"] or DEFAULT_JOIN)[:1000], inline=False)
        e.add_field(name="Variáveis", value=PLACEHOLDERS_HELP, inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @grupo.command(name="testar", description="Envia uma prévia das boas-vindas aqui.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def testar(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok = await self.send_welcome(interaction.user, channel=interaction.channel, test=True)
        await interaction.followup.send("✅ Prévia enviada." if ok else "❌ Não consegui enviar aqui (permissões?).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BoasVindas(bot))
