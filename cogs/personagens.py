"""Catálogo visual dos personagens do Gacha Hellsing."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import CARDS, card_embed


class CharacterSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=card["name"][:100],
                value=key,
                description=f"{card['rarity']} • {card['value']} Souls"[:100],
                emoji="🩸",
            )
            for key, card in CARDS.items()
        ]
        super().__init__(
            placeholder="Escolha um personagem para visualizar",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        card = CARDS[self.values[0]]
        await interaction.response.edit_message(embed=card_embed(card), view=self.view)


class CharacterCatalogView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.message: discord.Message | None = None
        self.add_item(CharacterSelect())

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Personagens(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _send_catalog(self, send) -> discord.Message:
        first = next(iter(CARDS.values()))
        view = CharacterCatalogView()
        message = await send(embed=card_embed(first, "Catálogo de personagens"), view=view)
        view.message = message
        return message

    @app_commands.command(
        name="personagens",
        description="Abre o catálogo visual com GIFs dos 12 personagens do Gacha.",
    )
    @app_commands.guild_only()
    async def personagens(self, interaction: discord.Interaction) -> None:
        first = next(iter(CARDS.values()))
        view = CharacterCatalogView()
        await interaction.response.send_message(
            embed=card_embed(first, "Catálogo de personagens"),
            view=view,
            ephemeral=False,
        )
        view.message = await interaction.original_response()

    @commands.command(name="personagens", aliases=["catalogo", "cards"])
    @commands.guild_only()
    async def personagens_prefix(self, ctx: commands.Context) -> None:
        await self._send_catalog(ctx.send)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Personagens(bot))
