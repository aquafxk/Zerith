import random
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import QUIZ, QUIZ_CD, emb, get_user, get_db


class QuizView(discord.ui.View):
    def __init__(self, owner_id: int, options: list[str], correct_idx: int):
        super().__init__(timeout=30)
        self.owner_id = owner_id
        self.correct_idx = correct_idx
        self.answered = False
        self.options = options
        self.message: Optional[discord.Message] = None
        self.select = discord.ui.Select(
            placeholder="Escolha a resposta correta...",
            options=[discord.SelectOption(label=o[:100], value=str(i)) for i, o in enumerate(options)],
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Este desafio não é seu.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.answered:
            return
        self.answered = True
        self.select.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    embed=emb(
                        "⌛ Tempo esgotado",
                        f"A resposta era: **{self.options[self.correct_idx]}**.",
                    ),
                    view=self,
                )
            except discord.HTTPException:
                pass

    async def on_select(self, interaction: discord.Interaction):
        if self.answered:
            return
        self.answered = True
        self.select.disabled = True
        ok = int(self.select.values[0]) == self.correct_idx
        if ok:
            await get_db().execute(
                "UPDATE users SET souls = souls + 300 WHERE guild_id = ? AND user_id = ?",
                (interaction.guild_id, interaction.user.id),
            )
            await get_db().commit()
            e = emb("🎯 Correto!", "Você ganhou `+300 Souls`.")
        else:
            e = emb("❌ Errado", f"A resposta era: **{self.options[self.correct_idx]}**.")
        await interaction.response.edit_message(embed=e, view=self)
        self.stop()


class Quiz(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="desafio", description="Pergunta sobre Hellsing.")
    @app_commands.guild_only()
    async def desafio(self, interaction: discord.Interaction):
        gid, uid = interaction.guild_id, interaction.user.id
        u = await get_user(gid, uid)
        now = int(time.time())
        wait = QUIZ_CD - (now - u["last_quiz"])
        if wait > 0:
            return await interaction.response.send_message(
                f"⏳ Próximo desafio <t:{now + wait}:R>.", ephemeral=True
            )
        cur = await get_db().execute(
            "UPDATE users SET last_quiz = ? WHERE guild_id = ? AND user_id = ? AND last_quiz <= ?",
            (now, gid, uid, now - QUIZ_CD),
        )
        if cur.rowcount != 1:  # outro /desafio do mesmo usuário chegou primeiro
            return await interaction.response.send_message("⏳ Você já tem um desafio em andamento.", ephemeral=True)
        question, right, wrong = random.choice(QUIZ)
        options = [right, *wrong]
        random.shuffle(options)
        view = QuizView(uid, options, options.index(right))
        await interaction.response.send_message(
            embed=emb("🔮 Desafio das Sombras", f"**{question}**\n\n30 segundos."),
            view=view,
        )
        view.message = await interaction.original_response()


    @commands.command(name="desafio", aliases=["quiz", "pergunta"])
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def desafio_prefix(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await get_user(gid, uid)
        now = int(time.time())
        wait = QUIZ_CD - (now - int(user["last_quiz"] or 0))
        if wait > 0:
            return await ctx.reply(f"⏳ Próximo desafio <t:{now + wait}:R>.", mention_author=False)
        cur = await get_db().execute(
            "UPDATE users SET last_quiz=? WHERE guild_id=? AND user_id=? AND last_quiz<=?",
            (now, gid, uid, now - QUIZ_CD),
        )
        if cur.rowcount != 1:
            return await ctx.reply("⏳ Você já tem um desafio em andamento.", mention_author=False)
        question, right, wrong = random.choice(QUIZ)
        options = [right, *wrong]
        random.shuffle(options)
        view = QuizView(uid, options, options.index(right))
        message = await ctx.send(embed=emb("🔮 Desafio das Sombras", f"**{question}**\n\n30 segundos."), view=view)
        view.message = message


async def setup(bot: commands.Bot):
    await bot.add_cog(Quiz(bot))
