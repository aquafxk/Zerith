import asyncio
import json
import random
import re
import time
from collections import deque
from datetime import timedelta

import discord
from discord.ext import commands, tasks

from cogs.ia import build_zerith_system_prompt

from core import (
    XP_CD, SPAM_LIMIT, SPAM_WINDOW, RAID_WINDOW, MENTION_CD,
    emb, get_user, update_user, get_config, grant_xp, spam_log, join_log, get_db, log,
)
from cogs.roles import role_problem


async def apply_level_roles(member: discord.Member, level: int):
    rows = await (await get_db().execute("SELECT role_id FROM level_roles WHERE guild_id=? AND level<=? ORDER BY level", (member.guild.id, level))).fetchall()
    for r in rows:
        role = member.guild.get_role(r["role_id"])
        if not role or role in member.roles:
            continue
        problem = role_problem(member.guild, role)
        if problem:
            log.warning(
                "Cargo automático bloqueado (guild=%s, role=%s): %s",
                member.guild.id,
                role.id,
                problem,
            )
            continue
        try:
            await member.add_roles(role, reason=f"Auto-role nível {level}")
        except discord.HTTPException:
            log.exception("Falha ao atribuir cargo de nível (guild=%s, role=%s).", member.guild.id, role.id)


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_memory_prune = 0.0
        # Histórico curto em RAM isolado por servidor, usuário e canal.
        # O conteúdo das mensagens não é persistido no SQLite.
        self._ai_memory: dict[tuple[int, int, int], tuple[deque, float]] = {}
        self._ai_locks: dict[tuple[int, int, int], asyncio.Lock] = {}
        self._ai_error_until: dict[tuple[int, int, int], float] = {}
        self._voice_reward_locks: dict[tuple[int, int], asyncio.Lock] = {}

    async def cog_unload(self):
        self.voice_rewards.cancel()

    @staticmethod
    def _infer_zerith_style(message: str) -> str:
        """Classifica apenas o tom textual; não tenta inferir identidade ou dados sensíveis."""
        text = message.casefold().strip()
        if not text:
            return "equilibrada"
        if re.search(r"\b(sem brincadeira|falando sério|assunto sério|preciso de ajuda|é urgente)\b", text):
            return "acolhedora"
        if re.search(r"(kkkk+|rsrs+|haha+|😂|🤣|zoeira|brincadeira|meme)", text):
            return "zoeira"
        if re.search(r"\b(por favor|obrigad[oa]|valeu|por gentileza)\b", text):
            return "fofa"
        if text.count("!") >= 2 or re.search(r"(🔥|✨|🎉|!!!)", text):
            return "energetica"
        if re.match(r"^(faz|manda|mostra|resume|resuma|explica|corrige|resolve|implementa)\b", text):
            return "direta"
        return "equilibrada"

    async def _update_zerith_profile(self, guild_id: int, user_id: int, message: str) -> tuple[str, str]:
        """Persiste só contagens de estilo; mensagens e fatos pessoais ficam fora do banco."""
        current_style = self._infer_zerith_style(message)
        db = get_db()
        cursor = await db.execute(
            "SELECT style_scores, interactions FROM ai_user_profiles WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        try:
            scores = json.loads(row["style_scores"]) if row and row["style_scores"] else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            scores = {}
        if not isinstance(scores, dict):
            scores = {}
        clean_scores = {}
        for key, value in scores.items():
            if str(key) not in {"fofa", "zoeira", "energetica", "direta", "acolhedora"}:
                continue
            try:
                clean_scores[str(key)] = max(0, min(int(value), 100))
            except (TypeError, ValueError):
                continue
        scores = clean_scores
        interactions = int(row["interactions"] or 0) if row else 0
        if current_style != "equilibrada":
            scores[current_style] = min(scores.get(current_style, 0) + 1, 100)
            interactions += 1
            await db.execute(
                "INSERT INTO ai_user_profiles (guild_id, user_id, style_scores, interactions, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "style_scores=excluded.style_scores, interactions=excluded.interactions, updated_at=excluded.updated_at",
                (guild_id, user_id, json.dumps(scores, ensure_ascii=False), interactions, int(time.time())),
            )
            await db.commit()
        learned_style = max(scores, key=scores.get) if scores and max(scores.values()) >= 2 else "equilibrada"
        return current_style, learned_style

    @commands.hybrid_command(
        name="zerith_esquecer",
        description="Apaga as preferências de conversa que Zerith aprendeu sobre você.",
    )
    @commands.guild_only()
    async def zerith_esquecer(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return
        await get_db().execute(
            "DELETE FROM ai_user_profiles WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, ctx.author.id),
        )
        await get_db().commit()
        for key in list(self._ai_memory):
            if key[0] == ctx.guild.id and key[1] == ctx.author.id:
                self._ai_memory.pop(key, None)
                self._ai_error_until.pop(key, None)
                lock = self._ai_locks.get(key)
                if lock is None or not lock.locked():
                    self._ai_locks.pop(key, None)
        await ctx.reply(
            "🧠 Preferências aprendidas apagadas. O histórico curto da conversa também foi limpo.",
            mention_author=False,
        )

    def _prune_memory_windows(self) -> None:
        now = time.monotonic()
        if now - self._last_memory_prune < 300:
            return
        for key, window in list(spam_log.items()):
            while window and now - window[0] > max(SPAM_WINDOW * 3, 60):
                window.popleft()
            if not window:
                spam_log.pop(key, None)
        for key, window in list(join_log.items()):
            while window and now - window[0] > max(RAID_WINDOW * 3, 60):
                window.popleft()
            if not window:
                join_log.pop(key, None)
        self._last_memory_prune = now

    @commands.Cog.listener()
    async def on_ready(self):
        # wait_until_ready() só é seguro após o cliente iniciar o login.
        if not self.voice_rewards.is_running():
            self.voice_rewards.start()
        # Registra nomes e IDs para identificar contagem inesperada no cache.
        # Deduplica por ID e registra o snapshot real recebido do gateway.
        guilds_by_id = {guild.id: guild for guild in self.bot.guilds}
        guilds = sorted(guilds_by_id.values(), key=lambda guild: (guild.name.casefold(), guild.id))
        log.info(
            "🩸 %s conectado: %d servidor(es) no cache do Discord.",
            self.bot.user,
            len(guilds),
        )
        for guild in guilds:
            log.info("   • Servidor: %s | ID: %s", guild.name, guild.id)

    @staticmethod
    def _voice_member_is_eligible(member: discord.Member) -> bool:
        """Filtra bots, AFK, auto-mute/deaf e mute/deaf aplicados pelo servidor."""
        state = member.voice
        if member.bot or state is None:
            return False
        return not any((
            state.self_mute, state.self_deaf, state.mute, state.deaf,
            state.suppress,
        ))

    async def _reward_voice_member(self, member: discord.Member) -> tuple[int, int, bool]:
        """Credita uma recompensa por ciclo e aplica progressão/cargos de nível."""
        gid, uid = member.guild.id, member.id
        lock = self._voice_reward_locks.setdefault((gid, uid), asyncio.Lock())
        async with lock:
            xp_gain = random.randint(10, 20)
            souls_gain = random.randint(15, 30)
            # Atômico: não sobrescreve XP ganho por mensagens no mesmo instante.
            old_level, level, _ = await grant_xp(gid, uid, xp_gain, souls=souls_gain)

            leveled = level > old_level
            if leveled:
                await apply_level_roles(member, level)
                channel = member.guild.system_channel
                bot_member = member.guild.me
                if channel and bot_member and channel.permissions_for(bot_member).send_messages:
                    try:
                        await channel.send(
                            embed=emb(
                                "🩸 LEVEL UP — Voz",
                                f"{member.mention} alcançou o **nível {level}** participando de uma chamada!",
                            ),
                            allowed_mentions=discord.AllowedMentions(users=True),
                        )
                    except discord.HTTPException:
                        log.debug("Não foi possível anunciar level up por voz (guild=%s).", gid)
            return xp_gain, souls_gain, leveled

    @tasks.loop(minutes=5)
    async def voice_rewards(self):
        """Recompensa membros em chamadas com pelo menos dois humanos elegíveis."""
        rewarded = skipped = 0
        started = time.monotonic()
        for guild in list(self.bot.guilds):
            try:
                voice_channels = [*guild.voice_channels, *guild.stage_channels]
                for channel in voice_channels:
                    if guild.afk_channel and channel.id == guild.afk_channel.id:
                        continue
                    humans = [m for m in channel.members if not m.bot]
                    # Exige pelo menos duas pessoas humanas no canal; bots não contam.
                    if len(humans) < 2:
                        skipped += len(humans)
                        continue
                    for member in humans:
                        if not self._voice_member_is_eligible(member):
                            skipped += 1
                            continue
                        try:
                            xp_gain, souls_gain, leveled = await self._reward_voice_member(member)
                            rewarded += 1
                            log.debug(
                                "Voice reward guild=%s user=%s xp=+%s souls=+%s level_up=%s",
                                guild.id, member.id, xp_gain, souls_gain, leveled,
                            )
                        except Exception:
                            log.exception(
                                "Falha ao recompensar membro em voz (guild=%s, user=%s).",
                                guild.id, member.id,
                            )
                        await asyncio.sleep(0)
            except Exception:
                log.exception("Falha ao varrer canais de voz (guild=%s).", guild.id)
        elapsed = time.monotonic() - started
        log.debug(
            "Ciclo de recompensas de voz concluído: %s recompensado(s), %s ignorado(s), %.2fs.",
            rewarded, skipped, elapsed,
        )
        if elapsed > 60:
            log.warning("Varredura de recompensas de voz demorou %.2fs.", elapsed)

    @voice_rewards.before_loop
    async def before_voice_rewards(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        # O listener registra transições; a elegibilidade e o crédito ficam
        # centralizados na varredura de 5 minutos para evitar recompensas fracionadas.
        if member.bot:
            return
        if before.channel != after.channel or (before.mute, before.deaf, before.self_mute, before.self_deaf) != (
            after.mute, after.deaf, after.self_mute, after.self_deaf
        ):
            log.debug(
                "Voice state alterado (guild=%s, user=%s, canal=%s->%s).",
                member.guild.id, member.id,
                before.channel.id if before.channel else None,
                after.channel.id if after.channel else None,
            )

    async def _handle_mass_mention(self, message: discord.Message) -> bool:
        """Remove mass mentions, aplica timeout de 1h e registra a evidência."""
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return False

        member = message.author
        permissions = member.guild_permissions
        if permissions.mention_everyone or permissions.manage_messages:
            return False

        # Deduplica explicitamente por ID: repetir a mesma menção não deve
        # contar como vários usuários distintos.
        distinct_mentions = {user.id: user for user in message.mentions}
        mention_count = len(distinct_mentions)
        # Sem permissão, o Discord entrega mention_everyone=False; por isso
        # também verificamos o texto bruto da mensagem.
        used_everyone = bool(
            message.mention_everyone
            or re.search(r"@(everyone|here)\b", message.content or "")
        )
        if mention_count <= 5 and not used_everyone:
            return False

        guild = message.guild
        channel = message.channel
        content = message.content or "[mensagem sem conteúdo textual]"
        author_label = f"{member} (ID: {member.id})"
        mention_names = [
            f"{user} (ID: {user.id})" for user in list(distinct_mentions.values())[:20]
        ]
        attachment_urls = [attachment.url for attachment in message.attachments[:10]]

        reasons = []
        if mention_count > 5:
            reasons.append(f"mais de 5 usuários distintos mencionados ({mention_count})")
        if used_everyone:
            reasons.append("uso de @everyone/@here sem permissão")
        reason_text = " e ".join(reasons)

        # Exclui imediatamente; o conteúdo foi preservado para auditoria.
        deleted = False
        try:
            await message.delete(reason=f"Anti-Mass-Mention: {reason_text}")
            deleted = True
        except discord.NotFound:
            deleted = True  # Já removida por outro moderador/processo.
        except discord.Forbidden:
            log.warning(
                "Anti-Mass-Mention: sem permissão para excluir mensagem "
                "(guild=%s, channel=%s, message=%s).",
                guild.id, channel.id, message.id,
            )
        except discord.HTTPException:
            log.exception(
                "Anti-Mass-Mention: falha ao excluir mensagem (guild=%s, message=%s).",
                guild.id, message.id,
            )

        timeout_result = "Timeout de 1 hora aplicado."
        bot_member = guild.me
        if bot_member is None:
            timeout_result = "Timeout não aplicado: membro do bot indisponível no cache."
        elif member.id == guild.owner_id or member.top_role >= bot_member.top_role:
            timeout_result = "Timeout não aplicado: hierarquia do cargo impede a ação."
        elif not bot_member.guild_permissions.moderate_members:
            timeout_result = "Timeout não aplicado: bot sem permissão de moderar membros."
        else:
            try:
                await member.timeout(
                    discord.utils.utcnow() + timedelta(hours=1),
                    reason=f"Anti-Mass-Mention: {reason_text}",
                )
            except discord.Forbidden:
                timeout_result = "Timeout recusado pelo Discord (permissão ou hierarquia)."
            except discord.HTTPException as exc:
                timeout_result = f"Falha HTTP ao aplicar timeout: {type(exc).__name__}."

        cfg = await get_config(guild.id)
        log_channel_id = cfg.get("log_channel")
        log_channel = guild.get_channel(int(log_channel_id)) if log_channel_id else None
        if log_channel is None:
            log.warning(
                "Anti-Mass-Mention detectado sem canal log_channel configurado/acessível "
                "(guild=%s, user=%s).",
                guild.id, member.id,
            )
            return True

        embed = emb(
            "🚨 Anti-Mass-Mention — Infração detectada",
            "Uma mensagem violou a proteção contra menções em massa.",
        )
        embed.add_field(name="👤 Autor", value=author_label[:1024], inline=False)
        embed.add_field(name="📍 Canal", value=f"{channel.mention} (`{channel.id}`)", inline=True)
        embed.add_field(name="👥 Usuários distintos mencionados", value=str(mention_count), inline=True)
        embed.add_field(name="⚠️ Motivo", value=reason_text[:1024], inline=False)
        safe_content = content.replace("```", "''' ")
        if len(safe_content) > 1000:
            safe_content = safe_content[:1000] + "… [conteúdo truncado]"
        embed.add_field(
            name="🗑️ Conteúdo removido",
            value=safe_content or "[mensagem vazia]",
            inline=False,
        )
        embed.add_field(
            name="🛡️ Ações",
            value=(
                f"Mensagem excluída: {'sim' if deleted else 'não — verifique permissões'}\n"
                f"{timeout_result}"
            )[:1024],
            inline=False,
        )
        if mention_names:
            embed.add_field(
                name="Destinatários",
                value="\n".join(mention_names)[:1024],
                inline=False,
            )
        if attachment_urls:
            embed.add_field(
                name="📎 Anexos",
                value="\n".join(attachment_urls)[:1024],
                inline=False,
            )
        embed.set_footer(text=f"Guild ID: {guild.id} • Message ID: {message.id}")
        try:
            await log_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            log.warning(
                "Anti-Mass-Mention: sem permissão para enviar alerta ao log_channel (guild=%s).",
                guild.id,
            )
        except discord.HTTPException:
            log.exception(
                "Anti-Mass-Mention: falha ao enviar alerta ao log_channel (guild=%s).",
                guild.id,
            )
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return
        # Executa antes dos comandos, XP, IA e demais filtros para bloquear
        # inclusive tentativas de mass mention enviadas como comandos.
        if await self._handle_mass_mention(message):
            return
        automod = self.bot.get_cog("AutoMod")
        if automod is not None and await automod.check_message(message):
            return  # mensagem removida pelo automod: sem XP, IA ou comandos
        self._prune_memory_windows()
        gid, uid = message.guild.id, message.author.id
        cfg = await get_config(gid)
        # O handler do main.py executa process_commands(). Este listener cuida
        # de XP/moderação; detectar o contexto evita premiar mensagens de comando.
        ctx = await self.bot.get_context(message)
        is_command = ctx.valid

        if cfg.get("antilink") and not message.author.guild_permissions.manage_messages:
            c = message.content.lower()
            if "discord.gg/" in c or "discord.com/invite/" in c:
                try:
                    await message.delete()
                    await message.channel.send(f"🚫 {message.author.mention}, convites bloqueados.", delete_after=8)
                except discord.HTTPException:
                    pass
                return

        if cfg.get("antispam") and not message.author.guild_permissions.manage_messages:
            dq = spam_log[(gid, uid)]
            t = time.monotonic()
            dq.append(t)
            if len(dq) >= SPAM_LIMIT and t - dq[-SPAM_LIMIT] <= SPAM_WINDOW:
                dq.clear()
                try:
                    await message.author.timeout(timedelta(minutes=5), reason="Anti-spam")
                    await message.channel.send(f"🚨 {message.author.mention} 5 min (spam).", delete_after=10)
                except discord.HTTPException:
                    pass
                return

        if (
            not is_command
            and self.bot.user
            and self.bot.user.mentioned_in(message)
            and not message.mention_everyone
        ):
            u = await get_user(gid, uid)
            now = int(time.time())
            if now - (u["last_ai"] or 0) >= MENTION_CD:
                content = message.content
                for mentioned in message.mentions:
                    content = content.replace(mentioned.mention, "").replace(
                        f"<@!{mentioned.id}>", ""
                    )
                content = content.strip()
                ia_cog = self.bot.get_cog("IA")
                if content and ia_cog is not None:
                    await update_user(gid, uid, last_ai=now)
                    channel_id = message.channel.id
                    history_key = (gid, uid, channel_id)
                    lock = self._ai_locks.setdefault(history_key, asyncio.Lock())
                    async with lock:
                        monotonic_now = time.monotonic()
                        # Expiração lazy: histórico temporário de 5 minutos, isolado por usuário.
                        for old_key, (_, last_seen) in list(self._ai_memory.items()):
                            if monotonic_now - last_seen >= 300:
                                self._ai_memory.pop(old_key, None)
                                self._ai_error_until.pop(old_key, None)
                                old_lock = self._ai_locks.get(old_key)
                                if old_key != history_key and old_lock and not old_lock.locked():
                                    self._ai_locks.pop(old_key, None)
                        if monotonic_now < self._ai_error_until.get(history_key, 0.0):
                            await message.reply(
                                embed=emb("⏳ Zerith", "Aguarde alguns segundos antes de me chamar novamente."),
                                mention_author=False,
                            )
                        else:
                            buffer, last_seen = self._ai_memory.get(
                                history_key, (deque(maxlen=6), monotonic_now)
                            )
                            if monotonic_now - last_seen >= 300:
                                buffer = deque(maxlen=6)
                            user_text = content[:1200]
                            current_style, learned_style = await self._update_zerith_profile(
                                gid, uid, user_text
                            )
                            payload = [
                                {
                                    "role": "system",
                                    "content": build_zerith_system_prompt(current_style, learned_style),
                                },
                                *list(buffer),
                                {"role": "user", "content": user_text},
                            ]
                            try:
                                async with message.channel.typing():
                                    resposta, _provider = await ia_cog.ask_ai_conversation(payload)
                                if _provider == "nenhum" or resposta.startswith("❌"):
                                    self._ai_error_until[history_key] = time.monotonic() + 30
                                    await message.reply(
                                        embed=emb("⚠️ Zerith indisponível", resposta[:1800]),
                                        mention_author=False,
                                    )
                                else:
                                    buffer.append({"role": "user", "content": user_text})
                                    buffer.append({"role": "assistant", "content": resposta[:2000]})
                                    self._ai_memory[history_key] = (buffer, time.monotonic())
                                    await message.reply(
                                        embed=emb("🩸 Zerith", resposta[:1900]),
                                        mention_author=False,
                                    )
                            except Exception:
                                self._ai_error_until[history_key] = time.monotonic() + 30
                                log.exception(
                                    "Falha ao responder menção à Zerith (guild=%s, user=%s)",
                                    gid, uid,
                                )
                                await message.reply(
                                    embed=emb("⚠️ Zerith indisponível", "Não consegui processar sua mensagem agora."),
                                    mention_author=False,
                                )
                elif content:
                    log.error("Cog IA não está carregado; menção à Zerith ignorada.")

        # Mensagens de comando não geram XP, mas continuam sujeitas aos filtros
        # anti-link/anti-spam acima.
        if is_command:
            return

        u = await get_user(gid, uid)
        if int(time.time()) - int(u["last_xp"] or 0) < XP_CD:
            return
        result = await grant_xp(gid, uid, random.randint(15, 25), level_bonus=25, xp_cooldown=XP_CD)
        if result is None:  # outra mensagem do mesmo usuário já levou o XP deste ciclo
            return
        old_level, lvl, bonus = result
        if lvl > old_level:
            log.info("Level up guild=%s user=%s: %s -> %s (+%s Souls)", gid, uid, old_level, lvl, bonus)
            await apply_level_roles(message.author, lvl)
            try:
                await message.channel.send(embed=emb("🩸 LEVEL UP!", f"{message.author.mention} → **Nível {lvl}**\n🎁 `{bonus} Souls`"), delete_after=30)
            except discord.HTTPException:
                pass

    # Boas-vindas, autorole e anti-raid ficam em cogs/boas_vindas.py e
    # cogs/automod.py desde a v3.1.0.


async def setup(bot):
    await bot.add_cog(Events(bot))
