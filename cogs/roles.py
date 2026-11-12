import json
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import get_config, emb, get_db, log

# Cargos com qualquer uma destas permissões nunca podem ser auto-atribuídos por painel.
DANGEROUS_PERMS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks",
    "ban_members", "kick_members", "moderate_members", "mention_everyone", "manage_messages",
)


def role_problem(guild: discord.Guild, role: discord.Role, author: Optional[discord.Member] = None) -> Optional[str]:
    """Retorna o motivo pelo qual o cargo não pode entrar num painel, ou None se estiver ok.

    Compara posições: o cargo precisa estar ESTRITAMENTE abaixo do cargo mais alto do bot
    e, quando `author` é informado, abaixo do cargo mais alto de quem cria o painel
    (o dono do servidor é exceção). Sem `author`, só valida o lado do bot (uso na hora de conceder).
    """
    if guild.me is None:
        return "Não consegui identificar o membro do bot neste servidor."
    if not guild.me.guild_permissions.manage_roles:
        return "O bot precisa da permissão **Gerenciar Cargos** para atribuir cargos."
    me_top = guild.me.top_role
    if role.is_default():
        return "O cargo @everyone não pode ser usado em painel."
    if role.managed:
        return f"{role.mention} é gerenciado por uma integração ou bot e não pode ser atribuído manualmente."
    try:
        if role.is_premium_subscriber():
            return f"{role.mention} é um cargo de impulsionador e não pode ser atribuído manualmente."
    except AttributeError:
        pass
    if role.position >= me_top.position:
        return (
            f"Meu cargo mais alto ({me_top.mention}, posição {me_top.position}) precisa estar **acima** de "
            f"{role.mention} (posição {role.position}). Arraste meu cargo para cima em "
            f"**Configurações do Servidor → Cargos**."
        )
    if author is not None and author.id != guild.owner_id and role.position >= author.top_role.position:
        return (
            f"Você só pode usar cargos abaixo do seu cargo mais alto ({author.top_role.mention}, "
            f"posição {author.top_role.position}). {role.mention} está na posição {role.position}."
        )
    perigosas = [p for p in DANGEROUS_PERMS if getattr(role.permissions, p, False)]
    if perigosas:
        return f"{role.mention} tem permissões perigosas ({', '.join(perigosas)}) e não pode ser auto-atribuído por painel."
    return None



def _parse_panel_emoji(value: Optional[str]):
    """Converte emoji unicode/customizado em PartialEmoji; rejeita entrada inválida."""
    if not value:
        return None
    try:
        return discord.PartialEmoji.from_str(value.strip())
    except (TypeError, ValueError, discord.InvalidArgument):
        raise ValueError(f"Emoji inválido: {value}")


def _entry_payload(entries: list[dict]) -> str:
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))


