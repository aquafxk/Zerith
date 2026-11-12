import asyncio
import html
import io
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

from core import emb, get_config, get_db, log


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Abrir chamado", style=discord.ButtonStyle.danger, emoji="🩸", custom_id="hellsing:ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket(interaction)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Assumir", style=discord.ButtonStyle.primary, emoji="🛡️", custom_id="hellsing:ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await get_config(interaction.guild_id)
        member = interaction.user
        is_staff = member.guild_permissions.manage_channels
        staff_role_id = cfg.get("ticket_staff_role")
        if staff_role_id and any(r.id == staff_role_id for r in member.roles):
            is_staff = True
        if not is_staff:
            return await interaction.response.send_message("❌ Só a Staff pode assumir.", ephemeral=True)
        await interaction.response.send_message(
            embed=emb("🛡️ Chamado assumido", f"{member.mention} está atendendo este chamado.")
        )

    @discord.ui.button(label="Encerrar", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="hellsing:ticket_close_btn")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Reutiliza a lógica do slash via mensagem orientando
        await interaction.response.send_message(
            "Use `/ticket_fechar` para encerrar e gerar a transcrição.", ephemeral=True
        )


class _TicketLockPool:
    """Locks por usuário com contagem de referências para remover chaves órfãs."""

    def __init__(self) -> None:
        self._entries: dict[tuple[int, int], tuple[asyncio.Lock, int]] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def hold(self, key: tuple[int, int]):
        async with self._guard:
            lock, refs = self._entries.get(key, (asyncio.Lock(), 0))
            self._entries[key] = (lock, refs + 1)
        acquired = False
        try:
            await lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                lock.release()
            async with self._guard:
                current = self._entries.get(key)
                if current and current[0] is lock:
                    remaining = current[1] - 1
                    if remaining <= 0 and not lock.locked():
                        self._entries.pop(key, None)
                    else:
                        self._entries[key] = (lock, remaining)


_TICKET_LOCKS = _TicketLockPool()


