"""Assistente seguro para montar uma estrutura em um servidor já existente."""
from __future__ import annotations

import asyncio
import logging
import json
import re
from typing import Awaitable, Callable, Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import COLOR, FOOTER, get_config, set_config

log = logging.getLogger("hellsing.setup")
ProgressCallback = Callable[[str], Awaitable[None]]
CREATE_DELAY = 0.80  # espaçamento conservador entre criações de canais/categorias


class ServerSetupConfirmView(discord.ui.View):
    def __init__(self, owner_id: int, guild_id: int, cog: "SetupServidor", plan: Optional[dict] = None):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.cog = cog
        self.plan = plan
        self.running = False
        self.page = 0
        self.message: Optional[discord.Message] = None
        self._sync_page_controls()

    def _page_count(self) -> int:
        if not self.plan:
            return 1
        return max(1, len(self.plan.get("categories", [])))

    def _sync_page_controls(self) -> None:
        previous = getattr(self, "previous_page", None)
        following = getattr(self, "next_page", None)
        if previous is not None:
            previous.disabled = self.plan is None or self.page <= 0 or self.running
        if following is not None:
            following.disabled = self.plan is None or self.page >= self._page_count() - 1 or self.running

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Este painel pertence a quem iniciou a configuração.", ephemeral=True
            )
            return False
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "Este painel não pertence a este servidor.", ephemeral=True
            )
            return False
        return True

    async def _disable(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    @discord.ui.button(label="Construir estrutura", style=discord.ButtonStyle.success, emoji="🏰", row=1)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.running:
            return await interaction.response.send_message("A configuração já está em andamento.", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)

        error = self.cog._can_run(interaction.guild, interaction.user)
        if error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)

        self.running = True
        await self._disable()
        await interaction.response.edit_message(
            embed=self.cog._progress_embed("Preparando a estrutura…", "Verificando permissões e itens existentes."),
            view=self,
        )

        async def progress(text: str) -> None:
            try:
                await interaction.edit_original_response(
                    embed=self.cog._progress_embed("Construindo a Mansão Hellsing…", text),
                    view=self,
                )
            except discord.HTTPException:
                log.warning("Não foi possível atualizar a mensagem de progresso do setup.")

        try:
            if self.plan is not None:
                report = await self.cog.build_custom_template(
                    interaction.guild, self.plan, progress, actor=interaction.user
                )
            else:
                report = await self.cog.build_template(interaction.guild, progress)
        except Exception:
            log.exception("Erro inesperado montando servidor %s", interaction.guild.id)
            report = (
                "⚠️ A configuração foi interrompida por um erro inesperado. Alguns itens podem já ter sido criados. "
                "O assistente pode ser executado novamente: ele reutiliza os itens que já existem."
            )

        self.stop()
        try:
            await interaction.edit_original_response(embed=self.cog._report_embed(report), view=None)
        except discord.HTTPException:
            await interaction.followup.send(report, ephemeral=True)

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary, emoji="◀️", row=0)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.plan or self.running or self.page <= 0:
            return await interaction.response.defer()
        self.page -= 1
        self._sync_page_controls()
        await interaction.response.edit_message(embed=self.cog._plan_embed(self.plan, self.page), view=self)

    @discord.ui.button(label="Próxima", style=discord.ButtonStyle.secondary, emoji="▶️", row=0)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.plan or self.running or self.page >= self._page_count() - 1:
            return await interaction.response.defer()
        self.page += 1
        self._sync_page_controls()
        await interaction.response.edit_message(embed=self.cog._plan_embed(self.plan, self.page), view=self)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="✖️", row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable()
        self.stop()
        await interaction.response.edit_message(
            embed=self.cog._report_embed("🚫 Configuração cancelada. Nenhum item foi criado por este assistente."),
            view=self,
        )

    async def on_timeout(self) -> None:
        await self._disable()
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class ServerDescriptionModal(discord.ui.Modal, title="Montar servidor com IA"):
    description = discord.ui.TextInput(
        label="Descreva o tipo de servidor",
        placeholder="Ex.: comunidade de animes, com chat, notícias, eventos, calls e área privada da equipe...",
        style=discord.TextStyle.paragraph,
        min_length=10,
        max_length=1000,
        required=True,
    )
    separator = discord.ui.TextInput(
        label="Separador após os emojis",
        placeholder="Ex.: ・  |  •  |  ┃",
        default="・",
        min_length=1,
        max_length=5,
        required=False,
    )

    def __init__(self, cog: "SetupServidor"):
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return await interaction.response.send_message("Use este formulário dentro de um servidor.", ephemeral=True)
        error = self.cog._can_run(interaction.guild, interaction.user)
        if error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            plan, _provider = await self.cog.generate_custom_plan(
                str(self.description.value), str(self.separator.value or "・")
            )
        except Exception as exc:
            log.warning("Não foi possível gerar a estrutura personalizada: %s", str(exc)[:300])
            return await interaction.followup.send(
                f"❌ Não consegui montar a prévia. Motivo: `{str(exc)[:500]}`", ephemeral=True
            )
        view = ServerSetupConfirmView(interaction.user.id, interaction.guild.id, self.cog, plan)
        view.message = await interaction.followup.send(
            embed=self.cog._plan_embed(plan, view.page),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class SetupServidor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _progress_embed(title: str, detail: str) -> discord.Embed:
        e = discord.Embed(title=f"🏰 {title}", description=detail, color=COLOR)
        e.set_footer(text=FOOTER)
        return e

    @staticmethod
    def _report_embed(report: str) -> discord.Embed:
        e = discord.Embed(title="🦇 Assistente Hellsing", description=report[:4000], color=COLOR)
        e.set_footer(text=FOOTER)
        return e

    @staticmethod
    def _normalise_overwrites(overwrites: Optional[dict]) -> dict:
        """Garante que a API receba um dict, inclusive quando não há overwrites."""
        if overwrites is None:
            return {}
        if not isinstance(overwrites, dict):
            raise TypeError("overwrites precisa ser um dicionário de alvo: PermissionOverwrite")
        return dict(overwrites)

    @classmethod
    def _staff_overwrites(cls, guild: discord.Guild, staff_role: discord.Role) -> dict:
        values = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            staff_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                manage_messages=True,
            ),
        }
        me = guild.me
        if me:
            values[me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
            )
        return cls._normalise_overwrites(values)

    @classmethod
    def _readonly_overwrites(cls, guild: discord.Guild, staff_role: discord.Role) -> dict:
        values = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        me = guild.me
        if me:
            values[me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, manage_messages=True
            )
        return cls._normalise_overwrites(values)

    async def _ensure_role(
        self, guild: discord.Guild, name: str, colour: int, permissions: discord.Permissions
    ) -> tuple[discord.Role, bool]:
        existing = discord.utils.get(guild.roles, name=name)
        if existing:
            return existing, False
        role = await guild.create_role(
            name=name,
            colour=discord.Colour(colour),
            permissions=permissions,
            hoist=True,
            mentionable=False,
            reason="Configuração inicial Hellsing confirmada por administrador",
        )
        await asyncio.sleep(0.35)
        return role, True

    async def _ensure_category(
        self, guild: discord.Guild, name: str, overwrites: Optional[dict] = None
    ) -> tuple[discord.CategoryChannel, bool]:
        existing = discord.utils.get(guild.categories, name=name)
        safe_overwrites = self._normalise_overwrites(overwrites)
        if existing:
            if safe_overwrites:
                await existing.edit(overwrites=safe_overwrites, reason="Sincronização de permissões do setup Hellsing")
            return existing, False
        category = await guild.create_category(
            name=name,
            overwrites=safe_overwrites,
            reason="Configuração inicial Hellsing confirmada por administrador",
        )
        await asyncio.sleep(CREATE_DELAY)
        return category, True

    async def _ensure_text(
        self,
        category: discord.CategoryChannel,
        name: str,
        topic: str,
        overwrites: Optional[dict] = None,
    ) -> tuple[discord.TextChannel, bool]:
        existing = discord.utils.get(category.text_channels, name=name)
        safe_overwrites = self._normalise_overwrites(overwrites)
        if existing:
            changes = {}
            if safe_overwrites:
                changes["overwrites"] = safe_overwrites
            if topic and existing.topic != topic[:1024]:
                changes["topic"] = topic[:1024]
            if changes:
                await existing.edit(**changes, reason="Sincronização do setup Hellsing")
            return existing, False
        channel = await category.create_text_channel(
            name=name,
            topic=topic[:1024],
            overwrites=safe_overwrites,
            reason="Configuração inicial Hellsing confirmada por administrador",
        )
        await asyncio.sleep(CREATE_DELAY)
        return channel, True

    async def _ensure_voice(
        self, category: discord.CategoryChannel, name: str, overwrites: Optional[dict] = None
    ) -> tuple[discord.VoiceChannel, bool]:
        existing = discord.utils.get(category.voice_channels, name=name)
        safe_overwrites = self._normalise_overwrites(overwrites)
        if existing:
            if safe_overwrites:
                await existing.edit(overwrites=safe_overwrites, reason="Sincronização de permissões do setup Hellsing")
            return existing, False
        channel = await category.create_voice_channel(
            name=name,
            overwrites=self._normalise_overwrites(overwrites),
            reason="Configuração inicial Hellsing confirmada por administrador",
        )
        await asyncio.sleep(CREATE_DELAY)
        return channel, True

    async def build_template(self, guild: discord.Guild, progress: Optional[ProgressCallback] = None) -> str:
        me = guild.me
        if me is None:
            return "❌ Não consegui identificar o membro do bot neste servidor."
        if not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
            return "❌ O bot precisa de **Gerenciar Canais** e **Gerenciar Cargos**."

        created = {"roles": 0, "categories": 0, "channels": 0}
        reused = {"roles": 0, "categories": 0, "channels": 0}
        errors: list[str] = []
        channels: dict[str, discord.abc.GuildChannel] = {}
        operations = 0

        async def tick(label: str) -> None:
            nonlocal operations
            operations += 1
            if progress and (operations % 4 == 0):
                await progress(f"{label}\nItens processados: `{operations}`")

        roles_to_make = (
            ("🛡️ Equipe Hellsing", 0x89282B, discord.Permissions(manage_messages=True, moderate_members=True)),
            ("🩸 Membro", 0x7F8C8D, discord.Permissions.none()),
            ("🤖 Bots", 0x5865F2, discord.Permissions.none()),
        )
        role_map: dict[str, discord.Role] = {}
        for name, colour, perms in roles_to_make:
            try:
                role, was_created = await self._ensure_role(guild, name, colour, perms)
                role_map[name] = role
                created["roles"] += int(was_created)
                reused["roles"] += int(not was_created)
            except discord.HTTPException as exc:
                errors.append(f"Cargo `{name}`: HTTP {exc.status}")
            await tick(f"🏷️ Cargo verificado: {name}")

        staff_role = role_map.get("🛡️ Equipe Hellsing")
        if staff_role is None:
            return "❌ Não foi possível criar/localizar o cargo da equipe. Nenhum canal foi criado."

        specs = [
            ("📌・INFORMAÇÕES", [
                ("regras", "Regras e orientações da comunidade.", "readonly"),
                ("anuncios", "Comunicados oficiais do servidor.", "readonly"),
                ("novidades", "Atualizações e novidades.", "readonly"),
                ("boas-vindas", "Entradas de novos membros.", "readonly"),
                ("cargos", "Informações sobre cargos e interesses.", "open"),
            ]),
            ("💬・COMUNIDADE", [
                ("chat-geral", "Conversa geral da comunidade.", "open"),
                ("apresentacoes", "Apresente-se à comunidade.", "open"),
                ("midia", "Compartilhamento de imagens e mídias.", "open"),
                ("memes", "Memes e momentos divertidos.", "open"),
            ]),
            ("🎮・ENTRETENIMENTO", [
                ("jogos", "Conversas sobre jogos.", "open"),
                ("comandos", "Use os comandos do bot aqui.", "open"),
                ("eventos", "Eventos e atividades da comunidade.", "open"),
            ]),
            ("🎫・SUPORTE", [
                ("suporte", "Dúvidas e suporte da comunidade.", "open"),
                ("abrir-ticket", "Use /painel_ticket para publicar o painel.", "open"),
            ]),
        ]

        for category_name, channel_specs in specs:
            try:
                category, was_created = await self._ensure_category(guild, category_name)
                created["categories"] += int(was_created)
                reused["categories"] += int(not was_created)
            except discord.HTTPException as exc:
                errors.append(f"Categoria `{category_name}`: HTTP {exc.status}")
                continue
            await tick(f"📁 Categoria verificada: {category_name}")
            for channel_name, topic, mode in channel_specs:
                overwrites = self._readonly_overwrites(guild, staff_role) if mode == "readonly" else {}
                try:
                    channel, was_created = await self._ensure_text(category, channel_name, topic, overwrites)
                    channels[channel_name] = channel
                    created["channels"] += int(was_created)
                    reused["channels"] += int(not was_created)
                except discord.HTTPException as exc:
                    errors.append(f"Canal `#{channel_name}`: HTTP {exc.status}")
                await tick(f"💬 Canal verificado: #{channel_name}")

        staff_log = None
        try:
            staff_overwrites = self._staff_overwrites(guild, staff_role)
            staff_category, was_created = await self._ensure_category(guild, "🔒・EQUIPE", staff_overwrites)
            created["categories"] += int(was_created)
            reused["categories"] += int(not was_created)
            await tick("🔒 Área privada da equipe verificada")
            for channel_name, topic in (
                ("staff-chat", "Comunicação interna da equipe."),
                ("mod-log", "Registros e auditoria da moderação."),
                ("denuncias", "Análise privada de denúncias."),
            ):
                try:
                    channel, was_created = await self._ensure_text(
                        staff_category, channel_name, topic, staff_overwrites
                    )
                    channels[channel_name] = channel
                    created["channels"] += int(was_created)
                    reused["channels"] += int(not was_created)
                    if channel_name == "mod-log":
                        staff_log = channel
                except discord.HTTPException as exc:
                    errors.append(f"Canal privado `#{channel_name}`: HTTP {exc.status}")
                await tick(f"🔐 Canal de equipe verificado: #{channel_name}")
        except discord.HTTPException as exc:
            errors.append(f"Categoria privada da equipe: HTTP {exc.status}")

        try:
            voice_category, was_created = await self._ensure_category(guild, "🔊・VOZ")
            created["categories"] += int(was_created)
            reused["categories"] += int(not was_created)
            await tick("🔊 Categoria de voz verificada")
            for voice_name in ("Geral", "Jogos"):
                try:
                    _, was_created = await self._ensure_voice(voice_category, voice_name)
                    created["channels"] += int(was_created)
                    reused["channels"] += int(not was_created)
                except discord.HTTPException as exc:
                    errors.append(f"Canal de voz `{voice_name}`: HTTP {exc.status}")
                await tick(f"🔊 Canal de voz verificado: {voice_name}")
        except discord.HTTPException as exc:
            errors.append(f"Categoria de voz: HTTP {exc.status}")

        current = await get_config(guild.id)
        updates = {}
        if not current.get("welcome_channel") and channels.get("boas-vindas"):
            updates["welcome_channel"] = channels["boas-vindas"].id
        if not current.get("log_channel") and staff_log:
            updates["log_channel"] = staff_log.id
        support = discord.utils.get(guild.categories, name="🎫・SUPORTE")
        if not current.get("ticket_category") and support:
            updates["ticket_category"] = support.id
        if not current.get("ticket_log") and staff_log:
            updates["ticket_log"] = staff_log.id
        if not current.get("ticket_staff_role"):
            updates["ticket_staff_role"] = staff_role.id
        if updates:
            try:
                await set_config(guild.id, **updates)
            except Exception:
                log.exception("Falha ao gravar configuração automática para guild %s", guild.id)
                errors.append("Configuração automática: falha ao gravar no SQLite.")

        lines = [
            "✅ **Estrutura Hellsing concluída (ou parcialmente concluída).**",
            f"🏷️ Cargos: `{created['roles']}` criados / `{reused['roles']}` reutilizados",
            f"📁 Categorias: `{created['categories']}` criadas / `{reused['categories']}` reutilizadas",
            f"💬 Canais: `{created['channels']}` criados / `{reused['channels']}` reutilizados",
            "🔒 A área privada usa overwrites explícitos; permissões privadas são sincronizadas nos itens reutilizados quando definidas no plano.",
            "🎫 Publique o painel com `/painel_ticket` no canal `#abrir-ticket`.",
        ]
        if errors:
            lines.append("\n⚠️ **Ocorrências:**\n" + "\n".join(f"• {item}" for item in errors[:8]))
            if len(errors) > 8:
                lines.append(f"• Mais `{len(errors) - 8}` ocorrência(s) foram registradas no console.")
        lines.append("\n-# O assistente não apaga canais em massa. Itens compatíveis são reutilizados e permissões privadas definidas pelo plano são sincronizadas.")
        return "\n".join(lines)

    @staticmethod
    def _safe_label(value: object, fallback: str, limit: int = 90) -> str:
        text = str(value or fallback).replace("@", "＠").replace("#", "＃")
        text = re.sub(r"[<>`\\/\r\n]", "", text)
        # Remove referências internas de módulo que alguns modelos devolvem
        # como se fossem nomes de categorias/canais.
        text = re.sub(r"(?i)cogs[._\- ]*setup[._\- ]*", "", text)
        text = re.sub(r"(?i)^setup[._\- ]*", "", text)
        text = text.replace("_", " ").replace("-", " ")
        text = re.sub(r"\s+", "-", text.strip())
        return text[:limit].strip("-_") or fallback

    @staticmethod
    def _safe_emoji(value: object) -> str:
        if not isinstance(value, str):
            return ""
        value = value.strip()
        if len(value) > 12 or any(token in value for token in ("@", "#", "<", ">", "`", "\\", "/")):
            return ""
        return value

    @classmethod
    def _normalize_ai_plan(cls, raw: object, separator: str) -> dict:
        if not isinstance(raw, dict) or not isinstance(raw.get("categories"), list):
            raise ValueError("A IA não retornou um plano com categorias válido.")

        categories = []
        total_channels = 0
        for cat in raw["categories"][:12]:
            if not isinstance(cat, dict) or not isinstance(cat.get("channels"), list):
                continue
            category_name = cls._safe_label(cat.get("name"), "categoria", 70)
            category_emoji = cls._safe_emoji(cat.get("emoji"))
            channels = []
            for channel in cat["channels"][:25]:
                if total_channels >= 50:
                    break
                if not isinstance(channel, dict):
                    continue
                kind = channel.get("type", "text")
                if kind not in ("text", "voice"):
                    kind = "text"
                name = cls._safe_label(channel.get("name"), "canal", 75)
                emoji = cls._safe_emoji(channel.get("emoji"))
                topic = channel.get("topic", "")
                if not isinstance(topic, str):
                    topic = ""
                channels.append({
                    "name": name,
                    "emoji": emoji,
                    "type": kind,
                    "topic": topic[:1024],
                    "private": bool(channel.get("private", False)),
                })
                total_channels += 1
            if channels:
                categories.append({
                    "name": category_name,
                    "emoji": category_emoji,
                    "private": bool(cat.get("private", False)),
                    "channels": channels,
                })

        if not categories or total_channels == 0:
            raise ValueError("A IA não sugeriu canais válidos. Descreva melhor o servidor e tente novamente.")

        roles = []
        for role in (raw.get("roles", []) if isinstance(raw.get("roles", []), list) else [])[:12]:
            if not isinstance(role, dict):
                continue
            name = cls._safe_label(role.get("name"), "Membro", 90)
            if name.casefold() in ("@everyone", "everyone", "everyone role"):
                continue
            color = role.get("color", "#7F8C8D")
            if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                color = "#7F8C8D"
            roles.append({"name": name, "color": color})

        separator = cls._safe_emoji(separator) or "・"
        return {"categories": categories, "roles": roles, "separator": separator}

    @staticmethod
    def _extract_json(content: str) -> dict:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        if start < 0:
            raise ValueError("A resposta da IA não contém JSON.")
        try:
            value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        except json.JSONDecodeError as exc:
            raise ValueError("A IA retornou JSON inválido. Tente descrever o servidor de outra forma.") from exc
        if not isinstance(value, dict):
            raise ValueError("A IA retornou um plano em formato inválido.")
        return value

    async def generate_custom_plan(self, description: str, separator: str = "・") -> tuple[dict, str]:
        """Tenta todas as APIs de IA disponíveis. Se nenhuma responder, levanta erro claro."""
        ai = self.bot.get_cog("IA")
        if ai is None:
            raise RuntimeError(
                "O módulo de IA não está carregado. Configure as chaves no Ambiente "
                "(OPENROUTER_API_KEY, GEMINI_API_KEY ou NVIDIA_API_KEY) e reinicie o bot."
            )

        prompt = (
            "Crie uma estrutura de servidor Discord com base na descrição abaixo. "
            "Retorne SOMENTE JSON válido, sem Markdown, com este formato: "
            '{"categories":[{"name":"INFORMAÇÕES","emoji":"📌","private":false,'
            '"channels":[{"name":"regras","emoji":"📜","type":"text","topic":"Regras",'
            '"private":false}]}],"roles":[{"name":"Membro","color":"#7F8C8D"}]}. '
            "Inclua categorias e canais que façam sentido para a comunidade. Use nomes curtos, "
            "em português brasileiro, emojis relevantes e canais de texto/voz. Marque áreas da equipe "
            "como private=true. Limite a 12 categorias, 25 canais por categoria, 50 canais no total "
            "e 12 cargos. NÃO inclua permissões, IDs, menções ou cargos com Administrador.\n\n"
            "Descrição do servidor:\n" + description[:1000]
        )

        tried: list[str] = []
        last_err = ""
        for provider_name in ("openrouter", "gemini", "nvidia"):
            try:
                content, provider = await ai.ask_ai(
                    prompt, provider_name, fallback=False, max_tokens=3500
                )
                if provider and provider != "nenhum" and content:
                    raw = self._extract_json(content)
                    plan = self._normalize_ai_plan(raw, separator)
                    plan["provider"] = provider_name
                    plan["description"] = description[:1000]
                    return plan, provider_name
                tried.append(provider_name)
            except Exception as exc:
                tried.append(provider_name)
                last_err = str(exc)[:200]
                continue

        nomes = ", ".join(tried) if tried else "nenhum"
        raise RuntimeError(
            f"Não consegui gerar a estrutura: nenhuma API de IA respondeu "
            f"(tentativas: {nomes}). "
            f"Verifique as chaves OPENROUTER_API_KEY / GEMINI_API_KEY / NVIDIA_API_KEY "
            f"e a cota dos provedores."
            + (f" Último erro: {last_err}" if last_err else "")
        )

    @staticmethod
    def _format_plan_name(emoji: object, name: object, separator: object, limit: object = 100) -> str:
        """Gera nomes Discord limpos, inclusive para planos antigos/malformados da IA."""
        safe_emoji = str(emoji or "").strip()[:12]
        safe_name = str(name or "canal").strip()
        # Prefixos internos podem vir com <>, crases, underscores ou repetidos.
        safe_name = re.sub(r'[<>`"\']', "", safe_name)
        safe_name = re.sub(r"(?i)cogs[._ -]*setup[._ -]*", "", safe_name)
        safe_name = re.sub(r"(?i)^setup[._ -]*", "", safe_name)
        safe_name = safe_name.replace("_", " ").replace("-", " ")
        safe_name = re.sub(r"(?i)\bcogs\b", "", safe_name)
        safe_name = re.sub(r"\\s+", " ", safe_name).strip(" .・|—–-")
        safe_name = safe_name or "canal"
        safe_separator = str(separator or "・").strip()[:5]
        try:
            max_length = max(1, min(int(limit), 100))
        except (TypeError, ValueError, OverflowError):
            max_length = 100
        prefix = f"{safe_emoji}{safe_separator}" if safe_emoji else ""
        return f"{prefix}{safe_name}"[:max_length]

    def _plan_embed(self, plan: dict, page: int = 0) -> discord.Embed:
        categories = plan.get("categories", [])
        page = max(0, min(page, max(0, len(categories) - 1)))
        channel_total = sum(len(item["channels"]) for item in categories)
        current = categories[page] if categories else None
        embed = discord.Embed(
            title="🏰 Prévia da estrutura criada por IA",
            description=(
                f"**Descrição:** {plan.get('description', '')[:450]}\n"
                f"**Provedor:** `{plan.get('provider', 'desconhecido')}` · "
                f"**Separador:** `{plan['separator']}`\n"
                "Confira cada página. Nada será criado até confirmar."
            ),
            color=COLOR,
        )
        if current:
            name = self._format_plan_name(current["emoji"], current["name"], plan["separator"])
            lines = []
            for channel in current["channels"]:
                channel_name = self._format_plan_name(channel["emoji"], channel["name"], plan["separator"])
                marker = "🔊" if channel["type"] == "voice" else "#"
                private = " 🔒" if (current["private"] or channel["private"]) else ""
                lines.append(f"{marker} `{channel_name}`{private}")
            suffix = " • privada" if current["private"] else ""
            chunks = [lines[index:index + 8] for index in range(0, len(lines), 8)] or [["_Sem canais_"]]
            for part, chunk in enumerate(chunks, start=1):
                field_name = f"{name}{suffix}" if part == 1 else f"{name}{suffix} · continuação {part}"
                embed.add_field(name=field_name[:256], value="\n".join(chunk)[:1024], inline=False)

        if page == len(categories) - 1 and plan.get("roles"):
            role_lines = [
                f"• `{item['name']}` — `{item['color']}` (sem permissões elevadas)"
                for item in plan["roles"]
            ]
            for part, start in enumerate(range(0, len(role_lines), 6), start=1):
                embed.add_field(
                    name="Cargos sugeridos" if part == 1 else f"Cargos sugeridos · continuação {part}",
                    value="\n".join(role_lines[start:start + 6])[:1024],
                    inline=False,
                )
        embed.set_footer(
            text=(
                f"Página {page + 1}/{max(1, len(categories))} • {len(categories)} categorias • "
                f"{channel_total} canais • {len(plan.get('roles', []))} cargos • prévia expira em 3 min"
            )
        )
        return embed

    async def _get_private_staff_role(self, guild: discord.Guild) -> tuple[discord.Role, bool]:
        """Usa um cargo dedicado salvo no banco; nunca reutiliza cargo homônimo desconhecido."""
        config = await get_config(guild.id)
        configured_id = config.get("setup_staff_role")
        if configured_id:
            existing = guild.get_role(int(configured_id))
            if existing is not None:
                return existing, False

        base_name = "🛡️ Equipe Hellsing IA"
        existing_names = {role.name.casefold() for role in guild.roles}
        role_name = base_name
        suffix = 2
        while role_name.casefold() in existing_names:
            role_name = f"{base_name} {suffix}"
            suffix += 1

        role = await guild.create_role(
            name=role_name,
            permissions=discord.Permissions.none(),
            hoist=False,
            mentionable=False,
            reason="Cargo privado do assistente de montagem Hellsing",
        )
        await set_config(guild.id, setup_staff_role=role.id)
        await asyncio.sleep(0.35)
        return role, True

    async def build_custom_template(
        self,
        guild: discord.Guild,
        plan: dict,
        progress: Optional[ProgressCallback] = None,
        *,
        actor: Optional[discord.Member] = None,
    ) -> str:
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
            return "❌ O bot precisa das permissões Gerenciar Canais e Gerenciar Cargos."

        created = {"roles": 0, "categories": 0, "channels": 0}
        reused = {"roles": 0, "categories": 0, "channels": 0}
        errors: list[str] = []
        separator = plan.get("separator", "・")
        try:
            staff_role, made = await self._get_private_staff_role(guild)
            created["roles"] += int(made)
            reused["roles"] += int(not made)
        except discord.HTTPException as exc:
            return f"❌ Não foi possível criar/localizar o cargo privado da equipe: HTTP {exc.status}."

        if actor is not None and staff_role not in actor.roles:
            try:
                await actor.add_roles(
                    staff_role,
                    reason="Acesso inicial à área privada criada pelo assistente Hellsing",
                )
            except discord.HTTPException as exc:
                return (
                    f"❌ O cargo privado `{staff_role.name}` foi preparado, mas não consegui atribuí-lo "
                    f"a quem iniciou a montagem (HTTP {exc.status}). Nenhum canal foi criado."
                )

        for role_data in plan.get("roles", []):
            name = role_data["name"]
            if name.casefold() == staff_role.name.casefold():
                continue
            try:
                role, made = await self._ensure_role(
                    guild, name, int(role_data["color"].lstrip("#"), 16), discord.Permissions.none()
                )
                created["roles"] += int(made)
                reused["roles"] += int(not made)
            except discord.HTTPException as exc:
                errors.append(f"Cargo `{name}`: HTTP {exc.status}")

        operations = 0
        async def tick(label: str) -> None:
            nonlocal operations
            operations += 1
            if progress and operations % 3 == 0:
                await progress(f"{label}\nItens processados: `{operations}`")

        for category_data in plan["categories"]:
            category_name = self._format_plan_name(
                category_data["emoji"], category_data["name"], separator
            )
            cat_overwrites = self._staff_overwrites(guild, staff_role) if category_data["private"] else {}
            if category_data["private"]:
                base_name = category_name[:82]
                for suffix in range(1, 10):
                    existing_category = discord.utils.get(guild.categories, name=category_name)
                    if existing_category is None:
                        break
                    everyone_denied = existing_category.overwrites_for(guild.default_role).view_channel is False
                    staff_allowed = existing_category.overwrites_for(staff_role).view_channel is True
                    bot_allowed = guild.me is not None and existing_category.overwrites_for(guild.me).view_channel is True
                    if everyone_denied and staff_allowed and bot_allowed:
                        break
                    category_name = f"{base_name}-privado-{suffix}"[:100]
            try:
                category, made = await self._ensure_category(guild, category_name, cat_overwrites)
                created["categories"] += int(made)
                reused["categories"] += int(not made)
            except discord.HTTPException as exc:
                errors.append(f"Categoria `{category_name}`: HTTP {exc.status}")
                continue
            await tick(f"📁 Categoria processada: {category_name}")

            for channel_data in category_data["channels"]:
                channel_name = self._format_plan_name(
                    channel_data["emoji"], channel_data["name"], separator
                )
                is_private = category_data["private"] or channel_data["private"]
                overwrites = self._staff_overwrites(guild, staff_role) if is_private else {}
                if is_private:
                    base_channel_name = channel_name[:82]
                    for suffix in range(1, 10):
                        existing_channel = (
                            discord.utils.get(category.voice_channels, name=channel_name)
                            if channel_data["type"] == "voice"
                            else discord.utils.get(category.text_channels, name=channel_name)
                        )
                        if existing_channel is None:
                            break
                        everyone_denied = existing_channel.overwrites_for(guild.default_role).view_channel is False
                        staff_allowed = existing_channel.overwrites_for(staff_role).view_channel is True
                        bot_allowed = guild.me is not None and existing_channel.overwrites_for(guild.me).view_channel is True
                        if everyone_denied and staff_allowed and bot_allowed:
                            break
                        channel_name = f"{base_channel_name}-privado-{suffix}"[:100]
                try:
                    if channel_data["type"] == "voice":
                        channel, made = await self._ensure_voice(category, channel_name, overwrites)
                    else:
                        channel, made = await self._ensure_text(
                            category, channel_name, channel_data["topic"], overwrites
                        )
                    created["channels"] += int(made)
                    reused["channels"] += int(not made)
                except discord.HTTPException as exc:
                    errors.append(f"Canal `{channel_name}`: HTTP {exc.status}")
                await tick(f"💬 Canal processado: {channel_name}")

        lines = [
            "✅ **Estrutura personalizada concluída ou parcialmente concluída.**",
            f"🏷️ Cargos: `{created['roles']}` criados / `{reused['roles']}` reutilizados",
            f"📁 Categorias: `{created['categories']}` criadas / `{reused['categories']}` reutilizadas",
            f"💬 Canais: `{created['channels']}` criados / `{reused['channels']}` reutilizados",
            f"🔒 Categorias e canais privados ocultam `@everyone` e liberam o cargo `{staff_role.name}`.",
            "🛡️ Quem confirmou a montagem recebe o cargo privado; atribua-o manualmente aos demais membros da equipe.",
            "Cargos sugeridos pela IA são criados sem permissões elevadas; o bot não concede Administrador.",
            "🔐 Permissões privadas e tópicos dos itens reutilizados foram sincronizados quando definidos no plano.",
        ]
        if errors:
            lines.append("\n⚠️ **Ocorrências:**\n" + "\n".join(f"• {item}" for item in errors[:8]))
            if len(errors) > 8:
                lines.append(f"• Mais `{len(errors) - 8}` ocorrência(s) foram registradas no console.")
        return "\n".join(lines)

    @staticmethod
    def _can_run(guild: discord.Guild, actor: discord.abc.User) -> Optional[str]:
        if not isinstance(actor, discord.Member):
            return "Este comando só funciona em um servidor."
        if actor.id != guild.owner_id and not actor.guild_permissions.manage_guild:
            return "Você precisa da permissão **Gerenciar Servidor**."
        if not actor.guild_permissions.manage_channels or not actor.guild_permissions.manage_roles:
            return "Você também precisa de **Gerenciar Canais** e **Gerenciar Cargos**."
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
            return "O bot precisa das permissões **Gerenciar Canais** e **Gerenciar Cargos**."
        return None

    @app_commands.command(name="montar_servidor", description="Cria uma estrutura personalizada a partir da sua descrição.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True, manage_channels=True, manage_roles=True)
    async def montar_servidor_slash(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Este comando só funciona em servidores.", ephemeral=True)
        error = self._can_run(interaction.guild, interaction.user)
        if error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        await interaction.response.send_modal(ServerDescriptionModal(self))

    @commands.command(name="montarservidor", aliases=["setupservidor", "criarservidor"])
    @commands.guild_only()
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def montar_servidor_prefix(self, ctx: commands.Context, *, descricao: str = ""):
        if not isinstance(ctx.author, discord.Member):
            return
        error = self._can_run(ctx.guild, ctx.author)
        if error:
            return await ctx.reply(f"❌ {error}", mention_author=False)
        if not descricao.strip():
            return await ctx.reply(
                "Descreva o servidor. Exemplo: `;montarservidor comunidade de animes com chat, novidades, eventos e área privada da equipe`. "
                "Para escolher o separador visual, use `/montar_servidor`.", mention_author=False
            )
        async with ctx.typing():
            try:
                plan, _provider = await self.generate_custom_plan(descricao, "・")
            except Exception as exc:
                log.warning("Geração de estrutura via prefixo falhou: %s", str(exc)[:250])
                return await ctx.reply(f"❌ Não consegui gerar a estrutura: {str(exc)[:350]}", mention_author=False)
        view = ServerSetupConfirmView(ctx.author.id, ctx.guild.id, self, plan)
        view.message = await ctx.send(
            embed=self._plan_embed(plan, view.page),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupServidor(bot))