class CargoButton(discord.ui.Button):
    def __init__(self, cog: "Roles", panel_id: str, entry: dict):
        self.cog = cog
        self.role_id = int(entry["role_id"])
        self.entry_label = str(entry["label"])
        super().__init__(
            label=f"Pegar {self.entry_label}"[:80],
            emoji=_parse_panel_emoji(entry.get("emoji")),
            style=discord.ButtonStyle.secondary,
            custom_id=f"hellsing:role:{panel_id}:{self.role_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        await self.cog._toggle_role(interaction, self.role_id, self.view)


class RoleButtonsView(discord.ui.View):
    def __init__(self, cog: "Roles", panel_id: str, entries: list[dict]):
        super().__init__(timeout=None)
        self.cog = cog
        self.panel_id = panel_id
        self.entries = entries[:5]
        for entry in self.entries:
            self.add_item(CargoButton(cog, panel_id, entry))


class RoleSelect(discord.ui.Select):
    def __init__(self, cog: "Roles", panel_id: str, entries: list[dict]):
        self.cog = cog
        self.entries = entries[:5]
        options = [
            discord.SelectOption(
                label=str(entry["label"])[:100],
                value=str(int(entry["role_id"])),
                emoji=_parse_panel_emoji(entry.get("emoji")),
            )
            for entry in self.entries
        ]
        super().__init__(
            placeholder="Selecione um ou mais cargos para alternar...",
            min_values=1,
            max_values=len(options),
            options=options,
            custom_id=f"hellsing:role-menu:{panel_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        await self.cog._apply_select_roles(interaction, self.entries, self.values, self.view)


class RoleMenuView(discord.ui.View):
    def __init__(self, cog: "Roles", panel_id: str, entries: list[dict]):
        super().__init__(timeout=None)
        self.add_item(RoleSelect(cog, panel_id, entries))


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verificar", style=discord.ButtonStyle.success, emoji="✅", custom_id="hellsing:verify")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await get_config(interaction.guild_id)
        role_id = cfg.get("verify_role")
        if not role_id:
            return await interaction.response.send_message(
                "❌ Cargo de verificação não configurado. Staff: `/config verificacao`.", ephemeral=True
            )
        role = interaction.guild.get_role(role_id)
        if not role:
            return await interaction.response.send_message("❌ Cargo de verificação sumiu.", ephemeral=True)
        problem = role_problem(interaction.guild, role)
        if problem:
            return await interaction.response.send_message(f"❌ {problem}", ephemeral=True)
        if role in interaction.user.roles:
            return await interaction.response.send_message("Você já está verificado.", ephemeral=True)
        try:
            await interaction.user.add_roles(role, reason="Verificação por botão")
        except discord.HTTPException:
            return await interaction.response.send_message("❌ Não consegui atribuir o cargo.", ephemeral=True)
        await interaction.response.send_message(f"✅ Verificado! Cargo {role.mention} concedido.", ephemeral=True)


class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._panels_restored = False

    async def cog_load(self):
        self.bot.add_view(VerifyView())

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._panels_restored:
            await self._restore_role_panels()
            self._panels_restored = True

    async def _restore_role_panels(self):
        """Restaura views persistentes e remove registros de painéis órfãos."""
        cursor = await get_db().execute(
            "SELECT message_id, guild_id, channel_id, panel_id, panel_type, entries FROM role_panels"
        )
        rows = await cursor.fetchall()
        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            channel = guild.get_channel(int(row["channel_id"])) if guild else None
            if channel is None:
                await get_db().execute("DELETE FROM role_panels WHERE message_id=?", (row["message_id"],))
                continue
            try:
                entries = json.loads(row["entries"])
                if row["panel_type"] == "buttons":
                    view = RoleButtonsView(self, row["panel_id"], entries)
                else:
                    view = RoleMenuView(self, row["panel_id"], entries)
                self.bot.add_view(view, message_id=int(row["message_id"]))
            except (ValueError, TypeError, KeyError, discord.InvalidArgument):
                log.exception("Painel de cargos inválido (message_id=%s); removendo registro.", row["message_id"])
                await get_db().execute("DELETE FROM role_panels WHERE message_id=?", (row["message_id"],))
        await get_db().commit()

    async def _toggle_role(self, interaction: discord.Interaction, role_id: int, view: discord.ui.View):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Este painel só funciona dentro do servidor.", ephemeral=True)
        role = interaction.guild.get_role(role_id)
        if role is None:
            return await interaction.response.send_message("❌ Este cargo não existe mais no servidor.", ephemeral=True)
        problem = role_problem(interaction.guild, role)
        if problem:
            return await interaction.response.send_message(f"❌ {problem}", ephemeral=True)
        if not interaction.guild.me or not interaction.guild.me.guild_permissions.manage_roles:
            return await interaction.response.send_message("❌ Não tenho a permissão Gerenciar Cargos.", ephemeral=True)
        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Auto-role: painel interativo")
                action = "removido"
            else:
                await member.add_roles(role, reason="Auto-role: painel interativo")
                action = "adicionado"
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Sem permissão para alterar este cargo. Verifique minha hierarquia.", ephemeral=True)
        except discord.HTTPException:
            log.exception("Falha ao alternar cargo %s para %s", role.id, member.id)
            return await interaction.response.send_message("❌ O Discord não aceitou a alteração do cargo.", ephemeral=True)
        try:
            await interaction.response.send_message(
                f"✅ Cargo **{role.name}** {action}.",
                ephemeral=True,
            )
        except discord.HTTPException:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"✅ Cargo {action}.", ephemeral=True)

    async def _apply_select_roles(self, interaction: discord.Interaction, entries: list[dict], values: list[str], view: discord.ui.View):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Este painel só funciona dentro do servidor.", ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        selected_ids = {int(value) for value in values}
        roles_to_add, roles_to_remove = [], []
        for role_id in selected_ids:
            role = guild.get_role(role_id)
            if role is None:
                return await interaction.response.send_message("❌ Um dos cargos deste painel não existe mais.", ephemeral=True)
            problem = role_problem(guild, role)
            if problem:
                return await interaction.response.send_message(f"❌ Painel bloqueado: {problem}", ephemeral=True)
            if role in member.roles:
                roles_to_remove.append(role)
            else:
                roles_to_add.append(role)
        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Auto-role: menu interativo")
            if roles_to_add:
                await member.add_roles(*roles_to_add, reason="Auto-role: menu interativo")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Sem permissão para alterar os cargos. Verifique minha hierarquia.", ephemeral=True)
        except discord.HTTPException:
            log.exception("Falha ao alternar cargos pelo menu para %s", member.id)
            return await interaction.response.send_message("❌ O Discord não aceitou a alteração dos cargos.", ephemeral=True)
        changes = []
        changes.extend(f"✅ {role.mention} adicionado" for role in roles_to_add)
        changes.extend(f"🗑️ {role.mention} removido" for role in roles_to_remove)
        await interaction.response.send_message("\n".join(changes) or "Nenhuma alteração necessária.", ephemeral=True)

    async def _create_interactive_panel(self, interaction: discord.Interaction, title: str, description: str, entries: list[dict], panel_type: str):
        if not title.strip() or len(title) > 256:
            return await interaction.response.send_message("❌ O título precisa ter entre 1 e 256 caracteres.", ephemeral=True)
        if len(description) > 3000:
            return await interaction.response.send_message("❌ A descrição deve ter no máximo 3.000 caracteres.", ephemeral=True)
        problems = []
        for entry in entries:
            role = interaction.guild.get_role(int(entry["role_id"]))
            if role is None:
                problems.append(f"• O cargo ID {entry['role_id']} não existe mais.")
                continue
            problem = role_problem(interaction.guild, role, interaction.user)
            if problem:
                problems.append(f"• {problem}")
            try:
                _parse_panel_emoji(entry.get("emoji"))
            except ValueError as exc:
                problems.append(f"• {exc}")
        if problems:
            return await interaction.response.send_message("❌ Painel não criado:\n" + "\n".join(problems), ephemeral=True)
        import uuid
        panel_id = uuid.uuid4().hex
        lines = [f"{entry.get('emoji') + ' ' if entry.get('emoji') else ''}**{entry['label']}** — <@&{entry['role_id']}>" for entry in entries]
        instrucao = (
            "\n\nClique para receber ou remover o cargo."
            if panel_type == "buttons"
            else "\n\nSelecione uma ou mais opções para alternar os cargos; selecione novamente para remover."
        )
        e = emb(f"🎭 {title}", f"{description}\n\n" + "\n".join(lines) + instrucao)
        view = RoleButtonsView(self, panel_id, entries) if panel_type == "buttons" else RoleMenuView(self, panel_id, entries)
        await interaction.response.defer(ephemeral=True)
        try:
            message = await interaction.channel.send(embed=e, view=view)
            await get_db().execute(
                "INSERT INTO role_panels(message_id,guild_id,channel_id,panel_id,panel_type,entries) VALUES(?,?,?,?,?,?)",
                (message.id, interaction.guild.id, interaction.channel_id, panel_id, panel_type, _entry_payload(entries)),
            )
            await get_db().commit()
            # Registra explicitamente a view associada à mensagem publicada.
            self.bot.add_view(view, message_id=message.id)
        except Exception:
            log.exception("Falha ao publicar painel interativo de cargos")
            if 'message' in locals():
                try:
                    await get_db().execute("DELETE FROM role_panels WHERE message_id=?", (message.id,))
                    await get_db().commit()
                    self.bot.remove_view(view)
                    await message.delete()
                except discord.HTTPException:
                    pass
            return await interaction.followup.send("❌ Não consegui publicar/salvar o painel. Nenhum painel foi mantido.", ephemeral=True)
        await interaction.followup.send("✅ Painel interativo criado e salvo; continuará funcionando após reinicializações.", ephemeral=True)

    @app_commands.command(name="painel_cargos", description="Cria um painel de reaction roles.")
    @app_commands.describe(
        titulo="Título do painel",
        descricao="Descrição",
        emoji1="Emoji 1",
        cargo1="Cargo do emoji 1",
        emoji2="Emoji 2 (opcional)",
        cargo2="Cargo 2 (opcional)",
        emoji3="Emoji 3 (opcional)",
        cargo3="Cargo 3 (opcional)",
    )
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def painel_cargos(
        self,
        interaction: discord.Interaction,
        titulo: str,
        descricao: str,
        emoji1: str,
        cargo1: discord.Role,
        emoji2: Optional[str] = None,
        cargo2: Optional[discord.Role] = None,
        emoji3: Optional[str] = None,
        cargo3: Optional[discord.Role] = None,
    ):
        pairs = [(emoji1, cargo1)]
        if emoji2 and cargo2:
            pairs.append((emoji2, cargo2))
        if emoji3 and cargo3:
            pairs.append((emoji3, cargo3))

        problems: List[str] = []
        for _, role in pairs:
            problem = role_problem(interaction.guild, role, interaction.user)
            if problem:
                problems.append(f"• {problem}")
        if problems:
            return await interaction.response.send_message("❌ Painel não criado:\n" + "\n".join(problems), ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        lines = [f"{em} → {role.mention}" for em, role in pairs]
        e = emb(f"🎭 {titulo}", f"{descricao}\n\n" + "\n".join(lines) + "\n\nReaja para receber o cargo.")
        msg = await interaction.channel.send(embed=e)

        failed: List[str] = []
        for em, role in pairs:
            try:
                await msg.add_reaction(em)
            except discord.HTTPException:
                failed.append(em)
                continue
            await get_db().execute(
                "INSERT OR REPLACE INTO reaction_roles(message_id, emoji, role_id) VALUES(?,?,?)",
                (msg.id, str(em), role.id),
            )
        await get_db().commit()
        if failed:
            await interaction.followup.send(f"⚠️ Painel criado, mas estes emojis foram rejeitados e não funcionam: {' '.join(failed)}", ephemeral=True)
        else:
            await interaction.followup.send("✅ Painel criado.", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id or payload.user_id == self.bot.user.id:
            return
        emoji = str(payload.emoji)
        row = await (await get_db().execute(
            "SELECT role_id FROM reaction_roles WHERE message_id=? AND emoji=?",
            (payload.message_id, emoji),
        )).fetchone()
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = payload.member or guild.get_member(payload.user_id)
        role = guild.get_role(row["role_id"])
        if not member or member.bot or not role:
            return
        # Revalida na hora de conceder: o cargo pode ter ganho permissões ou subido de posição depois.
        problem = role_problem(guild, role)
        if problem:
            log.warning("Reaction role bloqueado (%s, cargo %s): %s", guild.id, role.id, problem)
            return
        try:
            await member.add_roles(role, reason="Reaction role")
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id:
            return
        emoji = str(payload.emoji)
        row = await (await get_db().execute(
            "SELECT role_id FROM reaction_roles WHERE message_id=? AND emoji=?",
            (payload.message_id, emoji),
        )).fetchone()
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.NotFound:
                # O usuário saiu do servidor; não há mais cargo a remover.
                return
            except discord.Forbidden:
                log.warning(
                    "Sem permissão para buscar membro em reaction role (guild=%s, user=%s).",
                    guild.id, payload.user_id,
                )
                return
            except discord.HTTPException:
                log.exception(
                    "Falha ao buscar membro em reaction role (guild=%s, user=%s).",
                    guild.id, payload.user_id,
                )
                return
        role = guild.get_role(row["role_id"])
        if role is None:
            return
        try:
            await member.remove_roles(role, reason="Reaction role removido")
        except discord.Forbidden:
            log.warning(
                "Sem permissão/hierarquia para remover reaction role (guild=%s, user=%s, role=%s).",
                guild.id, member.id, role.id,
            )
        except discord.HTTPException:
            log.exception(
                "Falha ao remover reaction role (guild=%s, user=%s, role=%s).",
                guild.id, member.id, role.id,
            )



    @app_commands.command(name="painel_cargos_botoes", description="Cria painel de cargos com botões de alternância.")
    @app_commands.describe(titulo="Título do painel", descricao="Descrição do painel",
        cargo_1="Primeiro cargo", label_1="Texto do botão 1", emoji_1="Emoji opcional do botão 1",
        cargo_2="Segundo cargo (opcional)", label_2="Texto do botão 2", emoji_2="Emoji opcional do botão 2",
        cargo_3="Terceiro cargo (opcional)", label_3="Texto do botão 3", emoji_3="Emoji opcional do botão 3",
        cargo_4="Quarto cargo (opcional)", label_4="Texto do botão 4", emoji_4="Emoji opcional do botão 4",
        cargo_5="Quinto cargo (opcional)", label_5="Texto do botão 5", emoji_5="Emoji opcional do botão 5")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def painel_cargos_botoes(self, interaction: discord.Interaction, titulo: str, descricao: str,
        cargo_1: discord.Role, label_1: str, emoji_1: Optional[str] = None,
        cargo_2: Optional[discord.Role] = None, label_2: Optional[str] = None, emoji_2: Optional[str] = None,
        cargo_3: Optional[discord.Role] = None, label_3: Optional[str] = None, emoji_3: Optional[str] = None,
        cargo_4: Optional[discord.Role] = None, label_4: Optional[str] = None, emoji_4: Optional[str] = None,
        cargo_5: Optional[discord.Role] = None, label_5: Optional[str] = None, emoji_5: Optional[str] = None):
        raw = [(cargo_1, label_1, emoji_1), (cargo_2, label_2, emoji_2), (cargo_3, label_3, emoji_3), (cargo_4, label_4, emoji_4), (cargo_5, label_5, emoji_5)]
        entries = []
        for role, label, emoji in raw:
            if role is None:
                if label or emoji:
                    return await interaction.response.send_message("❌ Informe o cargo correspondente para cada label/emoji.", ephemeral=True)
                continue
            if not label or not label.strip():
                return await interaction.response.send_message("❌ Todo cargo informado precisa de um label.", ephemeral=True)
            entries.append({"role_id": role.id, "label": label.strip()[:80], "emoji": emoji.strip() if emoji else None})
        if not entries:
            return await interaction.response.send_message("❌ Informe pelo menos um cargo.", ephemeral=True)
        if len({e["role_id"] for e in entries}) != len(entries):
            return await interaction.response.send_message("❌ Não repita o mesmo cargo no painel.", ephemeral=True)
        await self._create_interactive_panel(interaction, titulo, descricao, entries, "buttons")

    @app_commands.command(name="painel_cargos_menu", description="Cria painel de cargos com menu de seleção.")
    @app_commands.describe(titulo="Título do painel", descricao="Descrição do painel",
        cargo_1="Primeiro cargo", label_1="Nome da opção 1", emoji_1="Emoji opcional da opção 1",
        cargo_2="Segundo cargo (opcional)", label_2="Nome da opção 2", emoji_2="Emoji opcional da opção 2",
        cargo_3="Terceiro cargo (opcional)", label_3="Nome da opção 3", emoji_3="Emoji opcional da opção 3",
        cargo_4="Quarto cargo (opcional)", label_4="Nome da opção 4", emoji_4="Emoji opcional da opção 4",
        cargo_5="Quinto cargo (opcional)", label_5="Nome da opção 5", emoji_5="Emoji opcional da opção 5")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def painel_cargos_menu(self, interaction: discord.Interaction, titulo: str, descricao: str,
        cargo_1: discord.Role, label_1: str, emoji_1: Optional[str] = None,
        cargo_2: Optional[discord.Role] = None, label_2: Optional[str] = None, emoji_2: Optional[str] = None,
        cargo_3: Optional[discord.Role] = None, label_3: Optional[str] = None, emoji_3: Optional[str] = None,
        cargo_4: Optional[discord.Role] = None, label_4: Optional[str] = None, emoji_4: Optional[str] = None,
        cargo_5: Optional[discord.Role] = None, label_5: Optional[str] = None, emoji_5: Optional[str] = None):
        raw = [(cargo_1, label_1, emoji_1), (cargo_2, label_2, emoji_2), (cargo_3, label_3, emoji_3), (cargo_4, label_4, emoji_4), (cargo_5, label_5, emoji_5)]
        entries = []
        for role, label, emoji in raw:
            if role is None:
                if label or emoji:
                    return await interaction.response.send_message("❌ Informe o cargo correspondente para cada label/emoji.", ephemeral=True)
                continue
            if not label or not label.strip():
                return await interaction.response.send_message("❌ Todo cargo informado precisa de um label.", ephemeral=True)
            entries.append({"role_id": role.id, "label": label.strip()[:100], "emoji": emoji.strip() if emoji else None})
        if not entries:
            return await interaction.response.send_message("❌ Informe pelo menos um cargo.", ephemeral=True)
        if len({e["role_id"] for e in entries}) != len(entries):
            return await interaction.response.send_message("❌ Não repita o mesmo cargo no painel.", ephemeral=True)
        await self._create_interactive_panel(interaction, titulo, descricao, entries, "menu")

    @app_commands.command(name="painel_verificacao", description="Publica o botão de verificação (cargo de membro).")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def painel_verificacao(self, interaction: discord.Interaction):
        cfg = await get_config(interaction.guild_id)
        if not cfg.get("verify_role"):
            return await interaction.response.send_message(
                "Configure antes: `/config verificacao cargo:@Membro`", ephemeral=True
            )
        e = emb(
            "✅ Verificação",
            "Clique no botão abaixo para receber o cargo de **membro** e acessar o servidor.\n"
            "Ao verificar, você confirma que leu as regras.",
        )
        await interaction.channel.send(embed=e, view=VerifyView())
        await interaction.response.send_message("✅ Painel de verificação publicado.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot))
