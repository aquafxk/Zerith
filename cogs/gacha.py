"""Coleção Hellsing: invocação, inventário paginado, inspeção e duelos sem apostas."""
from __future__ import annotations

import logging
import random
import sqlite3
import time
import unicodedata
from typing import Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from core import (
    ABUSE, ABUSE_ROLL_LIMIT, ABUSE_ROLL_WINDOW, CARDS, RARITY, ROLLS_PER_HOUR,
    TRADE_TIMEOUT, card_embed, emb, economy_log, get_user, get_db, pick_card_image, transaction,
)

ROLL_COST = 150
SELL_RATE = 0.5
DAILY_ROLL_LIMIT = 30
log = logging.getLogger("hellsing.gacha")

CLAIM_PRIORITY = 10
TZ_OFFSET = -3 * 3600
MAX_CARD_LEVEL = 5
CARD_UPGRADE_BONUS = 0.05


def _scaled_stat(base: int, level: int) -> int:
    """Aplica +5% por nível acima do nível inicial, limitado ao Nv. 5."""
    safe_level = max(1, min(int(level or 1), MAX_CARD_LEVEL))
    return int(int(base) * (1 + CARD_UPGRADE_BONUS * (safe_level - 1)) + 0.5)


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def resolve_card(value: str) -> Optional[str]:
    needle = _normalise(value.strip())
    if needle in CARDS:
        return needle
    for key, card in CARDS.items():
        if _normalise(card["name"]) == needle:
            return key
    matches = [key for key, card in CARDS.items() if needle and needle in _normalise(card["name"])]
    return matches[0] if len(matches) == 1 else None


