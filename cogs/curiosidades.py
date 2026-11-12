"""Curiosidades sob demanda e envio matinal."""
from __future__ import annotations

import random
from datetime import time as dtime

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Sao_Paulo")
except Exception:
    from datetime import timezone, timedelta
    TZ = timezone(timedelta(hours=-3))


import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import emb, get_config, log

FACTS = [
    "Alucard é anagrama de Dracula.",
    "A Organização Hellsing foi fundada para combater ameaças sobrenaturais em solo britânico.",
    "Seras Victoria era policial antes de ser transformada.",
    "Alexander Anderson é um agente da Seção XIII Iscariot do Vaticano.",
    "O Major acredita que a guerra é a única forma de arte que vale a pena.",
    "Walter C. Dornez já foi conhecido como o Anjo da Morte.",
    "Pip Bernadotte liderava o grupo mercenário Wild Geese.",
    "Schrödinger existe em todos os lugares e em lugar nenhum ao mesmo tempo.",
    "Integra Hellsing assumiu a liderança da organização ainda jovem.",
    "O Millennium é uma organização remanescente da Segunda Guerra Mundial.",
    "No Discord, bots precisam da intent de membros para detectar entradas.",
    "Cargos de reação não devem ter permissões de Administrador.",
]


class Curiosidades(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


    @commands.Cog.listener()
    async def on_ready(self):
        if not self.morning_curiosity.is_running():
            self.morning_curiosity.start()
    def cog_unload(self):
        self.morning_curiosity.cancel()

    @app_commands.command(name="curiosidade", description="Mostra uma curiosidade aleatória.")
    @app_commands.guild_only()
    async def curiosidade(self, interaction: discord.Interaction):
        fact = random.choice(FACTS)
        await interaction.response.send_message(embed=emb("🩸 Curiosidade", fact))

    @tasks.loop(time=dtime(hour=9, minute=0, tzinfo=TZ))
    async def morning_curiosity(self):
        for guild in self.bot.guilds:
            cfg = await get_config(guild.id)
            ch_id = cfg.get("curiosity_channel")
            if not ch_id:
                continue
            ch = guild.get_channel(ch_id)
            if not ch:
                continue
            try:
                await ch.send(embed=emb("☀️ Curiosidade da manhã", random.choice(FACTS)))
            except discord.HTTPException:
                log.warning("Falha ao enviar curiosidade matinal em %s", guild.id)

    @morning_curiosity.before_loop
    async def before_morning(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Curiosidades(bot))
