"""Cassino com Souls: moeda, caça-níquel, dados, roleta, blackjack e roubo (v3.1.0).

Todas as apostas são liquidadas com um único UPDATE condicional
(souls = souls - aposta + prêmio WHERE souls >= aposta), então não há saldo
negativo nem aposta dupla com cliques simultâneos.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import (
    ABUSE, ABUSE_BET_LIMIT, ABUSE_BET_WINDOW, ABUSE_BIG_BET,
    emb, economy_log, fmt_souls, get_db, get_feature, get_user, set_feature, transaction,
)

log = logging.getLogger("hellsing.cassino")

FEATURE = "casino"
DEFAULTS = {"enabled": True, "max_bet": 50_000, "rob": True}
MIN_BET = 10
BET_COOLDOWN = 3.0
BIG_WIN = 10_000
ROB_CD = 2 * 3600
ROB_MIN_BALANCE = 200

SLOTS = [("🍒", 30, 3), ("🍋", 25, 5), ("🍇", 20, 8), ("🔔", 13, 15), ("💎", 8, 30), ("🦇", 4, 75)]
SLOT_PAIR = 1.3  # retorno esperado ≈ 92%
RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


class BetError(Exception):
    pass


class Cassino(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_bet: dict[tuple[int, int], float] = {}
        self._bj_active: set[tuple[int, int]] = set()

    grupo = app_commands.Group(name="cassino", description="Jogos de aposta com Souls", guild_only=True)

    # ------------------------------------------------------------ núcleo
    async def _validate(self, gid: int, uid: int, bet: int) -> None:
        cfg = await get_feature(gid, FEATURE, DEFAULTS)
        if not cfg["enabled"]:
            raise BetError("O cassino está desativado neste servidor.")
        blocked, burst = ABUSE.hit(gid, uid, "bet", window=ABUSE_BET_WINDOW, limit=ABUSE_BET_LIMIT)
        if blocked:
            raise BetError(
                f"Anti-abuso: muitas apostas em pouco tempo ({burst}/{ABUSE_BET_LIMIT} "
                f"em {int(ABUSE_BET_WINDOW)}s). Aguarde."
            )
        if bet < MIN_BET:
            raise BetError(f"Aposta mínima: {fmt_souls(MIN_BET)}.")
        if bet > int(cfg["max_bet"]):
            raise BetError(f"Aposta máxima: {fmt_souls(cfg['max_bet'])}.")
        now = time.monotonic()
        key = (gid, uid)
        if now - self._last_bet.get(key, 0) < BET_COOLDOWN:
            raise BetError("Calma — aguarde alguns segundos entre as apostas.")
        self._last_bet[key] = now
        if len(self._last_bet) > 5000:
            self._last_bet = {k: v for k, v in self._last_bet.items() if now - v < 60}
        await get_user(gid, uid)

    @staticmethod
    async def _settle(gid: int, uid: int, bet: int, payout: int, game: str) -> int:
        """Debita a aposta e credita o prêmio de uma vez. Retorna o novo saldo."""
        async with transaction() as tx:
            cur = await tx.execute(
                "UPDATE users SET souls=souls-?+? WHERE guild_id=? AND user_id=? AND souls>=?",
                (bet, payout, gid, uid, bet),
            )
            if cur.rowcount != 1:
                raise BetError("Saldo insuficiente para essa aposta.")
            async with tx.execute("SELECT souls FROM users WHERE guild_id=? AND user_id=?", (gid, uid)) as c:
                balance = (await c.fetchone())["souls"]
        net = payout - bet
        (log.warning if net >= BIG_WIN else log.info)(
            "Cassino %s guild=%s user=%s aposta=%s prêmio=%s líquido=%+d saldo=%s", game, gid, uid, bet, payout, net, balance
        )
        return int(balance)

    async def _maybe_audit(self, gid: int, uid: int, bet: int, payout: int, game: str) -> None:
        """Loga no canal de moderação apostas grandes ou vitórias/derrotas altas (API Discord)."""
        net = payout - bet
        if bet < ABUSE_BIG_BET and abs(net) < ABUSE_BIG_BET:
            return
        guild = self.bot.get_guild(gid)
        if guild is None:
            return
        user = guild.get_member(uid)
        flag = "vitória alta" if net >= ABUSE_BIG_BET else ("derrota alta" if net <= -ABUSE_BIG_BET else "aposta alta")
        try:
            await economy_log(
                guild,
                title=f"🎰 Cassino — {flag}",
                description=(
                    f"<@{uid}> · jogo `{game}`\n"
                    f"Aposta: **{fmt_souls(bet)}** · Prêmio: **{fmt_souls(payout)}** · Líquido: **{net:+d}**"
                ),
                user=user,
            )
        except Exception:
            log.debug("economy_log cassino falhou", exc_info=True)

    @staticmethod
    def _result_embed(title: str, body: str, bet: int, payout: int, balance: int) -> discord.Embed:
        net = payout - bet
        e = emb(title, body)
        e.color = 0x2ECC71 if net > 0 else (0x95A5A6 if net == 0 else 0xE74C3C)
        e.add_field(name="Resultado", value=(f"+{fmt_souls(net)}" if net > 0 else ("Empate" if net == 0 else f"-{fmt_souls(-net)}")))
        e.add_field(name="Saldo", value=fmt_souls(balance))
        return e

    # ------------------------------------------------------------ jogos
    async def play_moeda(self, gid: int, uid: int, bet: int, side: str) -> discord.Embed:
        await self._validate(gid, uid, bet)
        result = random.choice(("cara", "coroa"))
        payout = int(bet * 1.9) if result == side else 0
        balance = await self._settle(gid, uid, bet, payout, "moeda")
        await self._maybe_audit(gid, uid, bet, payout, "moeda")
        return self._result_embed("🪙 Cara ou coroa", f"Você escolheu **{side}** · deu **{result}**.", bet, payout, balance)

    async def play_slots(self, gid: int, uid: int, bet: int) -> discord.Embed:
        await self._validate(gid, uid, bet)
        symbols = [s for s, _, _ in SLOTS]
        weights = [w for _, w, _ in SLOTS]
        reel = random.choices(symbols, weights=weights, k=3)
        mult = 0.0
        if reel[0] == reel[1] == reel[2]:
            mult = next(m for s, _, m in SLOTS if s == reel[0])
        elif len(set(reel)) == 2:
            mult = SLOT_PAIR
        payout = int(bet * mult)
        balance = await self._settle(gid, uid, bet, payout, "slots")
        await self._maybe_audit(gid, uid, bet, payout, "slots")
        tabela = " · ".join(f"{s}x3 = {m}x" for s, _, m in SLOTS)
        body = f"## ┃ {' ┃ '.join(reel)} ┃\n" + (f"**{mult:g}x!**" if mult else "Nada desta vez.") + f"\n-# Par = {SLOT_PAIR}x · {tabela}"
        return self._result_embed("🎰 Caça-níquel", body, bet, payout, balance)

    async def play_dados(self, gid: int, uid: int, bet: int, number: int) -> discord.Embed:
        await self._validate(gid, uid, bet)
        rolled = random.randint(1, 6)
        payout = int(bet * 5.5) if rolled == number else 0
        balance = await self._settle(gid, uid, bet, payout, "dados")
        await self._maybe_audit(gid, uid, bet, payout, "dados")
        return self._result_embed("🎲 Dados", f"Você apostou no **{number}** · saiu **{rolled}**. (acerto paga 5,5x)", bet, payout, balance)

    async def play_roleta(self, gid: int, uid: int, bet: int, choice: str, number: Optional[int]) -> discord.Embed:
        await self._validate(gid, uid, bet)
        n = random.randint(0, 36)
        color = "verde" if n == 0 else ("vermelho" if n in RED else "preto")
        if choice == "numero":
            if number is None:
                raise BetError("Informe o número (0 a 36).")
            win, mult, label = n == number, 36, f"número {number}"
        elif choice in ("vermelho", "preto"):
            win, mult, label = color == choice, 2, choice
        else:  # par / impar
            win, mult, label = n != 0 and (n % 2 == 0) == (choice == "par"), 2, choice
        payout = bet * mult if win else 0
        balance = await self._settle(gid, uid, bet, payout, "roleta")
        await self._maybe_audit(gid, uid, bet, payout, "roleta")
        dot = {"verde": "🟢", "vermelho": "🔴", "preto": "⚫"}[color]
        return self._result_embed("🎡 Roleta", f"Aposta: **{label}** · caiu {dot} **{n}** ({color}).", bet, payout, balance)

    # --------------------------------------------------------- comandos
    async def _run(self, interaction: discord.Interaction, coro):
        try:
            e = await coro
        except BetError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e)

    @grupo.command(name="moeda", description="Cara ou coroa (acerto paga 1,9x).")
    async def moeda(self, interaction: discord.Interaction, aposta: int, lado: Literal["cara", "coroa"]):
        await self._run(interaction, self.play_moeda(interaction.guild_id, interaction.user.id, aposta, lado))

    @grupo.command(name="slots", description="Caça-níquel (até 75x).")
    async def slots(self, interaction: discord.Interaction, aposta: int):
        await self._run(interaction, self.play_slots(interaction.guild_id, interaction.user.id, aposta))

    @grupo.command(name="dados", description="Aposte em um número de 1 a 6 (acerto paga 5,5x).")
    async def dados(self, interaction: discord.Interaction, aposta: int, numero: app_commands.Range[int, 1, 6]):
        await self._run(interaction, self.play_dados(interaction.guild_id, interaction.user.id, aposta, numero))

    @grupo.command(name="roleta", description="Roleta europeia: cor/par/ímpar paga 2x, número paga 36x.")
    async def roleta(
        self,
        interaction: discord.Interaction,
        aposta: int,
        escolha: Literal["vermelho", "preto", "par", "impar", "numero"],
        numero: Optional[app_commands.Range[int, 0, 36]] = None,
    ):
        await self._run(interaction, self.play_roleta(interaction.guild_id, interaction.user.id, aposta, escolha, numero))

    @grupo.command(name="blackjack", description="Blackjack contra a banca (paga 2x, blackjack 2,5x).")
    async def blackjack(self, interaction: discord.Interaction, aposta: int):
        gid, uid = interaction.guild_id, interaction.user.id
        if (gid, uid) in self._bj_active:
            return await interaction.response.send_message("❌ Termine sua partida de blackjack atual primeiro.", ephemeral=True)
        try:
            await self._validate(gid, uid, aposta)
            async with transaction() as tx:
                cur = await tx.execute(
                    "UPDATE users SET souls=souls-? WHERE guild_id=? AND user_id=? AND souls>=?", (aposta, gid, uid, aposta)
                )
                if cur.rowcount != 1:
                    raise BetError("Saldo insuficiente para essa aposta.")
        except BetError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        self._bj_active.add((gid, uid))
        view = BlackjackView(self, interaction.user, aposta)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        if view.is_blackjack(view.player):
            await view.finish(None)

    @grupo.command(name="roubar", description="Tenta roubar Souls de alguém (cooldown 2h, pode dar errado).")
    async def roubar(self, interaction: discord.Interaction, membro: discord.Member):
        try:
            e = await self.rob(interaction.guild, interaction.user, membro)
        except BetError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(embed=e, allowed_mentions=discord.AllowedMentions(users=[membro]))

    @grupo.command(name="config", description="(Staff) Liga/desliga o cassino, aposta máxima e roubo.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config(
        self,
        interaction: discord.Interaction,
        ativo: Optional[bool] = None,
        aposta_maxima: Optional[app_commands.Range[int, MIN_BET, 100_000_000]] = None,
        roubo: Optional[bool] = None,
    ):
        changes = {k: v for k, v in (("enabled", ativo), ("max_bet", aposta_maxima), ("rob", roubo)) if v is not None}
        cfg = await set_feature(interaction.guild_id, FEATURE, **changes) if changes else await get_feature(interaction.guild_id, FEATURE, DEFAULTS)
        cfg = {**DEFAULTS, **cfg}
        if changes:
            log.info("Cassino config guild=%s por %s: %s", interaction.guild_id, interaction.user.id, changes)
        await interaction.response.send_message(
            f"🎰 Cassino: **{'on' if cfg['enabled'] else 'off'}** · aposta máxima {fmt_souls(cfg['max_bet'])} · roubo **{'on' if cfg['rob'] else 'off'}**",
            ephemeral=True,
        )

    # ------------------------------------------------------------- roubo
    async def rob(self, guild: discord.Guild, thief: discord.Member, target: discord.Member) -> discord.Embed:
        cfg = await get_feature(guild.id, FEATURE, DEFAULTS)
        if not cfg["enabled"] or not cfg["rob"]:
            raise BetError("O roubo está desativado neste servidor.")
        if target.bot or target.id == thief.id:
            raise BetError("Escolha outro membro.")
        gid, now = guild.id, int(time.time())
        await get_user(gid, thief.id)
        await get_user(gid, target.id)
        async with transaction() as tx:
            async with tx.execute(
                "SELECT user_id, souls, last_rob FROM users WHERE guild_id=? AND user_id IN (?, ?)", (gid, thief.id, target.id)
            ) as c:
                rows = {r["user_id"]: r for r in await c.fetchall()}
            me, victim = rows[thief.id], rows[target.id]
            wait = ROB_CD - (now - int(me["last_rob"] or 0))
            if wait > 0:
                raise BetError(f"Você pode tentar de novo <t:{now + wait}:R>.")
            if me["souls"] < ROB_MIN_BALANCE:
                raise BetError(f"Você precisa de pelo menos {fmt_souls(ROB_MIN_BALANCE)} para arriscar um roubo.")
            if victim["souls"] < ROB_MIN_BALANCE:
                raise BetError(f"{target.display_name} não tem Souls suficientes para valer a pena.")
            await tx.execute("UPDATE users SET last_rob=? WHERE guild_id=? AND user_id=?", (now, gid, thief.id))
            if random.random() < 0.4:
                amount = min(5000, max(1, int(victim["souls"] * random.uniform(0.10, 0.25))))
                await tx.execute("UPDATE users SET souls=souls-? WHERE guild_id=? AND user_id=?", (amount, gid, target.id))
                await tx.execute("UPDATE users SET souls=souls+? WHERE guild_id=? AND user_id=?", (amount, gid, thief.id))
                ok = True
            else:
                amount = min(3000, max(1, int(me["souls"] * random.uniform(0.10, 0.20))))
                await tx.execute("UPDATE users SET souls=souls-? WHERE guild_id=? AND user_id=?", (amount, gid, thief.id))
                await tx.execute("UPDATE users SET souls=souls+? WHERE guild_id=? AND user_id=?", (amount, gid, target.id))
                ok = False
        log.info("Roubo guild=%s %s -> %s %s %s Souls", gid, thief.id, target.id, "sucesso" if ok else "falhou", amount)
        if ok:
            e = emb("🦹 Roubo bem-sucedido", f"{thief.mention} roubou **{fmt_souls(amount)}** de {target.mention}.")
            e.color = 0x2ECC71
        else:
            e = emb("🚓 Pego no flagra", f"{thief.mention} tentou roubar {target.mention} e pagou **{fmt_souls(amount)}** de multa para a vítima.")
            e.color = 0xE74C3C
        return e

    # ----------------------------------------------------------- prefixo
    async def _prefix(self, ctx: commands.Context, coro):
        try:
            e = await coro
        except BetError as exc:
            return await ctx.reply(f"❌ {exc}", mention_author=False)
        e.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        await ctx.reply(embed=e, mention_author=False)

    @commands.command(name="moeda", aliases=["coinflip", "cf"])
    @commands.guild_only()
    async def moeda_prefix(self, ctx: commands.Context, aposta: int, lado: str = "cara"):
        lado = lado.lower()
        if lado not in ("cara", "coroa"):
            return await ctx.reply("Use `;moeda <aposta> cara|coroa`.", mention_author=False)
        await self._prefix(ctx, self.play_moeda(ctx.guild.id, ctx.author.id, aposta, lado))

    @commands.command(name="slots", aliases=["cacaniquel"])
    @commands.guild_only()
    async def slots_prefix(self, ctx: commands.Context, aposta: int):
        await self._prefix(ctx, self.play_slots(ctx.guild.id, ctx.author.id, aposta))

    @commands.command(name="roubar", aliases=["rob"])
    @commands.guild_only()
    async def roubar_prefix(self, ctx: commands.Context, membro: discord.Member):
        await self._prefix(ctx, self.rob(ctx.guild, ctx.author, membro))


# ----------------------------------------------------------------- blackjack
def _card() -> tuple[str, int]:
    rank = random.choice(["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"])
    suit = random.choice("♠♥♦♣")
    return f"{rank}{suit}", (11 if rank == "A" else 10 if rank in ("10", "J", "Q", "K") else int(rank))


def _total(hand) -> int:
    total = sum(v for _, v in hand)
    aces = sum(1 for c, _ in hand if c.startswith("A"))
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


class BlackjackView(discord.ui.View):
    def __init__(self, cog: Cassino, player: discord.Member, bet: int):
        super().__init__(timeout=90)
        self.cog, self.user, self.bet = cog, player, bet
        self.player = [_card(), _card()]
        self.dealer = [_card(), _card()]
        self.done = False
        self.message: Optional[discord.Message] = None

    @staticmethod
    def is_blackjack(hand) -> bool:
        return len(hand) == 2 and _total(hand) == 21

    def embed(self, reveal: bool = False, result: str = "") -> discord.Embed:
        def show(hand):
            return " ".join(f"`{c}`" for c, _ in hand)

        dealer = f"{show(self.dealer)} = **{_total(self.dealer)}**" if reveal else f"`{self.dealer[0][0]}` `??`"
        e = emb("🃏 Blackjack", f"**Você:** {show(self.player)} = **{_total(self.player)}**\n**Banca:** {dealer}")
        e.set_author(name=self.user.display_name, icon_url=self.user.display_avatar.url)
        e.add_field(name="Aposta", value=fmt_souls(self.bet))
        if result:
            e.add_field(name="Resultado", value=result, inline=False)
        return e

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("Essa partida não é sua.", ephemeral=True)
            return False
        return not self.done

    async def finish(self, interaction: Optional[discord.Interaction]):
        if self.done:
            return
        self.done = True
        self.stop()
        gid, uid = self.user.guild.id, self.user.id
        p = _total(self.player)
        if p <= 21 and not self.is_blackjack(self.player):
            while _total(self.dealer) < 17:
                self.dealer.append(_card())
        d = _total(self.dealer)
        if p > 21:
            payout, text = 0, "Estourou. A banca venceu."
        elif self.is_blackjack(self.player) and not self.is_blackjack(self.dealer):
            payout, text = int(self.bet * 2.5), "**Blackjack!** Pagamento 2,5x."
        elif d > 21 or p > d:
            payout, text = self.bet * 2, "Você venceu."
        elif p == d:
            payout, text = self.bet, "Empate. Aposta devolvida."
        else:
            payout, text = 0, "A banca venceu."
        balance = None
        try:
            # A aposta já foi debitada no início: aqui só entra o prêmio.
            if payout:
                await self.cog._settle(gid, uid, 0, payout, "blackjack")
            async with get_db().execute("SELECT souls FROM users WHERE guild_id=? AND user_id=?", (gid, uid)) as c:
                balance = (await c.fetchone())["souls"]
            if not payout:
                log.info("Cassino blackjack guild=%s user=%s aposta=%s prêmio=0 líquido=-%s", gid, uid, self.bet, self.bet)
        except Exception:
            log.exception("Falha ao pagar blackjack guild=%s user=%s prêmio=%s", gid, uid, payout)
            text += "\n⚠️ Erro ao creditar o prêmio; avise a staff."
        finally:
            self.cog._bj_active.discard((gid, uid))
        net = payout - self.bet
        text += f"\n{'+' if net >= 0 else '-'}{fmt_souls(abs(net))}" + (f" · saldo {fmt_souls(balance)}" if balance is not None else "")
        for item in self.children:
            item.disabled = True
        e = self.embed(reveal=True, result=text)
        e.color = 0x2ECC71 if net > 0 else (0x95A5A6 if net == 0 else 0xE74C3C)
        try:
            if interaction is not None and not interaction.response.is_done():
                await interaction.response.edit_message(embed=e, view=self)
            elif self.message is not None:
                await self.message.edit(embed=e, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Pedir", style=discord.ButtonStyle.primary, emoji="➕")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.append(_card())
        if _total(self.player) >= 21:
            return await self.finish(interaction)
        self.children[2].disabled = True  # dobrar só na primeira jogada
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Parar", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finish(interaction)

    @discord.ui.button(label="Dobrar", style=discord.ButtonStyle.success, emoji="💰")
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid, uid = self.user.guild.id, self.user.id
        async with transaction() as tx:
            cur = await tx.execute(
                "UPDATE users SET souls=souls-? WHERE guild_id=? AND user_id=? AND souls>=?", (self.bet, gid, uid, self.bet)
            )
            ok = cur.rowcount == 1
        if not ok:
            return await interaction.response.send_message("Saldo insuficiente para dobrar.", ephemeral=True)
        self.bet *= 2
        self.player.append(_card())
        await self.finish(interaction)

    async def on_timeout(self):
        await self.finish(None)  # sem resposta: para automaticamente


async def setup(bot: commands.Bot):
    await bot.add_cog(Cassino(bot))