async def try_start_roll(gid: int, uid: int, now: int) -> Tuple[bool, str, int]:
    blocked, burst = ABUSE.hit(gid, uid, "roll", window=ABUSE_ROLL_WINDOW, limit=ABUSE_ROLL_LIMIT)
    if blocked:
        return (
            False,
            f"🛡️ Anti-abuso: muitas invocações em pouco tempo ({burst}/{ABUSE_ROLL_LIMIT} em {int(ABUSE_ROLL_WINDOW)}s). Espere um pouco.",
            0,
        )
    user = await get_user(gid, uid)
    window, used = int(user["roll_window"] or 0), int(user["rolls_used"] or 0)
    if now - window >= 3600:
        window, used = now, 0

    day_start = ((now + TZ_OFFSET) // 86400) * 86400 - TZ_OFFSET
    today = int(user["rolls_today"] or 0) if int(user["roll_day"] or 0) == day_start else 0
    if used >= ROLLS_PER_HOUR:
        return False, f"⏳ Limite de {ROLLS_PER_HOUR} invocações por hora. Renova <t:{window + 3600}:R>.", 0
    if DAILY_ROLL_LIMIT and today >= DAILY_ROLL_LIMIT:
        return False, f"⏳ Limite diário de {DAILY_ROLL_LIMIT} invocações atingido (anti-spam).", 0

    cost = ROLL_COST
    try:
        from core import get_feature
        ev = await get_feature(gid, "weekly_event", {"active": False, "roll_discount": 0, "ends_at": 0})
        if ev.get("active") and int(ev.get("ends_at") or 0) > now:
            disc = max(0, min(90, int(ev.get("roll_discount") or 0)))
            cost = max(10, int(ROLL_COST * (100 - disc) / 100))
    except Exception:
        cost = ROLL_COST

    cur = await get_db().execute(
        "UPDATE users SET souls=souls-?, roll_window=?, rolls_used=?, roll_day=?, rolls_today=? "
        "WHERE guild_id=? AND user_id=? AND souls>=?",
        (cost, window, used + 1, day_start, today + 1, gid, uid, cost),
    )
    await get_db().commit()
    if cur.rowcount != 1:
        return False, f"❌ Saldo insuficiente. Custo atual: `{cost} Souls`; saldo: `{user['souls']}`.", 0
    # ranking semanal
    try:
        week = now // (7 * 86400)
        await get_db().execute(
            "INSERT INTO roll_stats(guild_id, user_id, week, rolls) VALUES(?,?,?,1) "
            "ON CONFLICT(guild_id, user_id, week) DO UPDATE SET rolls = rolls + 1",
            (gid, uid, week),
        )
        await get_db().commit()
    except Exception:
        try:
            await get_db().execute(
                "CREATE TABLE IF NOT EXISTS roll_stats ("
                "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, week INTEGER NOT NULL, "
                "rolls INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, user_id, week))"
            )
            await get_db().commit()
        except Exception:
            pass
    return True, "", ROLLS_PER_HOUR - (used + 1)


async def refund_roll(gid: int, uid: int) -> None:
    await get_db().execute(
        "UPDATE users SET souls=souls+?, rolls_used=MAX(rolls_used-1,0), "
        "rolls_today=MAX(rolls_today-1,0) WHERE guild_id=? AND user_id=?",
        (ROLL_COST, gid, uid),
    )
    await get_db().commit()


def get_random_card_key() -> str:
    rarities = list(RARITY.keys())
    weights = [RARITY[item][1] for item in rarities]
    chosen = random.choices(rarities, weights=weights, k=1)[0]
    pool = [key for key, card in CARDS.items() if card.get("rarity") == chosen]
    return random.choice(pool or list(CARDS))


class ClaimView(discord.ui.View):
    def __init__(self, card_key: str, owner_id: int):
        super().__init__(timeout=60)
        self.card_key = card_key
        self.owner_id = owner_id
        self.created = time.monotonic()
        self.claimed = False
        self.message: Optional[discord.Message] = None

    @discord.ui.button(label="Reivindicar carta", style=discord.ButtonStyle.danger, emoji="🩸")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.claimed:
            return await interaction.response.send_message("Esta carta já foi reivindicada.", ephemeral=True)
        remaining = CLAIM_PRIORITY - (time.monotonic() - self.created)
        if interaction.user.id != self.owner_id and remaining > 0:
            return await interaction.response.send_message(
                f"⏳ O invocador tem prioridade por mais {int(remaining) + 1}s.", ephemeral=True
            )
        if not interaction.guild_id:
            return await interaction.response.send_message("Use esta carta dentro de um servidor.", ephemeral=True)

        # Serializa operações que alteram a coleção e mantém a inserção atômica.
        self.claimed = True
        try:
            await get_user(interaction.guild_id, interaction.user.id)
        except Exception:
            self.claimed = False
            raise
        try:
            async with transaction() as tx:
                await tx.execute(
                    "INSERT INTO cards(guild_id,user_id,card_key,level) VALUES(?,?,?,1)",
                    (interaction.guild_id, interaction.user.id, self.card_key),
                )
        except Exception:
            self.claimed = False
            raise
        button.disabled = True
        button.style = discord.ButtonStyle.secondary
        button.label = f"Obtida por {interaction.user.display_name}"[:80]
        card_message = interaction.message
        if card_message and card_message.embeds:
            updated = card_message.embeds[0]
            updated.set_footer(text=f"{interaction.user.display_name} adicionou a carta à coleção • RANDOM • HELLSING")
            await interaction.response.edit_message(embed=updated, view=self)
        else:
            await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"🎉 {interaction.user.mention} adicionou **{CARDS[self.card_key]['name']}** à coleção!"
        )
        self.stop()

    async def on_timeout(self) -> None:
        if self.claimed or not self.message:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


