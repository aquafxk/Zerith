import logging
import random
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import (
    DAILY_CD, WORK_CD, JOBS, emb, get_user, get_db, xp_needed,
    update_user, economy_log, get_feature, transaction,
)

log = logging.getLogger("hellsing.economia")


async def _transferir(gid: int, origem: int, destino: int, quantidade: int) -> bool:
    """Débito e crédito na mesma transação: ou os dois acontecem, ou nenhum."""
    async with transaction() as tx:
        cur = await tx.execute(
            "UPDATE users SET souls=souls-? WHERE guild_id=? AND user_id=? AND souls>=?",
            (quantidade, gid, origem, quantidade),
        )
        if cur.rowcount != 1:
            return False
        await tx.execute(
            "UPDATE users SET souls=souls+? WHERE guild_id=? AND user_id=?",
            (quantidade, gid, destino),
        )
    log.info("Transferência guild=%s %s -> %s: %s Souls", gid, origem, destino, quantidade)
    return True


class Economia(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        try:
            await get_db().execute("ALTER TABLE users ADD COLUMN last_contract INTEGER NOT NULL DEFAULT 0")
            await get_db().commit()
        except Exception:
            pass

    @app_commands.command(name="daily", description="Resgate suas Souls diárias (com bônus de sequência).")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction):
        gid, uid = interaction.guild_id, interaction.user.id
        u = await get_user(gid, uid)
        now = int(time.time())
        wait = DAILY_CD - (now - u["last_daily"])
        if wait > 0:
            return await interaction.response.send_message(f"⏳ Já resgatado. Volte <t:{now + wait}:R>.", ephemeral=True)
        streak = u["streak"] + 1 if 0 < now - u["last_daily"] <= 48 * 3600 else 1
        reward = random.randint(200, 500) + min(streak, 7) * 25
        cur = await get_db().execute(
            "UPDATE users SET souls = souls + ?, streak = ?, last_daily = ? WHERE guild_id = ? AND user_id = ? AND last_daily <= ?",
            (reward, streak, now, gid, uid, now - DAILY_CD),
        )
        await get_db().commit()
        if cur.rowcount != 1:
            return await interaction.response.send_message("⏳ Recompensa já resgatada.", ephemeral=True)
        u = await get_user(gid, uid)
        e = emb("🍷 RECOMPENSA DIÁRIA", f"Você recebeu **{reward} Souls**.\n🔥 Sequência: `{streak} dia(s)`\n💰 Saldo: `{u['souls']} Souls`")
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="work", description="Trabalhe para a Organização Hellsing e ganhe Souls.")
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction):
        gid, uid = interaction.guild_id, interaction.user.id
        u = await get_user(gid, uid)
        now = int(time.time())
        wait = WORK_CD - (now - u["last_work"])
        if wait > 0:
            return await interaction.response.send_message(f"⏳ Descanse. Novo trabalho <t:{now + wait}:R>.", ephemeral=True)
        earned = random.randint(100, 300)
        cur = await get_db().execute(
            "UPDATE users SET souls = souls + ?, last_work = ? WHERE guild_id = ? AND user_id = ? AND last_work <= ?",
            (earned, now, gid, uid, now - WORK_CD),
        )
        await get_db().commit()
        if cur.rowcount != 1:
            return await interaction.response.send_message("⏳ Trabalho já realizado.", ephemeral=True)
        await interaction.response.send_message(embed=emb("⚔️ TRABALHO CONCLUÍDO", f"Você **{random.choice(JOBS)}** e recebeu `{earned} Souls`."))

    @app_commands.command(name="missao", description="Missão da Organização — recompensa em Souls (cooldown 6h).")
    @app_commands.guild_only()
    async def missao(self, interaction: discord.Interaction):
        gid, uid = interaction.guild_id, interaction.user.id
        user = await get_user(gid, uid)
        now = int(time.time())
        last = int(user["last_contract"] or 0) if "last_contract" in user.keys() else 0
        cooldown = 6 * 3600
        if now - last < cooldown:
            return await interaction.response.send_message(f"⏳ Próxima missão <t:{last + cooldown}:R>.", ephemeral=True)
        reward = random.randint(180, 380)
        cur = await get_db().execute(
            "UPDATE users SET souls=souls+?, last_contract=? WHERE guild_id=? AND user_id=? AND last_contract<=?",
            (reward, now, gid, uid, now - cooldown),
        )
        await get_db().commit()
        if cur.rowcount != 1:
            return await interaction.response.send_message("⏳ Missão já resgatada.", ephemeral=True)
        await interaction.response.send_message(embed=emb("📜 MISSÃO CONCLUÍDA", f"Você concluiu uma missão da Organização e recebeu **{reward} Souls**.\nPróxima missão <t:{now + cooldown}:R>"))

    
    @commands.command(name="missao", aliases=["missão", "missao_diaria"])
    @commands.guild_only()
    async def missao_prefix(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await get_user(gid, uid)
        now = int(time.time())
        last = int(user["last_contract"] or 0) if "last_contract" in user.keys() else 0
        cooldown = 6 * 3600
        if now - last < cooldown:
            return await ctx.reply(f"⏳ Próxima missão <t:{last + cooldown}:R>.", mention_author=False)
        reward = random.randint(180, 380)
        cur = await get_db().execute(
            "UPDATE users SET souls=souls+?, last_contract=? WHERE guild_id=? AND user_id=? AND last_contract<=?",
            (reward, now, gid, uid, now - cooldown),
        )
        await get_db().commit()
        if cur.rowcount != 1:
            return await ctx.reply("⏳ Missão já resgatada.", mention_author=False)
        await ctx.send(
            embed=emb(
                "📜 MISSÃO CONCLUÍDA",
                f"Você concluiu uma missão da Organização e recebeu **{reward} Souls**.\n"
                f"Próxima missão <t:{now + cooldown}:R>",
            )
        )

    @app_commands.command(name="saldo", description="Mostra seu saldo de Souls.")
    @app_commands.guild_only()
    async def saldo(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        target = membro or interaction.user
        u = await get_user(interaction.guild_id, target.id)
        await interaction.response.send_message(embed=emb("💰 Saldo", f"{target.mention} possui `{u['souls']} Souls`."))

    @app_commands.command(name="pagar", description="Transfere Souls para outro membro.")
    @app_commands.describe(membro="Quem recebe", quantidade="Quantidade de Souls")
    @app_commands.guild_only()
    async def pagar(self, interaction: discord.Interaction, membro: discord.Member, quantidade: app_commands.Range[int, 1, 1_000_000]):
        gid, uid = interaction.guild_id, interaction.user.id
        if membro.bot or membro.id == uid:
            return await interaction.response.send_message("❌ Destinatário inválido.", ephemeral=True)
        await get_user(gid, uid)
        await get_user(gid, membro.id)
        if not await _transferir(gid, uid, membro.id, quantidade):
            return await interaction.response.send_message("❌ Saldo insuficiente.", ephemeral=True)
        await interaction.response.send_message(embed=emb("🤝 Transferência", f"{interaction.user.mention} enviou `{quantidade} Souls` para {membro.mention}."))

    @app_commands.command(name="perfil", description="Exibe o perfil de um membro.")
    @app_commands.guild_only()
    async def perfil(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        target = membro or interaction.user
        gid = interaction.guild_id
        u = await get_user(gid, target.id)
        cards_row = await (await get_db().execute("SELECT COUNT(*) c FROM cards WHERE guild_id=? AND user_id=?", (gid, target.id))).fetchone()
        cards = int(cards_row["c"]) if cards_row else 0
        need = xp_needed(u["level"])
        filled = min(10, int(10 * u["xp"] / need)) if need else 0
        e = emb(f"🩸 Perfil de {target.display_name}")
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="📜 Nível", value=f"`{u['level']}`")
        e.add_field(name="✨ XP", value=f"`{u['xp']}/{need}`\n{'█' * filled}{'░' * (10 - filled)}")
        e.add_field(name="💰 Souls", value=f"`{u['souls']}`")
        e.add_field(name="🔥 Sequência diária", value=f"`{u['streak']}`")
        e.add_field(name="🃏 Cartas", value=f"`{cards}`")
        e.add_field(name="⚔️ Duelos", value=f"`{int(u['duels_won'] or 0)}/{int(u['duels_played'] or 0)}` vitórias/partidas", inline=False)
        joined = getattr(target, "joined_at", None)
        if joined:
            e.add_field(name="📅 No servidor desde", value=discord.utils.format_dt(joined, style="R"), inline=True)
        created = getattr(target, "created_at", None)
        if created:
            e.add_field(name="🪪 Conta criada", value=discord.utils.format_dt(created, style="R"), inline=True)
        fav = ""
        try:
            fav = (u["fav_card"] if "fav_card" in u.keys() else "") or ""
        except Exception:
            fav = ""
        title = ""
        try:
            title = (u["title"] if "title" in u.keys() else "") or ""
        except Exception:
            title = ""
        if title:
            e.add_field(name="🎖️ Título", value=title[:80], inline=False)
        if fav:
            e.add_field(name="⭐ Carta favorita", value=str(fav)[:80], inline=False)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="rank", description="Ranking do servidor por nível ou Souls.")
    @app_commands.choices(tipo=[app_commands.Choice(name="Nível", value="level"), app_commands.Choice(name="Souls", value="souls")])
    @app_commands.guild_only()
    async def rank(self, interaction: discord.Interaction, tipo: Optional[app_commands.Choice[str]] = None):
        kind = tipo.value if tipo else "level"
        order = "level DESC, xp DESC" if kind == "level" else "souls DESC"
        rows = await (await get_db().execute(f"SELECT * FROM users WHERE guild_id=? ORDER BY {order} LIMIT 10", (interaction.guild_id,))).fetchall()
        if not rows:
            return await interaction.response.send_message("Ninguém no ranking ainda.", ephemeral=True)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(rows):
            pos = medals[i] if i < 3 else f"`{i + 1}.`"
            val = f"Nv. {r['level']}" if kind == "level" else f"{r['souls']} Souls"
            lines.append(f"{pos} <@{r['user_id']}> — **{val}**")
        await interaction.response.send_message(embed=emb(f"🏆 Ranking — {'Nível' if kind == 'level' else 'Souls'}", "\n".join(lines)))


    # Comandos de prefixo equivalentes aos principais comandos de barra.
    @commands.command(name="daily")
    @commands.guild_only()
    async def daily_prefix(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await get_user(gid, uid)
        now = int(time.time())
        wait = DAILY_CD - (now - int(user["last_daily"] or 0))
        if wait > 0:
            return await ctx.reply(f"⏳ Já resgatado. Volte <t:{now + wait}:R>.", mention_author=False)
        streak = user["streak"] + 1 if 0 < now - user["last_daily"] <= 48 * 3600 else 1
        reward = random.randint(200, 500) + min(streak, 7) * 25
        cur = await get_db().execute(
            "UPDATE users SET souls=souls+?, streak=?, last_daily=? WHERE guild_id=? AND user_id=? AND last_daily<=?",
            (reward, streak, now, gid, uid, now - DAILY_CD),
        )
        await get_db().commit()
        if cur.rowcount != 1:
            return await ctx.reply("⏳ Recompensa já resgatada.", mention_author=False)
        updated = await get_user(gid, uid)
        embed = emb("🍷 RECOMPENSA DIÁRIA", f"Você recebeu **{reward} Souls**.\n🔥 Sequência: `{streak}` dia(s)\n💰 Saldo: `{updated['souls']} Souls`")
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="work", aliases=["trabalhar"])
    @commands.guild_only()
    async def work_prefix(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await get_user(gid, uid)
        now = int(time.time())
        wait = WORK_CD - (now - int(user["last_work"] or 0))
        if wait > 0:
            return await ctx.reply(f"⏳ Próximo trabalho <t:{now + wait}:R>.", mention_author=False)
        earned = random.randint(100, 300)
        cur = await get_db().execute("UPDATE users SET souls=souls+?, last_work=? WHERE guild_id=? AND user_id=? AND last_work<=?", (earned, now, gid, uid, now - WORK_CD))
        await get_db().commit()
        if cur.rowcount != 1:
            return await ctx.reply("⏳ Trabalho já realizado.", mention_author=False)
        await ctx.send(embed=emb("⚔️ TRABALHO CONCLUÍDO", f"Você **{random.choice(JOBS)}** e recebeu `{earned} Souls`."))

    @commands.command(name="saldo", aliases=["carteira"])
    @commands.guild_only()
    async def saldo_prefix(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        target = membro or ctx.author
        user = await get_user(ctx.guild.id, target.id)
        await ctx.send(embed=emb("💰 Saldo", f"{target.mention} possui `{user['souls']} Souls`."))

    @commands.command(name="pagar", aliases=["transferir"])
    @commands.guild_only()
    async def pagar_prefix(self, ctx: commands.Context, membro: discord.Member, quantidade: int):
        if membro.bot or membro.id == ctx.author.id or quantidade < 1 or quantidade > 1_000_000:
            return await ctx.reply("❌ Destinatário ou quantidade inválida.", mention_author=False)
        gid, uid = ctx.guild.id, ctx.author.id
        await get_user(gid, uid)
        await get_user(gid, membro.id)
        if not await _transferir(gid, uid, membro.id, quantidade):
            return await ctx.reply("❌ Saldo insuficiente.", mention_author=False)
        await ctx.send(embed=emb("🤝 Transferência", f"{ctx.author.mention} enviou `{quantidade} Souls` para {membro.mention}."))

    @commands.command(name="perfil")
    @commands.guild_only()
    async def perfil_prefix(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        target = membro or ctx.author
        user = await get_user(ctx.guild.id, target.id)
        cards_row = await (await get_db().execute("SELECT COUNT(*) c FROM cards WHERE guild_id=? AND user_id=?", (ctx.guild.id, target.id))).fetchone()
        cards = int(cards_row["c"]) if cards_row else 0
        need = xp_needed(user["level"])
        filled = min(10, int(10 * user["xp"] / need)) if need else 0
        embed = emb(f"🩸 Perfil de {target.display_name}")
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="📜 Nível", value=f"`{user['level']}`")
        embed.add_field(name="✨ XP", value=f"`{user['xp']}/{need}`\n{'█' * filled}{'░' * (10 - filled)}")
        embed.add_field(name="💰 Souls", value=f"`{user['souls']}`")
        embed.add_field(name="🔥 Sequência", value=f"`{user['streak']}`")
        embed.add_field(name="🃏 Cartas", value=f"`{cards}`")
        embed.add_field(name="⚔️ Duelos", value=f"`{int(user['duels_won'] or 0)}/{int(user['duels_played'] or 0)}` vitórias/partidas", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="rank", aliases=["ranking"])
    @commands.guild_only()
    async def rank_prefix(self, ctx: commands.Context, tipo: str = "level"):
        kind = tipo.casefold()
        if kind in ("nivel", "nível"):
            kind = "level"
        if kind not in ("level", "souls"):
            return await ctx.reply("Use `;rank level` ou `;rank souls`.", mention_author=False)
        order = "level DESC, xp DESC" if kind == "level" else "souls DESC"
        rows = await (await get_db().execute(f"SELECT * FROM users WHERE guild_id=? ORDER BY {order} LIMIT 10", (ctx.guild.id,))).fetchall()
        if not rows:
            return await ctx.reply("Ninguém no ranking ainda.", mention_author=False)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for index, row in enumerate(rows):
            position = medals[index] if index < 3 else f"`{index + 1}.`"
            value = f"Nível {row['level']}" if kind == "level" else f"{row['souls']} Souls"
            lines.append(f"{position} <@{row['user_id']}> — **{value}**")
        await ctx.send(embed=emb(f"🏆 Ranking — {'Nível' if kind == 'level' else 'Souls'}", "\n".join(lines)))


    @app_commands.command(name="titulo", description="Define um título curto no seu perfil (máx. 40 chars).")
    @app_commands.guild_only()
    async def titulo_cmd(self, interaction: discord.Interaction, texto: app_commands.Range[str, 1, 40]):
        await update_user(interaction.guild_id, interaction.user.id, title=str(texto))
        await interaction.response.send_message(f"Título definido: **{texto}**", ephemeral=True)

    @app_commands.command(name="carta_favorita", description="Define o nome da carta favorita no perfil.")
    @app_commands.guild_only()
    async def carta_favorita(self, interaction: discord.Interaction, nome: app_commands.Range[str, 1, 60]):
        await update_user(interaction.guild_id, interaction.user.id, fav_card=str(nome))
        await interaction.response.send_message(f"Carta favorita: **{nome}**", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economia(bot))
