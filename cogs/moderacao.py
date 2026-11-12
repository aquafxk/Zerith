from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import emb, get_db, add_case, send_log, WARN_TIMEOUT_AT
import logging
import time

log = logging.getLogger("hellsing.moderacao")


def audit_reason(interaction: discord.Interaction, motivo: str) -> str:
    return f"{interaction.user} ({interaction.user.id}): {motivo}"[:512]


def check_target(interaction: discord.Interaction, target: discord.Member) -> Optional[str]:
    guild = interaction.guild
    if target.id == interaction.user.id:
        return "Você não pode aplicar isso em si mesmo."
    if target.id == guild.me.id:
        return "Não vou punir a mim mesmo."
    if target.id == guild.owner_id:
        return "Não é possível punir o dono do servidor."
    if interaction.user.id != guild.owner_id and target.top_role >= interaction.user.top_role:
        return "O cargo do alvo é igual ou superior ao seu."
    if target.top_role >= guild.me.top_role:
        return "O cargo do alvo é igual ou superior ao meu."
    return None


async def mod_log(guild: discord.Guild, embed: discord.Embed) -> None:
    embed.timestamp = embed.timestamp or discord.utils.utcnow()
    await send_log(guild, embed)


class NukeConfirmView(discord.ui.View):
    """Confirmação dupla para recriar somente o canal atual, sem tocar no servidor todo."""
    def __init__(self, owner_id: int, channel: discord.TextChannel):
        super().__init__(timeout=45)
        self.owner_id = owner_id
        self.channel = channel

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Somente quem iniciou o comando pode confirmar.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar nuke deste canal", style=discord.ButtonStyle.danger, emoji="💣")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild or not isinstance(self.channel, discord.TextChannel):
            return await interaction.response.send_message("Canal inválido.", ephemeral=True)
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            return await interaction.response.send_message("O bot precisa de Gerenciar Canais.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            clone = await self.channel.clone(reason=f"Nuke confirmado por {interaction.user} ({interaction.user.id})")
            await clone.edit(position=self.channel.position)
            await self.channel.delete(reason=f"Nuke confirmado por {interaction.user} ({interaction.user.id})")
            try:
                await clone.send(
                    f"✅ Canal recriado com sucesso por {interaction.user.mention}. "
                    "O histórico anterior foi purgado."
                )
            except discord.HTTPException:
                pass
        except discord.HTTPException as exc:
            await interaction.followup.send(f"❌ Não foi possível recriar o canal (HTTP {exc.status}).", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Operação cancelada.", embed=None, view=self)
        self.stop()


class Moderacao(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _finish(self, interaction, title, target, motivo, action, extra=""):
        case_id = await add_case(interaction.guild_id, target.id, interaction.user.id, action, motivo)
        log.info(
            "Moderação %s caso #%s guild=%s alvo=%s (%s) mod=%s (%s) motivo=%r",
            action, case_id, interaction.guild_id, target, target.id, interaction.user, interaction.user.id, motivo[:200],
        )
        e = emb(title, f"**Caso:** `#{case_id}`\n**Alvo:** {target.mention} (`{target.id}`)\n**Moderador:** {interaction.user.mention}\n**Motivo:** {motivo}{extra}")
        await interaction.followup.send(embed=e)
        await mod_log(interaction.guild, e)

    @app_commands.command(name="kick", description="Expulsa um membro.")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, membro: discord.Member, motivo: str = "Sem motivo"):
        if err := check_target(interaction, membro):
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await interaction.response.defer()
        try:
            await membro.kick(reason=audit_reason(interaction, motivo))
        except discord.HTTPException:
            return await interaction.followup.send("❌ Falha ao expulsar.")
        await self._finish(interaction, "👢 Expulso", membro, motivo, "KICK")

    @app_commands.command(name="ban", description="Bane um usuário, mesmo que já tenha saído do servidor.")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, usuario: discord.User, motivo: str = "Sem motivo"):
        membro = interaction.guild.get_member(usuario.id)
        if membro and (err := check_target(interaction, membro)):
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await interaction.response.defer()
        try:
            await interaction.guild.ban(usuario, reason=audit_reason(interaction, motivo), delete_message_seconds=0)
        except discord.HTTPException:
            return await interaction.followup.send("❌ Falha ao banir. Verifique a permissão Banir membros e a hierarquia.")
        await self._finish(interaction, "🔨 Usuário banido", usuario, motivo, "BAN")

    @app_commands.command(name="unban", description="Revoga um banimento usando o ID do usuário.")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, motivo: str = "Banimento revogado pela Staff"):
        if not user_id.isdigit() or int(user_id) <= 0:
            return await interaction.response.send_message("❌ Informe um ID numérico válido.", ephemeral=True)
        await interaction.response.defer()
        target_id = int(user_id)
        try:
            await interaction.guild.unban(discord.Object(id=target_id), reason=audit_reason(interaction, motivo))
        except discord.NotFound:
            return await interaction.followup.send("❌ Esse usuário não consta na lista de banidos.")
        except discord.HTTPException:
            return await interaction.followup.send("❌ Falha ao revogar o banimento.")
        case_id = await add_case(interaction.guild_id, target_id, interaction.user.id, "UNBAN", motivo)
        e = emb("🔓 Banimento revogado", f"**Caso:** `#{case_id}`\n**Alvo:** <@{target_id}> (`{target_id}`)\n**Moderador:** {interaction.user.mention}\n**Motivo:** {motivo}")
        await interaction.followup.send(embed=e)
        await mod_log(interaction.guild, e)

    @app_commands.command(name="timeout", description="Silencia um membro.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def timeout_cmd(self, interaction: discord.Interaction, membro: discord.Member, minutos: app_commands.Range[int, 1, 40320], motivo: str = "Sem motivo"):
        if err := check_target(interaction, membro):
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await interaction.response.defer()
        try:
            await membro.timeout(timedelta(minutes=minutos), reason=audit_reason(interaction, motivo))
        except discord.HTTPException:
            return await interaction.followup.send("❌ Falha no timeout.")
        await self._finish(interaction, "🔇 Timeout", membro, motivo, "TIMEOUT", f"\n**Duração:** {minutos} min")

    @app_commands.command(name="unmute", description="Remove o timeout de um membro.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, membro: discord.Member, motivo: str = "Timeout removido pela Staff"):
        if err := check_target(interaction, membro):
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await interaction.response.defer()
        try:
            await membro.timeout(None, reason=audit_reason(interaction, motivo))
        except discord.HTTPException:
            return await interaction.followup.send("❌ Falha ao remover timeout.")
        await self._finish(interaction, "🔊 Timeout removido", membro, motivo, "UNTIMEOUT")

    @app_commands.command(name="aviso_remover", description="Remove uma advertência pelo ID do registro.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def aviso_remover(self, interaction: discord.Interaction, aviso_id: int):
        row = await (await get_db().execute(
            "SELECT user_id, reason FROM warns WHERE id=? AND guild_id=?",
            (aviso_id, interaction.guild_id),
        )).fetchone()
        if not row:
            return await interaction.response.send_message("❌ Advertência não encontrada neste servidor.", ephemeral=True)
        cur = await get_db().execute("DELETE FROM warns WHERE id=? AND guild_id=?", (aviso_id, interaction.guild_id))
        await get_db().commit()
        if cur.rowcount:
            case_id = await add_case(interaction.guild_id, row["user_id"], interaction.user.id, "WARN_REMOVE", f"Aviso #{aviso_id} removido")
            e = emb("🧹 Advertência removida", f"**Aviso:** `#{aviso_id}`\n**Caso:** `#{case_id}`\n**Alvo:** <@{row['user_id']}>\n**Moderador:** {interaction.user.mention}\n**Motivo original:** {row['reason']}")
            await interaction.response.send_message(embed=e, ephemeral=True)
            await mod_log(interaction.guild, e)
        else:
            await interaction.response.send_message("❌ A advertência não pôde ser removida.", ephemeral=True)

    @app_commands.command(name="avisar", description="Registra um aviso.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def avisar(self, interaction: discord.Interaction, membro: discord.Member, motivo: str):
        if err := check_target(interaction, membro):
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await interaction.response.defer()
        gid = interaction.guild_id
        await get_db().execute("INSERT INTO warns(guild_id, user_id, mod_id, reason, ts) VALUES(?,?,?,?,?)", (gid, membro.id, interaction.user.id, motivo[:500], int(time.time())))
        await get_db().commit()
        total_row = await (await get_db().execute("SELECT COUNT(*) c FROM warns WHERE guild_id=? AND user_id=?", (gid, membro.id))).fetchone()
        total = int(total_row["c"]) if total_row else 0
        extra = f"\n**Total de avisos:** {total}"
        if total >= WARN_TIMEOUT_AT:
            try:
                await membro.timeout(timedelta(minutes=60), reason=f"{total} avisos")
                extra += "\n🔇 Timeout automático 60 min."
            except discord.HTTPException:
                pass
        await self._finish(interaction, "⚠️ Aviso", membro, motivo, "WARN", extra)

    @app_commands.command(name="avisos", description="Lista avisos de um membro.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def avisos(self, interaction: discord.Interaction, membro: discord.Member):
        rows = await (await get_db().execute("SELECT * FROM warns WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 10", (interaction.guild_id, membro.id))).fetchall()
        if not rows:
            return await interaction.response.send_message("✅ Nenhum aviso.", ephemeral=True)
        lines = [f"`#{r['id']}` <t:{r['ts']}:d> por <@{r['mod_id']}> — {r['reason']}" for r in rows]
        await interaction.response.send_message(embed=emb(f"⚠️ Avisos de {membro.display_name}", "\n".join(lines)), ephemeral=True)

    @app_commands.command(name="cases", description="Lista casos de moderação de um membro.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def cases(self, interaction: discord.Interaction, membro: discord.Member):
        rows = await (await get_db().execute("SELECT * FROM mod_cases WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 15", (interaction.guild_id, membro.id))).fetchall()
        if not rows:
            return await interaction.response.send_message("Nenhum caso registrado.", ephemeral=True)
        lines = [f"`#{r['id']}` **{r['action']}** <t:{r['ts']}:d> — {r['reason']}" for r in rows]
        await interaction.response.send_message(embed=emb(f"📋 Cases de {membro.display_name}", "\n".join(lines)), ephemeral=True)

    @app_commands.command(name="nuke", description="Recria somente o canal atual; apaga o histórico após confirmação.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def nuke(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("❌ Use em um canal de texto comum.", ephemeral=True)
        embed = emb("💣 CONFIRMAÇÃO DE NUKE", f"Isso vai **recriar apenas {interaction.channel.mention}** e apagar o histórico do canal antigo. Cargos, categorias e outros canais não serão alterados.\n\nConfirme somente se tiver certeza.")
        await interaction.response.send_message(embed=embed, view=NukeConfirmView(interaction.user.id, interaction.channel), ephemeral=True)

    @app_commands.command(name="lockdown", description="Trava ou destrava o canal atual.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def lockdown(self, interaction: discord.Interaction, travar: bool, motivo: str = "Lockdown"):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("❌ Só em canal de texto.", ephemeral=True)
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False if travar else None
        overwrite.send_messages_in_threads = False if travar else None
        overwrite.create_public_threads = False if travar else None
        overwrite.create_private_threads = False if travar else None
        try:
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=motivo)
        except discord.HTTPException:
            return await interaction.response.send_message("❌ Falha ao alterar permissões.", ephemeral=True)
        estado = "🔒 Canal travado" if travar else "🔓 Canal destravado"
        e = emb(estado, f"**Moderador:** {interaction.user.mention}\n**Motivo:** {motivo}")
        await interaction.response.send_message(embed=e)
        await mod_log(interaction.guild, e)

    @app_commands.command(name="slowmode", description="Define o intervalo entre mensagens no canal atual.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, segundos: app_commands.Range[int, 0, 21600]):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("❌ Este comando exige um canal de texto.", ephemeral=True)
        try:
            await interaction.channel.edit(slowmode_delay=segundos, reason=audit_reason(interaction, f"Slowmode ajustado para {segundos}s"))
        except discord.HTTPException as exc:
            return await interaction.response.send_message(f"❌ Não foi possível ajustar o slowmode (HTTP {exc.status}).", ephemeral=True)
        await interaction.response.send_message(f"✅ Slowmode definido para **{segundos} segundo(s)** em {interaction.channel.mention}.")

    @app_commands.command(name="limpar_usuario", description="Apaga mensagens recentes de um membro neste canal.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def limpar_usuario(self, interaction: discord.Interaction, membro: discord.Member, quantidade: app_commands.Range[int, 1, 100]):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("❌ Este comando exige um canal de texto.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            candidates = [message async for message in interaction.channel.history(limit=500) if message.author.id == membro.id]
            selected = candidates[:quantidade]
            recent = [message for message in selected if (discord.utils.utcnow() - message.created_at).days < 14]
            old = [message for message in selected if message not in recent]
            deleted_count = 0
            if len(recent) == 1:
                await recent[0].delete()
                deleted_count += 1
            elif len(recent) > 1:
                await interaction.channel.delete_messages(recent)
                deleted_count += len(recent)
            for message in old:
                await message.delete()
                deleted_count += 1
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"❌ Falha ao limpar mensagens (HTTP {exc.status}).", ephemeral=True)
        await interaction.followup.send(f"🧹 {deleted_count} mensagem(ns) de {membro.mention} removida(s).", ephemeral=True)

    @app_commands.command(name="limpar", description="Apaga mensagens do canal.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    async def limpar(self, interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 100], membro: Optional[discord.Member] = None):
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message("❌ Canal não suportado.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            if membro:
                # purge(limit=N) só examina N mensagens; aqui procuramos até 500
                # e paramos quando já apagamos N mensagens do membro.
                picked = 0

                def _check(m: discord.Message) -> bool:
                    nonlocal picked
                    if m.author.id == membro.id and picked < quantidade:
                        picked += 1
                        return True
                    return False

                deleted = await interaction.channel.purge(limit=500, check=_check)
            else:
                deleted = await interaction.channel.purge(limit=quantidade)
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"❌ Falha ao limpar mensagens (HTTP {exc.status}).", ephemeral=True)
        await interaction.followup.send(f"🧹 `{len(deleted)}` mensagem(ns) apagada(s).", ephemeral=True)
        alvo = f" de {membro.mention}" if membro else ""
        await mod_log(interaction.guild, emb("🧹 Limpeza", f"{interaction.user.mention} apagou `{len(deleted)}` mensagem(ns){alvo} em {interaction.channel.mention}."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderacao(bot))
