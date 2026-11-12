from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import emb, START_TS


class Utilidades(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Status do bot.")
    @app_commands.guild_only()
    async def stats(self, interaction: discord.Interaction):
        e = emb("🩸 Status da Organização")
        e.add_field(name="📡 Latência", value=f"`{round(self.bot.latency * 1000)} ms`")
        e.add_field(name="🌐 Servidores", value=f"`{len(self.bot.guilds)}`")
        e.add_field(name="🕯️ Online desde", value=f"<t:{START_TS}:R>")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="userinfo", description="Informações de um membro.")
    @app_commands.guild_only()
    async def userinfo(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        m = membro or interaction.user
        e = emb(f"👤 {m.display_name}")
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="ID", value=f"`{m.id}`")
        e.add_field(name="Conta criada", value=f"<t:{int(m.created_at.timestamp())}:D>")
        e.add_field(name="Entrou no servidor", value=f"<t:{int(m.joined_at.timestamp())}:D>" if m.joined_at else "—")
        e.add_field(name="Maior cargo", value=m.top_role.mention)
        await interaction.response.send_message(embed=e)


    @commands.command(name="stats")
    @commands.guild_only()
    async def stats_prefix(self, ctx: commands.Context):
        e = emb("🩸 Status da Organização")
        e.add_field(name="📡 Latência", value=f"`{round(self.bot.latency * 1000)} ms`")
        e.add_field(name="🌐 Servidores", value=f"`{len(self.bot.guilds)}`")
        e.add_field(name="🕯️ Online desde", value=f"<t:{START_TS}:R>")
        await ctx.send(embed=e)

    @commands.command(name="userinfo", aliases=["usuario", "membro"])
    @commands.guild_only()
    async def userinfo_prefix(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        member = membro or ctx.author
        e = emb(f"👤 {member.display_name}")
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="ID", value=f"`{member.id}`")
        e.add_field(name="Conta criada", value=f"<t:{int(member.created_at.timestamp())}:D>")
        e.add_field(name="Entrou no servidor", value=f"<t:{int(member.joined_at.timestamp())}:D>" if member.joined_at else "—")
        e.add_field(name="Maior cargo", value=member.top_role.mention)
        await ctx.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utilidades(bot))
