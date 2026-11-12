"""Rolagem de dados estilo RPG/D&D."""
from __future__ import annotations

import random
import re

import discord
from discord import app_commands
from discord.ext import commands

from core import emb

DICE_RE = re.compile(r"^(\d{1,2})d(\d{1,3})([+-]\d{1,4})?$", re.I)


def roll_expr(expr: str) -> tuple[str, int, list[int]]:
    expr = expr.strip().lower().replace(" ", "")
    m = DICE_RE.match(expr)
    if not m:
        raise ValueError("Use o formato NdM+K (ex: 2d6, 1d20+3, 4d8-1).")
    n, faces, mod_s = int(m.group(1)), int(m.group(2)), m.group(3)
    if n < 1 or n > 20:
        raise ValueError("Quantidade de dados: 1 a 20.")
    if faces < 2 or faces > 100:
        raise ValueError("Faces: 2 a 100.")
    rolls = [random.randint(1, faces) for _ in range(n)]
    total = sum(rolls) + (int(mod_s) if mod_s else 0)
    mod_txt = mod_s or ""
    return f"{n}d{faces}{mod_txt}", total, rolls


class RerollView(discord.ui.View):
    def __init__(self, owner_id: int, expr: str):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.expr = expr

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Só quem rolou pode rerrolar.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Rolar novamente", style=discord.ButtonStyle.primary, emoji="🎲")
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        label, total, rolls = roll_expr(self.expr)
        e = emb("🎲 Nova rolagem", f"**{label}** → `{total}`\nDetalhe: {', '.join(map(str, rolls))}")
        await interaction.response.edit_message(embed=e, view=self)


class Dados(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="dados", description="Rola dados no estilo D&D (ex: 2d6, 1d20+3).")
    @app_commands.describe(expressao="Expressão NdM+K")
    @app_commands.guild_only()
    async def dados(self, interaction: discord.Interaction, expressao: str = "1d20"):
        try:
            label, total, rolls = roll_expr(expressao)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        e = emb("🎲 Rolagem", f"**{label}** → `{total}`\nDetalhe: {', '.join(map(str, rolls))}")
        await interaction.response.send_message(embed=e, view=RerollView(interaction.user.id, expressao))


async def setup(bot: commands.Bot):
    await bot.add_cog(Dados(bot))