async def create_ticket(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None:
        return await interaction.response.send_message(
            "❌ Tickets só podem ser abertos dentro de um servidor.", ephemeral=True
        )
    # Responde já: criar canal pode passar dos 3 s que o Discord concede.
    await interaction.response.defer(ephemeral=True, thinking=True)
    # Um lock por usuário evita dois canais com cliques duplos/simultâneos.
    async with _TICKET_LOCKS.hold((guild.id, interaction.user.id)):
        await _create_ticket_locked(interaction, guild)


async def _create_ticket_locked(interaction: discord.Interaction, guild: discord.Guild):
    cfg = await get_config(guild.id)
    # Já tem ticket aberto?
    row = await (await get_db().execute(
        "SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND open=1",
        (guild.id, interaction.user.id),
    )).fetchone()
    if row:
        ch = guild.get_channel(row["channel_id"])
        if ch:
            return await interaction.followup.send(f"Você já tem um chamado: {ch.mention}", ephemeral=True)

    cat = guild.get_channel(cfg["ticket_category"]) if cfg.get("ticket_category") else None
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    staff_role = guild.get_role(cfg["ticket_staff_role"]) if cfg.get("ticket_staff_role") else None
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    try:
        channel = await guild.create_text_channel(
            name=f"chamado-{interaction.user.name}"[:90],
            category=cat if isinstance(cat, discord.CategoryChannel) else None,
            overwrites=overwrites,
            topic=f"Chamado de {interaction.user} ({interaction.user.id})",
            reason="Ticket Hellsing",
        )
    except discord.HTTPException as exc:
        log.warning("Ticket: falha ao criar canal (guild=%s, user=%s, HTTP %s).", guild.id, interaction.user.id, exc.status)
        return await interaction.followup.send("❌ Não consegui criar o canal. Verifique minhas permissões.", ephemeral=True)

    await get_db().execute(
        "INSERT OR REPLACE INTO tickets(channel_id, guild_id, user_id, open, ts) VALUES(?,?,?,1,?)",
        (channel.id, guild.id, interaction.user.id, int(time.time())),
    )
    await get_db().commit()
    log.info("Ticket aberto guild=%s user=%s canal=%s", guild.id, interaction.user.id, channel.id)

    e = emb(
        "🩸 Chamado aberto na Mansão Hellsing",
        f"{interaction.user.mention}, descreva seu assunto.\n"
        f"A equipe responderá em breve.\n\nUse `/ticket_fechar` para encerrar.",
    )
    try:
        await channel.send(content=f"{interaction.user.mention}" + (f" {staff_role.mention}" if staff_role else ""), embed=e, view=TicketControlView())
    except discord.HTTPException:
        log.warning("Ticket: não consegui enviar a mensagem inicial em %s.", channel.id)
    await interaction.followup.send(f"✅ Chamado criado: {channel.mention}", ephemeral=True)

    log_ch = guild.get_channel(cfg["ticket_log"]) if cfg.get("ticket_log") else None
    if log_ch:
        try:
            await log_ch.send(embed=emb("🎫 Ticket aberto", f"**User:** {interaction.user.mention}\n**Canal:** {channel.mention}"))
        except discord.HTTPException:
            pass


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketView())
        self.bot.add_view(TicketControlView())

    @app_commands.command(name="painel_ticket", description="Publica o painel de chamados (staff).")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True)
    @app_commands.guild_only()
    async def painel_ticket(self, interaction: discord.Interaction):
        e = emb(
            "🩸 Mansão Hellsing — Central de Chamados",
            "Precisa de ajuda, deseja reportar algo ou falar com a staff?\n\n"
            "Clique no botão abaixo para abrir um **chamado privado**.\n"
            "Mantenha o respeito — as sombras observam.",
        )
        await interaction.channel.send(embed=e, view=TicketView())
        await interaction.response.send_message("✅ Painel publicado.", ephemeral=True)

    @app_commands.command(name="ticket", description="Abre um chamado privado com a staff.")
    @app_commands.guild_only()
    async def ticket(self, interaction: discord.Interaction):
        await create_ticket(interaction)

    @app_commands.command(name="ticket_fechar", description="Fecha o chamado e salva uma transcrição.")
    @app_commands.guild_only()
    async def ticket_fechar(self, interaction: discord.Interaction):
        row = await (await get_db().execute(
            "SELECT * FROM tickets WHERE channel_id=? AND guild_id=? AND open=1",
            (interaction.channel_id, interaction.guild_id),
        )).fetchone()
        if not row:
            return await interaction.response.send_message("❌ Este canal não é um ticket aberto.", ephemeral=True)

        cfg = await get_config(interaction.guild_id)
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        is_staff = bool(member and member.guild_permissions.manage_channels)
        staff_role_id = cfg.get("ticket_staff_role")
        if member and staff_role_id and any(role.id == staff_role_id for role in member.roles):
            is_staff = True
        if interaction.user.id != row["user_id"] and not is_staff:
            return await interaction.response.send_message("❌ Apenas o autor ou a Staff podem fechar este chamado.", ephemeral=True)

        log_ch = interaction.guild.get_channel(cfg["ticket_log"]) if cfg.get("ticket_log") else None
        if not isinstance(log_ch, discord.TextChannel):
            return await interaction.response.send_message(
                "❌ O canal de auditoria de tickets não está configurado. Configure-o antes de fechar para não perder o histórico.",
                ephemeral=True,
            )

        await interaction.response.defer(thinking=True, ephemeral=True)
        channel = interaction.channel
        opened_at = datetime.fromtimestamp(int(row["ts"]), tz=timezone.utc)
        closed_at = datetime.now(timezone.utc)
        messages = []
        attachment_count = 0
        truncated = False
        total_chars = 0
        max_messages = 5000
        max_html_chars = 7_500_000

        def safe_https(value: str) -> str:
            parsed = urlparse(value or "")
            return value if parsed.scheme == "https" and parsed.netloc else ""

        def fmt_dt(value: datetime) -> str:
            return value.astimezone().strftime("%H:%M %d/%m/%Y %Z")

        transcript_filename = f"ticket-{interaction.channel_id}.html"
        collected_messages: list = []
        try:
            async for msg in channel.history(limit=max_messages + 1, oldest_first=True):
                collected_messages.append(msg)
        except discord.HTTPException as exc:
            log.exception("Falha ao ler historico do ticket")
            return await interaction.followup.send(
                f"❌ Não foi possível ler o histórico: HTTP {exc.status}.",
                ephemeral=True,
            )
        try:
            for msg in collected_messages:
                if len(messages) >= max_messages:
                    truncated = True
                    break
                avatar_url = safe_https(msg.author.display_avatar.url)
                avatar_html = (
                    f'<img class="avatar" src="{html.escape(avatar_url, quote=True)}" alt="Avatar" loading="lazy">'
                    if avatar_url else '<div class="avatar placeholder">?</div>'
                )
                author_name = html.escape(str(msg.author.display_name))
                author_tag = html.escape(str(msg.author))
                timestamp = msg.created_at.astimezone(timezone.utc)
                local_timestamp = fmt_dt(timestamp)
                content = html.escape(msg.clean_content.replace("\x00", ""))
                content = content.replace("\n", "<br>") or '<span class="muted">(sem texto)</span>'
                attachment_html = []
                for attachment in msg.attachments:
                    attachment_count += 1
                    url = safe_https(attachment.url)
                    if not url:
                        attachment_html.append('<div class="attachment">📎 Anexo indisponível (URL não HTTPS)</div>')
                        continue
                    name = html.escape(attachment.filename)
                    mime = (attachment.content_type or "").lower()
                    href = html.escape(url, quote=True)
                    if mime.startswith("image/") and mime in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                        attachment_html.append(
                            f'<a class="image-link" href="{href}" target="_blank" rel="noopener noreferrer">'
                            f'<img class="attachment-image" src="{href}" alt="{name}" loading="lazy"></a>'
                        )
                    else:
                        size = attachment.size
                        size_label = f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024 else f"{size / 1024:.1f} KB"
                        attachment_html.append(
                            f'<a class="attachment" href="{href}" target="_blank" rel="noopener noreferrer">'
                            f'📎 {name} <span class="muted">({size_label})</span></a>'
                        )
                embeds_note = f'<div class="muted">{len(msg.embeds)} embed(s) na mensagem</div>' if msg.embeds else ""
                block = (
                    f'<article class="msg">{avatar_html}<div class="body">'
                    f'<div class="head"><span class="author">{author_name}</span>'
                    f'<span class="tag">{author_tag}</span>'
                    f'<time datetime="{timestamp.isoformat()}">{html.escape(local_timestamp)}</time></div>'
                    f'<div class="content">{content}</div>{"".join(attachment_html)}{embeds_note}'
                    f'</div></article>'
                )
                total_chars += len(block)
                if total_chars > max_html_chars:
                    truncated = True
                    break
                messages.append(block)

            ticket_name = html.escape(channel.name)
            opener = interaction.guild.get_member(int(row["user_id"]))
            opener_name = html.escape(str(opener) if opener else f"ID {row['user_id']}")
            staff_name = html.escape(str(interaction.user))
            truncation_notice = (
                '<div class="notice">A transcrição foi limitada. Nem todas as mensagens foram incluídas.</div>'
                if truncated else ""
            )
            document = f"""<!doctype html>
    <html lang="pt-BR"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: data:; style-src 'unsafe-inline';">
    <title>Transcrição — {ticket_name}</title>
    <style>
    :root{{--bg:#1e1f22;--side:#2b2d31;--chat:#313338;--text:#dbdee1;--muted:#949ba4;--white:#f2f3f5;--accent:#5865f2}}
    *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
    .wrap{{max-width:1100px;margin:28px auto;padding:0 18px}}header{{background:var(--side);border:1px solid #3f4147;border-radius:12px;padding:22px;margin-bottom:18px}}
    h1{{margin:0 0 14px;color:var(--white);font-size:24px}}.meta{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}
    .meta div{{background:#1e1f22;padding:10px 12px;border-radius:8px}}.label{{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
    .notice{{background:#4a3b1c;color:#f0d99a;padding:10px 14px;border-radius:8px;margin:12px 0}}.chat{{background:var(--chat);border-radius:12px;padding:12px 0}}
    .msg{{display:flex;gap:14px;padding:10px 18px}}.msg:hover{{background:#2e3035}}.avatar{{width:40px;height:40px;border-radius:50%;object-fit:cover;flex:0 0 40px}}
    .placeholder{{background:var(--accent);display:grid;place-items:center;color:white;font-weight:700}}.body{{min-width:0;flex:1}}.head{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}}
    .author{{color:var(--white);font-weight:650}}.tag{{color:var(--muted);font-size:12px}}time,.muted{{color:var(--muted);font-size:12px}}.content{{white-space:normal;overflow-wrap:anywhere;margin-top:3px}}
    .attachment{{display:inline-block;margin:8px 8px 0 0;padding:8px 11px;background:var(--side);border:1px solid #42454b;border-radius:8px;color:#c9cdfb;text-decoration:none;overflow-wrap:anywhere}}
    .attachment:hover{{border-color:var(--accent)}}.attachment-image{{display:block;max-width:min(400px,100%);max-height:320px;border-radius:8px;margin-top:8px}}.image-link{{display:inline-block}}footer{{color:var(--muted);font-size:12px;text-align:center;padding:18px}}
    </style></head><body><main class="wrap"><header><h1>🎫 Transcrição — #{ticket_name}</h1>
    <div class="meta"><div><span class="label">Autor</span>{opener_name}</div>
    <div><span class="label">Aberto em (UTC)</span>{opened_at.strftime('%d/%m/%Y %H:%M:%S UTC')}</div>
    <div><span class="label">Aberto em (local)</span>{html.escape(fmt_dt(opened_at))}</div>
    <div><span class="label">Encerrado em (UTC)</span>{closed_at.strftime('%d/%m/%Y %H:%M:%S UTC')}</div>
    <div><span class="label">Encerrado em (local)</span>{html.escape(fmt_dt(closed_at))}</div>
    <div><span class="label">Fechado por</span>{staff_name}</div></div>
    <p>{len(messages)} mensagens · {attachment_count} anexos</p>{truncation_notice}</header>
    <section class="chat">{''.join(messages)}</section>
    <footer>Transcript gerado por Hellsing · {closed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</footer>
    </main></body></html>"""
            payload = document.encode("utf-8")
            if len(payload) > 14_500_000:
                raise ValueError("transcrição HTML excedeu o limite seguro de upload")
        except Exception as exc:
            # Fallback isolado: mesmo se a leitura do histórico falhar, ainda
            # enviamos um TXT com os dados do ticket e a causa do erro.
            log.exception("Falha ao gerar HTML do ticket %s; usando TXT de emergência", interaction.channel_id)
            fallback_lines = [
                f"HISTÓRICO DO TICKET: {channel.name}",
                f"Aberto por: {row['user_id']} | Aberto em: {opened_at.isoformat()}",
                f"Fechado por: {interaction.user} | Encerrado em: {closed_at.isoformat()}",
                f"Falha ao gerar HTML: {type(exc).__name__}: {str(exc)[:300]}",
                "=" * 72,
            ]
            fallback_message_count = 0
            fallback_attachment_count = 0
            fallback_bytes_limit = 14_500_000
            fallback_size = len("\n".join(fallback_lines).encode("utf-8"))
            try:
                for fallback_msg in collected_messages:
                    fallback_body = fallback_msg.clean_content.replace("\x00", "")
                    if fallback_msg.attachments:
                        fallback_attachment_count += len(fallback_msg.attachments)
                        links = ", ".join(a.url for a in fallback_msg.attachments)
                        fallback_body += " | Anexos: " + links
                    line = (
                        f"[{fallback_msg.created_at.isoformat()}] {fallback_msg.author} "
                        f"({fallback_msg.author.id}): {fallback_body}"
                    )
                    # Reserva espaço para o cabeçalho e evita exceder o upload.
                    line_size = len(line.encode("utf-8")) + 1
                    if fallback_size + line_size > fallback_bytes_limit:
                        fallback_lines.append("[Histórico TXT truncado: limite de tamanho atingido]")
                        break
                    fallback_lines.append(line)
                    fallback_size += line_size
                    fallback_message_count += 1
            except Exception as fallback_exc:
                log.exception(
                    "Falha ao coletar histórico TXT do ticket %s", interaction.channel_id
                )
                fallback_lines.append(
                    f"Falha adicional ao coletar mensagens: "
                    f"{type(fallback_exc).__name__}: {str(fallback_exc)[:300]}"
                )
            payload = "\n".join(fallback_lines).encode("utf-8")
            messages = [None] * fallback_message_count
            attachment_count = fallback_attachment_count
            transcript_filename = f"ticket-{interaction.channel_id}-emergencia.txt"
        transcript = discord.File(io.BytesIO(payload), filename=transcript_filename)
        try:
            await log_ch.send(
                embed=emb(
                    "🎫 Ticket finalizado",
                    f"**Ticket:** `#{channel.name}`\n**Autor:** <@{row['user_id']}>\n"
                    f"**Fechado por:** {interaction.user.mention}\n**Mensagens:** {len(messages)}\n"
                    f"**Anexos:** {attachment_count}\n**Transcrição:** `{transcript_filename}`"
                    + ("\n⚠️ Histórico truncado por limite." if truncated else ""),
                ),
                file=transcript,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            return await interaction.followup.send(
                "❌ Não consegui entregar a transcrição no canal de auditoria. O ticket foi mantido aberto para evitar perda do histórico.",
                ephemeral=True,
            )

        await get_db().execute("UPDATE tickets SET open=0 WHERE channel_id=? AND open=1", (interaction.channel_id,))
        await get_db().commit()
        await interaction.followup.send("🔒 Transcrição salva no canal de auditoria. O ticket será removido em 5 segundos.", ephemeral=True)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket fechado por {interaction.user} ({interaction.user.id})")
        except discord.HTTPException:
            pass



async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
