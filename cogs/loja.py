"""Loja do servidor: itens e cargos comprados com Souls (v3.1.0)."""
from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import emb, fmt_souls, get_db, get_user, send_log, transaction
from cogs.roles import role_problem

log = logging.getLogger("hellsing.loja")

MAX_ITEMS = 50


async def _items(gid: int, *, only_active: bool = True) -> list:
    sql = "SELECT * FROM shop_items WHERE guild_id=?" + (" AND active=1" if only_active else "") + " ORDER BY price ASC, id ASC"
    async with get_db().execute(sql, (gid,)) as c:
        return list(await c.fetchall())


async def _item(gid: int, item_id: int):
    async with get_db().execute(
        "SELECT * FROM shop_items WHERE guild_id=? AND id=? AND active=1", (gid, item_id)
    ) as c:
        return await c.fetchone()


def _item_line(r) -> str:
    stock = "∞" if r["stock"] < 0 else str(r["stock"])
    role = f" · cargo <@&{r['role_id']}>" if r["role_id"] else ""
    desc = f"\n> {r['description']}" if r["description"] else ""
    return f"`#{r['id']}` **{discord.utils.escape_markdown(r['name'])}** — {fmt_souls(r['price'])} · estoque {stock}{role}{desc}"


async def comprar_item(member: discord.Member, item_id: int, qty: int = 1) -> tuple[bool, str]:
    """Compra atômica: débito, estoque e inventário na mesma transação.
    Se o cargo não puder ser entregue, tudo é estornado."""
    guild = member.guild
    item = await _item(guild.id, item_id)
    if item is None:
        return False, "Item não encontrado. Veja os IDs em `/loja ver`."
    role = guild.get_role(item["role_id"]) if item["role_id"] else None
    if item["role_id"]:
        qty = 1
        if role is None:
            return False, "O cargo deste item não existe mais. Avise a staff."
        if role in member.roles:
            return False, f"Você já tem o cargo {role.mention}."
        problem = role_problem(guild, role)
        if problem:
            return False, problem
    total = int(item["price"]) * qty
    await get_user(guild.id, member.id)
    async with transaction() as tx:
        cur = await tx.execute(
            "UPDATE shop_items SET stock=CASE WHEN stock<0 THEN stock ELSE stock-? END "
            "WHERE guild_id=? AND id=? AND active=1 AND (stock<0 OR stock>=?)",
            (qty, guild.id, item_id, qty),
        )
        if cur.rowcount != 1:
            return False, "Estoque esgotado."
        cur = await tx.execute(
            "UPDATE users SET souls=souls-? WHERE guild_id=? AND user_id=? AND souls>=?",
            (total, guild.id, member.id, total),
        )
        if cur.rowcount != 1:
            raise _Insufficient()
        await tx.execute(
            "INSERT INTO user_items(guild_id, user_id, item_id, qty) VALUES(?,?,?,?) "
            "ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET qty=qty+excluded.qty",
            (guild.id, member.id, item_id, qty),
        )
    if role is not None:
        try:
            await member.add_roles(role, reason=f"Compra na loja (item #{item_id})")
        except discord.HTTPException as exc:
            log.warning("Falha ao entregar cargo da loja (guild=%s, item=%s): %s — estornando", guild.id, item_id, exc)
            async with transaction() as tx:
                await tx.execute("UPDATE users SET souls=souls+? WHERE guild_id=? AND user_id=?", (total, guild.id, member.id))
                await tx.execute("UPDATE shop_items SET stock=CASE WHEN stock<0 THEN stock ELSE stock+? END WHERE id=?", (qty, item_id))
                await tx.execute("UPDATE user_items SET qty=qty-? WHERE guild_id=? AND user_id=? AND item_id=?", (qty, guild.id, member.id, item_id))
            return False, "Não consegui entregar o cargo (permissão). Suas Souls foram devolvidas."
    log.info("Compra guild=%s user=%s item=#%s x%s por %s Souls", guild.id, member.id, item_id, qty, total)
    e = emb("🛒 Compra na loja", f"{member.mention} comprou **{item['name']}** x{qty} por {fmt_souls(total)}.")
    e.timestamp = discord.utils.utcnow()
    await send_log(guild, e)
    extra = f"\n🎖️ Cargo {role.mention} entregue." if role else ""
    return True, f"Você comprou **{discord.utils.escape_markdown(item['name'])}** x{qty} por {fmt_souls(total)}.{extra}"


