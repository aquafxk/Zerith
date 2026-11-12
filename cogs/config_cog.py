from typing import Optional
import json

import discord
from discord import app_commands
from discord.ext import commands

from core import emb, set_config, get_config, get_db


DANGEROUS_ROLE_PERMISSIONS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "ban_members", "kick_members", "moderate_members",
    "mention_everyone", "manage_messages",
)


def validate_assignable_role(guild: discord.Guild, actor: discord.Member, role: discord.Role) -> Optional[str]:
    """Impede autoatribuição de cargos gerenciados, acima do bot ou privilegiados."""
    if role.is_default():
        return "@everyone não pode ser atribuído automaticamente."
    if role.managed:
        return "Esse cargo é gerenciado por uma integração e não pode ser atribuído."
    if guild.me is None or role >= guild.me.top_role:
        return "O cargo do bot precisa estar acima do cargo configurado."
    if actor.id != guild.owner_id and role >= actor.top_role:
        return "Você só pode configurar cargos abaixo do seu cargo mais alto."
    dangerous = [name for name in DANGEROUS_ROLE_PERMISSIONS if getattr(role.permissions, name, False)]
    if dangerous:
        return "Esse cargo possui permissões administrativas e não pode ser concedido automaticamente."
    return None


class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    config = app_commands.Group(name="config", description="Configurações do servidor", guild_only=True, default_permissions=discord.Permissions(manage_guild=True))

    @config.command(name="logs", description="Canal de logs (moderação e eventos do servidor).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logs(self, interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
        await set_config(interaction.guild_id, log_channel=canal.id if canal else None)
        await interaction.response.send_message(f"✅ Logs: {canal.mention if canal else 'off'}.", ephemeral=True)

    @config.command(name="logs_eventos", description="Liga/desliga o registro de eventos (mensagens, membros, cargos, voz) no canal de logs.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logs_eventos(self, interaction: discord.Interaction, ativo: bool):
        await set_config(interaction.guild_id, log_events=int(ativo))
        cfg = await get_config(interaction.guild_id)
        aviso = "" if cfg.get("log_channel") else "\n⚠️ Defina o canal com `/config logs` para os registros aparecerem."
        await interaction.response.send_message(f"✅ Logs de eventos {'on' if ativo else 'off'}.{aviso}", ephemeral=True)

    @config.command(name="antispam", description="Anti-spam automático.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def antispam(self, interaction: discord.Interaction, ativo: bool):
        await set_config(interaction.guild_id, antispam=int(ativo))
        await interaction.response.send_message(f"✅ Anti-spam {'on' if ativo else 'off'}.", ephemeral=True)

    @config.command(name="antilink", description="Bloqueia convites de outros servidores.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def antilink(self, interaction: discord.Interaction, ativo: bool):
        await set_config(interaction.guild_id, antilink=int(ativo))
        await interaction.response.send_message(f"✅ Anti-invite {'on' if ativo else 'off'}.", ephemeral=True)

    @config.command(name="ticket_categoria", description="Categoria dos tickets.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_cat(self, interaction: discord.Interaction, categoria: Optional[discord.CategoryChannel] = None):
        await set_config(interaction.guild_id, ticket_category=categoria.id if categoria else None)
        await interaction.response.send_message(f"✅ Categoria tickets: {categoria.name if categoria else 'off'}.", ephemeral=True)

    @config.command(name="ticket_log", description="Canal de log de tickets.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_log(self, interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
        await set_config(interaction.guild_id, ticket_log=canal.id if canal else None)
        await interaction.response.send_message(f"✅ Log tickets: {canal.mention if canal else 'off'}.", ephemeral=True)

    @config.command(name="ticket_staff", description="Cargo da staff nos tickets.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_staff(self, interaction: discord.Interaction, cargo: Optional[discord.Role] = None):
        await set_config(interaction.guild_id, ticket_staff_role=cargo.id if cargo else None)
        await interaction.response.send_message(f"✅ Staff tickets: {cargo.mention if cargo else 'off'}.", ephemeral=True)

    @config.command(name="cargo_nivel", description="Cargo automático por nível.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def cargo_nivel(self, interaction: discord.Interaction, nivel: app_commands.Range[int, 1, 200], cargo: discord.Role):
        problem = validate_assignable_role(interaction.guild, interaction.user, cargo)
        if problem:
            return await interaction.response.send_message(f"❌ {problem}", ephemeral=True)
        await get_db().execute("INSERT OR REPLACE INTO level_roles(guild_id, level, role_id) VALUES(?,?,?)", (interaction.guild_id, nivel, cargo.id))
        await get_db().commit()
        await interaction.response.send_message(f"✅ Nível {nivel} → {cargo.mention}", ephemeral=True)

    @config.command(name="cargos_nivel", description="Lista cargos por nível.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cargos_nivel(self, interaction: discord.Interaction):
        rows = await (await get_db().execute("SELECT level, role_id FROM level_roles WHERE guild_id=? ORDER BY level", (interaction.guild_id,))).fetchall()
        if not rows:
            return await interaction.response.send_message("Nenhum configurado.", ephemeral=True)
        lines = [f"Nv. **{r['level']}** → <@&{r['role_id']}>" for r in rows]
        await interaction.response.send_message(embed=emb("🏆 Cargos por nível", "\n".join(lines)), ephemeral=True)

    @config.command(name="remover_cargo_nivel", description="Remove cargo de um nível.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remover_cargo_nivel(self, interaction: discord.Interaction, nivel: app_commands.Range[int, 1, 200]):
        cur = await get_db().execute("DELETE FROM level_roles WHERE guild_id=? AND level=?", (interaction.guild_id, nivel))
        await get_db().commit()
        await interaction.response.send_message(f"Removido nível {nivel}." if cur.rowcount else "Nada nesse nível.", ephemeral=True)


    @config.command(name="painel_json", description="Personaliza textos do painel usando JSON.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def painel_json(self, interaction: discord.Interaction, dados: str):
        """Aceita somente textos de páginas conhecidas; não executa código."""
        if len(dados) > 4000:
            return await interaction.response.send_message("❌ JSON muito grande (máximo 4.000 caracteres).", ephemeral=True)
        try:
            payload = json.loads(dados)
        except json.JSONDecodeError as exc:
            return await interaction.response.send_message(f"❌ JSON inválido na posição {exc.pos}.", ephemeral=True)
        allowed = {"inicio", "servidor", "economia", "cassino", "gacha", "acoes", "moderacao", "config", "comunidade", "tickets", "ia", "extras"}
        if not isinstance(payload, dict) or not payload or set(payload) - allowed:
            return await interaction.response.send_message("❌ Envie um objeto JSON com uma ou mais chaves de páginas válidas.", ephemeral=True)
        if any(not isinstance(value, str) or len(value) > 1800 for value in payload.values()):
            return await interaction.response.send_message("❌ Cada texto precisa ser uma string de até 1.800 caracteres.", ephemeral=True)
        current = (await get_config(interaction.guild_id)).get("panel_messages", "{}")
        try:
            merged = json.loads(current) if isinstance(current, str) else {}
        except json.JSONDecodeError:
            merged = {}
        merged.update(payload)
        await set_config(interaction.guild_id, panel_messages=json.dumps(merged, ensure_ascii=False))
        await interaction.response.send_message("✅ Textos do painel salvos. Abra `/menu` novamente para visualizar.", ephemeral=True)

    @config.command(name="painel_json_reset", description="Restaura os textos padrão do painel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def painel_json_reset(self, interaction: discord.Interaction):
        await set_config(interaction.guild_id, panel_messages="{}")
        await interaction.response.send_message("✅ Textos padrão restaurados.", ephemeral=True)

    @config.command(name="regras", description="Canal de regras (citado nas boas-vindas).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def regras(self, interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
        await set_config(interaction.guild_id, rules_channel=canal.id if canal else None)
        await interaction.response.send_message(f"✅ Regras: {canal.mention if canal else 'off'}.", ephemeral=True)

    @config.command(name="curiosidade", description="Canal das curiosidades diárias (manhã).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def curiosidade_ch(self, interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
        await set_config(interaction.guild_id, curiosity_channel=canal.id if canal else None)
        await interaction.response.send_message(f"✅ Curiosidades: {canal.mention if canal else 'off'}.", ephemeral=True)

    @config.command(name="verificacao", description="Cargo concedido pelo botão de verificação.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def verificacao_role(self, interaction: discord.Interaction, cargo: Optional[discord.Role] = None):
        if cargo:
            problem = validate_assignable_role(interaction.guild, interaction.user, cargo)
            if problem:
                return await interaction.response.send_message(f"❌ {problem}", ephemeral=True)
        await set_config(interaction.guild_id, verify_role=cargo.id if cargo else None)
        await interaction.response.send_message(f"✅ Cargo de verificação: {cargo.mention if cargo else 'off'}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