class InventoryPaginator(discord.ui.View):
    def __init__(self, viewer_id: int, target: discord.abc.User, items: list[tuple[str, int, int]]):
        super().__init__(timeout=180)
        self.viewer_id = viewer_id
        self.target = target
        self.items = items
        self.page = 0
        self.per_page = 4
        self.max_page = max(0, (len(items) - 1) // self.per_page)
        self.message: Optional[discord.Message] = None
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= self.max_page

    def render(self) -> discord.Embed:
        start = self.page * self.per_page
        page_items = self.items[start:start + self.per_page]
        total_value = sum(CARDS[key]["value"] * count for key, count, _level in self.items)
        total_cards = sum(count for _, count, _level in self.items)
        lines = []
        for key, count, level in page_items:
            card = CARDS[key]
            rarity_label = RARITY.get(card["rarity"], ("⭐", 0))[0]
            atk = _scaled_stat(card["atk"], level)
            defense = _scaled_stat(card["def"], level)
            lines.append(
                f"{rarity_label} **{card['name']}** × `{count}` • **Nv. {level}**\n"
                f"└ ⚔️ `{atk}` ATK • 🛡️ `{defense}` DEF • ❤️ `{card['hp']}` HP"
            )
        description = "\n\n".join(lines)
        description += f"\n\n━━━━━━━━━━━━━━━━━━━━\n🃏 **Cartas:** `{total_cards}` • 💎 **Valor de coleção:** `{total_value} Souls`"
        embed = emb(f"🃏 Coleção de {self.target.display_name} • Página {self.page + 1}/{self.max_page + 1}", description)
        embed.set_thumbnail(url=self.target.display_avatar.url)
        first = page_items[0][0] if page_items else None
        if first:
            image = pick_card_image(CARDS[first])
            if image:
                embed.set_image(url=image)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.viewer_id:
            await interaction.response.send_message("Somente quem abriu este inventário pode navegar.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        """Desativa os controles quando a paginação expira."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                # A mensagem pode ter sido apagada ou o token efêmero expirado.
                pass

    @discord.ui.button(label="Anterior", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="Próxima", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.max_page, self.page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.render(), view=self)


class TradeView(discord.ui.View):
    def __init__(self, author_id: int, target_id: int, offer_key: str, want_key: str):
        super().__init__(timeout=TRADE_TIMEOUT)
        self.author_id = author_id
        self.target_id = target_id
        self.offer_key = offer_key
        self.want_key = want_key
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.author_id, self.target_id):
            await interaction.response.send_message("Esta troca não pertence a você.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Aceitar", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id or self.done:
            return await interaction.response.send_message("Somente o membro convidado pode aceitar.", ephemeral=True)
        gid = interaction.guild_id
        try:
            async with transaction() as tx:
                offer = await (await tx.execute(
                    "SELECT id FROM cards WHERE guild_id=? AND user_id=? AND card_key=? ORDER BY level ASC, id ASC LIMIT 1",
                    (gid, self.author_id, self.offer_key),
                )).fetchone()
                want = await (await tx.execute(
                    "SELECT id FROM cards WHERE guild_id=? AND user_id=? AND card_key=? ORDER BY level ASC, id ASC LIMIT 1",
                    (gid, self.target_id, self.want_key),
                )).fetchone()
                if not offer or not want:
                    raise RuntimeError("Uma das cartas não está mais disponível.")
                cur_a = await tx.execute(
                    "UPDATE cards SET user_id=? WHERE id=? AND user_id=?",
                    (self.target_id, offer["id"], self.author_id),
                )
                cur_b = await tx.execute(
                    "UPDATE cards SET user_id=? WHERE id=? AND user_id=?",
                    (self.author_id, want["id"], self.target_id),
                )
                if cur_a.rowcount != 1 or cur_b.rowcount != 1:
                    raise RuntimeError("A carta mudou de proprietário durante a troca.")
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                log.info("Troca cancelada guild=%s %s<->%s: %s", gid, self.author_id, self.target_id, exc)
            else:
                log.exception("Erro na troca de cartas guild=%s %s<->%s", gid, self.author_id, self.target_id)
            self.done = True
            for item in self.children:
                item.disabled = True
            return await interaction.response.edit_message(embed=emb("❌ Troca cancelada", "Não foi possível concluir a troca com segurança."), view=self)
        self.done = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=emb(
                "✅ Troca concluída",
                f"<@{self.author_id}> ⇄ <@{self.target_id}>\n**{CARDS[self.offer_key]['name']}** ↔ **{CARDS[self.want_key]['name']}**",
            ),
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.done:
            return await interaction.response.send_message("Esta proposta já foi encerrada.", ephemeral=True)
        self.done = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=emb("❌ Troca recusada", f"<@{interaction.user.id}> recusou a proposta."), view=self)
        self.stop()


class Gacha(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Migração idempotente: preserva bancos antigos.
        for column, default in (("roll_day", 0), ("rolls_today", 0)):
            try:
                await get_db().execute(f"ALTER TABLE users ADD COLUMN {column} INTEGER NOT NULL DEFAULT {default}")
                await get_db().commit()
            except sqlite3.OperationalError:
                pass
        try:
            await get_db().execute(
                "ALTER TABLE cards ADD COLUMN level INTEGER NOT NULL DEFAULT 1"
            )
            await get_db().commit()
        except sqlite3.OperationalError:
            # Coluna já existe em bancos migrados anteriormente.
            pass
        await get_db().execute(
            "CREATE INDEX IF NOT EXISTS idx_cards_forge "
            "ON cards(guild_id, user_id, card_key, level)"
        )
        await get_db().commit()

    async def _send_roll(self, *, guild_id: int, user_id: int, send):
        ok, error, remaining = await try_start_roll(guild_id, user_id, int(time.time()))
        if not ok:
            return await send(content=error)
        key = get_random_card_key()
        card = CARDS[key]
        embed = card_embed(card, footer_extra=f"Custo: {ROLL_COST} Souls • {remaining} roll(s) restantes nesta hora")
        view = ClaimView(key, user_id)
        try:
            message = await send(embed=embed, view=view)
            view.message = message
        except discord.HTTPException:
            await refund_roll(guild_id, user_id)
            raise

    @app_commands.command(name="roll", description=f"Invoca uma carta (custa {ROLL_COST} Souls).")
    @app_commands.guild_only()
    async def roll(self, interaction: discord.Interaction):
        async def send(**kwargs):
            await interaction.response.send_message(**kwargs)
            return await interaction.original_response()
        await self._send_roll(guild_id=interaction.guild_id, user_id=interaction.user.id, send=send)

    @commands.command(name="roll", aliases=["invocar", "gacha"])
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def roll_prefix(self, ctx: commands.Context):
        async def send(**kwargs):
            return await ctx.send(**kwargs)
        await self._send_roll(guild_id=ctx.guild.id, user_id=ctx.author.id, send=send)

    async def _inventory_view(self, viewer_id: int, target: discord.abc.User, guild_id: int) -> Optional[InventoryPaginator]:
        rows = await (await get_db().execute(
            "SELECT card_key, level, COUNT(*) AS amount FROM cards "
            "WHERE guild_id=? AND user_id=? GROUP BY card_key, level",
            (guild_id, target.id),
        )).fetchall()
        items = [
            (row["card_key"], int(row["amount"]), int(row["level"] or 1))
            for row in rows if row["card_key"] in CARDS
        ]
        if not items:
            return None
        ordered = sorted(items, key=lambda item: (CARDS[item[0]]["value"], item[2]), reverse=True)
        return InventoryPaginator(viewer_id, target, ordered)

    @app_commands.command(name="inventario", description="Exibe sua coleção com paginação.")
    @app_commands.guild_only()
    async def inventario(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        target = membro or interaction.user
        view = await self._inventory_view(interaction.user.id, target, interaction.guild_id)
        if not view:
            return await interaction.response.send_message(f"❌ {target.display_name} ainda não possui cartas. Use `/roll`.", ephemeral=True)
        await interaction.response.send_message(embed=view.render(), view=view)
        view.message = await interaction.original_response()

    @commands.command(name="inventario", aliases=["colecao", "cartas"])
    @commands.guild_only()
    async def inventario_prefix(self, ctx: commands.Context, membro: Optional[discord.Member] = None):
        target = membro or ctx.author
        view = await self._inventory_view(ctx.author.id, target, ctx.guild.id)
        if not view:
            return await ctx.reply(f"❌ {target.display_name} ainda não possui cartas. Use `;roll`.", mention_author=False)
        view.message = await ctx.send(embed=view.render(), view=view)

    @app_commands.command(name="forjar", description="Consome 2 cópias iguais para evoluir uma carta até Nv. 5.")
    @app_commands.describe(carta="Carta que deseja evoluir (exige 2 cópias no mesmo nível)")
    @app_commands.guild_only()
    async def forjar(self, interaction: discord.Interaction, carta: str):
        key = resolve_card(carta)
        if not key:
            return await interaction.response.send_message("❌ Carta não encontrada. Escolha uma opção sugerida.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        gid, uid = interaction.guild_id, interaction.user.id
        async with transaction() as tx:
            pair = await (await tx.execute(
                "SELECT level, COUNT(*) AS amount FROM cards "
                "WHERE guild_id=? AND user_id=? AND card_key=? "
                "GROUP BY level HAVING COUNT(*) >= 2 AND level < ? "
                "ORDER BY level DESC LIMIT 1",
                (gid, uid, key, MAX_CARD_LEVEL),
            )).fetchone()
            if not pair:
                levels = await (await tx.execute(
                    "SELECT level, COUNT(*) AS amount FROM cards "
                    "WHERE guild_id=? AND user_id=? AND card_key=? "
                    "GROUP BY level ORDER BY level DESC",
                    (gid, uid, key),
                )).fetchall()
                if not levels:
                    return await interaction.followup.send("❌ Você não possui essa carta.", ephemeral=True)
                if all(int(row["level"] or 1) >= MAX_CARD_LEVEL for row in levels):
                    return await interaction.followup.send("⭐ Todas as suas cópias dessa carta já atingiram o nível máximo **Nv. 5**.", ephemeral=True)
                return await interaction.followup.send(
                    "❌ Você precisa de **2 cópias da mesma carta no mesmo nível** para forjar. "
                    "Cartas de níveis diferentes não podem ser combinadas.", ephemeral=True
                )

            old_level = int(pair["level"] or 1)
            new_level = old_level + 1
            copies = await (await tx.execute(
                "SELECT id FROM cards WHERE guild_id=? AND user_id=? AND card_key=? AND level=? "
                "ORDER BY id LIMIT 2",
                (gid, uid, key, old_level),
            )).fetchall()
            if len(copies) != 2:
                raise RuntimeError("As cópias necessárias não estão mais disponíveis.")
            ids = (int(copies[0]["id"]), int(copies[1]["id"]))
            removed = await tx.execute(
                "DELETE FROM cards WHERE guild_id=? AND user_id=? AND card_key=? AND level=? AND id IN (?, ?)",
                (gid, uid, key, old_level, *ids),
            )
            if removed.rowcount != 2:
                raise RuntimeError("Não foi possível reservar as duas cópias para a forja.")
            await tx.execute(
                "INSERT INTO cards(guild_id,user_id,card_key,level) VALUES(?,?,?,?)",
                (gid, uid, key, new_level),
            )

        card = CARDS[key]
        old_atk, old_def = _scaled_stat(card["atk"], old_level), _scaled_stat(card["def"], old_level)
        new_atk, new_def = _scaled_stat(card["atk"], new_level), _scaled_stat(card["def"], new_level)
        await interaction.followup.send(
            embed=emb(
                "⚒️ Forja concluída",
                f"**{card['name']}** evoluiu de **Nv. {old_level}** para **Nv. {new_level}**.\n"
                f"Duas cópias Nv. {old_level} foram consumidas e convertidas em uma carta Nv. {new_level}.\n\n"
                f"⚔️ ATK: `{old_atk}` → `{new_atk}`\n"
                f"🛡️ DEF: `{old_def}` → `{new_def}`\n\n"
                f"Bônus atual: **+{(new_level - 1) * 5}%** em ATK e DEF."
            ),
            ephemeral=True,
        )

    @forjar.autocomplete("carta")
    async def forjar_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = await (await get_db().execute(
            "SELECT card_key, level, COUNT(*) AS amount FROM cards "
            "WHERE guild_id=? AND user_id=? GROUP BY card_key, level "
            "HAVING COUNT(*) >= 2 AND level < ? ORDER BY level DESC",
            (interaction.guild_id, interaction.user.id, MAX_CARD_LEVEL),
        )).fetchall()
        needle = _normalise(current)
        choices = []
        seen: set[str] = set()
        for row in rows:
            key = row["card_key"]
            if key in seen or key not in CARDS:
                continue
            if needle and needle not in _normalise(CARDS[key]["name"]):
                continue
            seen.add(key)
            label = f"{CARDS[key]['name']} • Nv. {int(row['level'] or 1)} ×{int(row['amount'])}"
            choices.append(app_commands.Choice(name=label[:100], value=key))
        return choices[:25]

    @app_commands.command(name="carta", description="Inspeciona uma carta do catálogo.")
    @app_commands.describe(nome="Nome do personagem")
    @app_commands.guild_only()
    async def carta(self, interaction: discord.Interaction, nome: str):
        key = resolve_card(nome)
        if not key:
            return await interaction.response.send_message("❌ Carta não encontrada. Escolha uma opção sugerida.", ephemeral=True)
        await interaction.response.send_message(embed=card_embed(CARDS[key]))

    @carta.autocomplete("nome")
    async def carta_autocomplete(self, interaction: discord.Interaction, current: str):
        needle = _normalise(current)
        options = []
        for key, card in CARDS.items():
            if not needle or needle in _normalise(card["name"]):
                options.append(app_commands.Choice(name=card["name"][:100], value=key))
        return options[:25]

    @commands.command(name="carta", aliases=["personagem"])
    @commands.guild_only()
    async def carta_prefix(self, ctx: commands.Context, *, nome: str):
        key = resolve_card(nome)
        if not key:
            return await ctx.reply("❌ Carta não encontrada. Use uma chave como `alucard` ou `seras`.", mention_author=False)
        await ctx.send(embed=card_embed(CARDS[key]))

    @app_commands.command(name="duelo", description="Disputa amistosa de cartas, sem apostas ou transferência de Souls.")
    @app_commands.guild_only()
    async def duelo(self, interaction: discord.Interaction, oponente: discord.Member):
        await self._run_duel(
            guild_id=interaction.guild_id,
            challenger=interaction.user,
            opponent=oponente,
            send=lambda **kwargs: interaction.response.send_message(**kwargs),
            ephemeral_errors=True,
        )

    @commands.command(name="duelo", aliases=["batalha"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def duelo_prefix(self, ctx: commands.Context, oponente: discord.Member):
        await self._run_duel(
            guild_id=ctx.guild.id,
            challenger=ctx.author,
            opponent=oponente,
            send=lambda **kwargs: ctx.send(**kwargs),
            ephemeral_errors=False,
        )

    async def _run_duel(
        self,
        guild_id: int,
        challenger: discord.abc.User,
        opponent: discord.abc.User,
        send,
        *,
        ephemeral_errors: bool,
    ):
        async def error(message: str):
            if ephemeral_errors:
                return await send(content=message, ephemeral=True)
            return await send(content=message)

        if opponent.bot or opponent.id == challenger.id:
            return await error("❌ Escolha outro membro, que não seja um bot.")
        first = await (await get_db().execute(
            "SELECT card_key, level FROM cards WHERE guild_id=? AND user_id=?",
            (guild_id, challenger.id),
        )).fetchall()
        second = await (await get_db().execute(
            "SELECT card_key, level FROM cards WHERE guild_id=? AND user_id=?",
            (guild_id, opponent.id),
        )).fetchall()
        first = [row for row in first if row["card_key"] in CARDS]
        second = [row for row in second if row["card_key"] in CARDS]
        if not first or not second:
            return await error("❌ Os dois participantes precisam ter pelo menos uma carta.")
        selected_a, selected_b = random.choice(first), random.choice(second)
        key_a, key_b = selected_a["card_key"], selected_b["card_key"]
        level_a, level_b = int(selected_a["level"] or 1), int(selected_b["level"] or 1)
        card_a, card_b = CARDS[key_a], CARDS[key_b]
        atk_a, def_a = _scaled_stat(card_a["atk"], level_a), _scaled_stat(card_a["def"], level_a)
        atk_b, def_b = _scaled_stat(card_b["atk"], level_b), _scaled_stat(card_b["def"], level_b)
        score_a = atk_a + def_a + card_a["hp"] // 3 + random.randint(0, 25)
        score_b = atk_b + def_b + card_b["hp"] // 3 + random.randint(0, 25)
        if score_a == score_b:
            result = "🤝 **Empate!** As duas cartas tiveram o mesmo resultado."
            winner = None
        else:
            winner = challenger if score_a > score_b else opponent
            result = f"🏆 **Vencedor:** {winner.mention}"

        embed = emb(
            "🃏 Duelo amistoso de cartas",
            f"{challenger.mention}: **{card_a['name']}** (Nv. {level_a}) — "
            f"⚔️ `{atk_a}` ATK • 🛡️ `{def_a}` DEF • poder `{score_a}`\n"
            f"{opponent.mention}: **{card_b['name']}** (Nv. {level_b}) — "
            f"⚔️ `{atk_b}` ATK • 🛡️ `{def_b}` DEF • poder `{score_b}`\n\n{result}\n\n"
            "-# Disputa recreativa; não envolve apostas nem movimenta Souls.",
        )
        if card_a.get("image"):
            embed.set_thumbnail(url=card_a["image"])
        await send(embed=embed)
        # Estatísticas persistentes por servidor; empate conta como partida para ambos.
        async with transaction() as tx:
            await tx.execute("INSERT OR IGNORE INTO users(guild_id, user_id) VALUES(?, ?)", (guild_id, challenger.id))
            await tx.execute("INSERT OR IGNORE INTO users(guild_id, user_id) VALUES(?, ?)", (guild_id, opponent.id))
            await tx.execute(
                "UPDATE users SET duels_played=duels_played+1, duels_won=duels_won+? WHERE guild_id=? AND user_id=?",
                (1 if winner and winner.id == challenger.id else 0, guild_id, challenger.id),
            )
            await tx.execute(
                "UPDATE users SET duels_played=duels_played+1, duels_won=duels_won+? WHERE guild_id=? AND user_id=?",
                (1 if winner and winner.id == opponent.id else 0, guild_id, opponent.id),
            )

    @app_commands.command(name="vender", description=f"Vende carta por {int(SELL_RATE * 100)}% do valor.")
    @app_commands.describe(carta="Chave ou nome da carta")
    @app_commands.guild_only()
    async def vender(self, interaction: discord.Interaction, carta: str):
        key = resolve_card(carta)
        if not key:
            return await interaction.response.send_message("❌ Carta inválida.", ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        price = int(CARDS[key]["value"] * SELL_RATE)
        async with transaction() as tx:
            row = await (await tx.execute(
                "SELECT id, level FROM cards WHERE guild_id=? AND user_id=? AND card_key=? ORDER BY level ASC, id ASC LIMIT 1",
                (gid, uid, key),
            )).fetchone()
            if not row:
                return await interaction.response.send_message("❌ Você não possui essa carta.", ephemeral=True)
            removed = await tx.execute("DELETE FROM cards WHERE id=? AND user_id=?", (row["id"], uid))
            if removed.rowcount != 1:
                return await interaction.response.send_message(
                    "❌ Essa carta não está mais disponível. Atualize seu inventário e tente novamente.",
                    ephemeral=True,
                )
            await tx.execute("UPDATE users SET souls=souls+? WHERE guild_id=? AND user_id=?", (price, gid, uid))
        await interaction.response.send_message(embed=emb("💱 Venda", f"**{CARDS[key]['name']}** (Nv. {int(row['level'] or 1)}) → `{price} Souls`"))

    @vender.autocomplete("carta")
    async def vender_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = (await (await get_db().execute(
            "SELECT DISTINCT card_key FROM cards WHERE guild_id=? AND user_id=?",
            (interaction.guild_id, interaction.user.id),
        )).fetchall())
        needle = _normalise(current)
        return [
            app_commands.Choice(name=CARDS[row["card_key"]]["name"][:100], value=row["card_key"])
            for row in rows
            if row["card_key"] in CARDS and needle in _normalise(CARDS[row["card_key"]]["name"])
        ][:25]

    @app_commands.command(name="trocar", description="Propõe uma troca de cartas com outro membro.")
    @app_commands.guild_only()
    async def trocar(self, interaction: discord.Interaction, membro: discord.Member, sua_carta: str, carta_dele: str):
        own_key, their_key = resolve_card(sua_carta), resolve_card(carta_dele)
        if membro.bot or membro.id == interaction.user.id or not own_key or not their_key:
            return await interaction.response.send_message("❌ Membro ou carta inválida.", ephemeral=True)
        gid, uid = interaction.guild_id, interaction.user.id
        owns = (await (await get_db().execute("SELECT 1 FROM cards WHERE guild_id=? AND user_id=? AND card_key=? LIMIT 1", (gid, uid, own_key))).fetchone())
        target_owns = (await (await get_db().execute("SELECT 1 FROM cards WHERE guild_id=? AND user_id=? AND card_key=? LIMIT 1", (gid, membro.id, their_key))).fetchone())
        if not owns or not target_owns:
            return await interaction.response.send_message("❌ Uma das pessoas não possui a carta indicada.", ephemeral=True)
        embed = emb(
            "🔄 Proposta de troca",
            f"{interaction.user.mention} oferece **{CARDS[own_key]['name']}**\n"
            f"e pede **{CARDS[their_key]['name']}** de {membro.mention}.",
        )
        view = TradeView(uid, membro.id, own_key, their_key)
        await interaction.response.send_message(content=membro.mention, embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Gacha(bot))