class _Insufficient(Exception):
    pass


class Loja(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    grupo = app_commands.Group(name="loja", description="Loja do servidor (Souls)", guild_only=True)

    async def item_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = await _items(interaction.guild_id)
        cur = current.lower()
        return [
            app_commands.Choice(name=f"#{r['id']} {r['name']} — {r['price']} Souls"[:100], value=r["id"])
            for r in rows
            if cur in r["name"].lower() or cur in str(r["id"])
        ][:25]

    @grupo.command(name="ver", description="Mostra os itens à venda.")
    async def ver(self, interaction: discord.Interaction):
        rows = await _items(interaction.guild_id)
        if not rows:
            return await interaction.response.send_message(
                "A loja está vazia. A staff pode adicionar itens com `/loja adicionar`.", ephemeral=True
            )
        u = await get_user(interaction.guild_id, interaction.user.id)
        e = emb("🛒 Loja do servidor", "\n".join(_item_line(r) for r in rows)[:4000])
        e.add_field(name="Seu saldo", value=fmt_souls(u["souls"]))
        e.add_field(name="Comprar", value="`/loja comprar item:`")
        await interaction.response.send_message(embed=e, allowed_mentions=discord.AllowedMentions.none())

    @grupo.command(name="comprar", description="Compra um item da loja.")
    @app_commands.autocomplete(item=item_autocomplete)
    async def comprar(self, interaction: discord.Interaction, item: int, quantidade: app_commands.Range[int, 1, 100] = 1):
        await interaction.response.defer(thinking=True)
        try:
            ok, msg = await comprar_item(interaction.user, item, quantidade)
        except _Insufficient:
            ok, msg = False, "Saldo insuficiente."
        if ok:
            await interaction.followup.send(embed=emb("🛒 Compra concluída", msg))
        else:
            await interaction.followup.send(embed=emb("❌ Compra não realizada", msg))

    @grupo.command(name="itens", description="Mostra os itens comprados por você ou por um membro.")
    async def itens(self, interaction: discord.Interaction, membro: Optional[discord.Member] = None):
        target = membro or interaction.user
        async with get_db().execute(
            "SELECT ui.qty, si.id, si.name, si.role_id FROM user_items ui JOIN shop_items si ON si.id=ui.item_id "
            "WHERE ui.guild_id=? AND ui.user_id=? AND ui.qty>0 ORDER BY si.name",
            (interaction.guild_id, target.id),
        ) as c:
            rows = await c.fetchall()
        text = "\n".join(f"`#{r['id']}` **{discord.utils.escape_markdown(r['name'])}** x{r['qty']}" for r in rows) or "Nenhum item."
        await interaction.response.send_message(embed=emb(f"🎒 Itens de {target.display_name}", text[:4000]))

    # ------------------------------------------------------------- staff
    @grupo.command(name="adicionar", description="(Staff) Adiciona um item à loja.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(cargo="Opcional: cargo entregue na compra", estoque="Vazio = ilimitado")
    async def adicionar(
        self,
        interaction: discord.Interaction,
        nome: app_commands.Range[str, 2, 60],
        preco: app_commands.Range[int, 1, 100_000_000],
        cargo: Optional[discord.Role] = None,
        estoque: Optional[app_commands.Range[int, 0, 100_000]] = None,
        descricao: Optional[app_commands.Range[str, 1, 200]] = None,
    ):
        if cargo is not None:
            problem = role_problem(interaction.guild, cargo, interaction.user)
            if problem:
                return await interaction.response.send_message(f"❌ {problem}", ephemeral=True)
        if len(await _items(interaction.guild_id)) >= MAX_ITEMS:
            return await interaction.response.send_message(f"❌ Limite de {MAX_ITEMS} itens.", ephemeral=True)
        cur = await get_db().execute(
            "INSERT INTO shop_items(guild_id, name, description, price, role_id, stock) VALUES(?,?,?,?,?,?)",
            (interaction.guild_id, nome.strip(), (descricao or "").strip(), preco, cargo.id if cargo else None, -1 if estoque is None else estoque),
        )
        log.info("Loja: item #%s criado guild=%s por %s (%s, %s Souls)", cur.lastrowid, interaction.guild_id, interaction.user.id, nome, preco)
        await interaction.response.send_message(f"✅ Item `#{cur.lastrowid}` **{nome}** adicionado por {fmt_souls(preco)}.", ephemeral=True)

    @grupo.command(name="editar", description="(Staff) Altera preço, estoque ou descrição de um item.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(item=item_autocomplete)
    @app_commands.describe(estoque="-1 = ilimitado")
    async def editar(
        self,
        interaction: discord.Interaction,
        item: int,
        preco: Optional[app_commands.Range[int, 1, 100_000_000]] = None,
        estoque: Optional[app_commands.Range[int, -1, 100_000]] = None,
        descricao: Optional[app_commands.Range[str, 1, 200]] = None,
    ):
        changes = {k: v for k, v in (("price", preco), ("stock", estoque), ("description", descricao)) if v is not None}
        if not changes:
            return await interaction.response.send_message("Nada para alterar.", ephemeral=True)
        cols = ", ".join(f"{k}=?" for k in changes)
        cur = await get_db().execute(
            f"UPDATE shop_items SET {cols} WHERE guild_id=? AND id=? AND active=1",
            (*changes.values(), interaction.guild_id, item),
        )
        if cur.rowcount != 1:
            return await interaction.response.send_message("❌ Item não encontrado.", ephemeral=True)
        log.info("Loja: item #%s editado guild=%s por %s: %s", item, interaction.guild_id, interaction.user.id, changes)
        await interaction.response.send_message(f"✅ Item `#{item}` atualizado.", ephemeral=True)

    @grupo.command(name="remover", description="(Staff) Remove um item da loja.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(item=item_autocomplete)
    async def remover(self, interaction: discord.Interaction, item: int):
        cur = await get_db().execute(
            "UPDATE shop_items SET active=0 WHERE guild_id=? AND id=? AND active=1", (interaction.guild_id, item)
        )
        if cur.rowcount != 1:
            return await interaction.response.send_message("❌ Item não encontrado.", ephemeral=True)
        log.info("Loja: item #%s removido guild=%s por %s", item, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(f"✅ Item `#{item}` removido da loja (quem comprou mantém).", ephemeral=True)

    # ----------------------------------------------------------- prefixo
    @commands.command(name="loja", aliases=["shop"])
    @commands.guild_only()
    async def loja_prefix(self, ctx: commands.Context):
        rows = await _items(ctx.guild.id)
        text = "\n".join(_item_line(r) for r in rows) or "A loja está vazia."
        await ctx.send(embed=emb("🛒 Loja do servidor", text[:4000] + "\n\nCompre com `;comprar <id>` ou `/loja comprar`."), allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="comprar", aliases=["buy"])
    @commands.guild_only()
    async def comprar_prefix(self, ctx: commands.Context, item: int, quantidade: int = 1):
        quantidade = max(1, min(100, quantidade))
        try:
            ok, msg = await comprar_item(ctx.author, item, quantidade)
        except _Insufficient:
            ok, msg = False, "Saldo insuficiente."
        await ctx.reply(embed=emb("🛒 Compra concluída" if ok else "❌ Compra não realizada", msg), mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Loja(bot))
