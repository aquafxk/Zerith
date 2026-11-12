"""Menu interativo Hellsing — select bonito, páginas com GIF e comandos atualizados."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import COLOR, FOOTER, get_config

# ---------------------------------------------------------------------------
# Conteúdo das páginas (markdown)
# ---------------------------------------------------------------------------

MENU_PAGES = {
    "inicio": (
        "# 🦇 ORGANIZAÇÃO HELLSING\n"
        "### Central de comandos\n"
        "Escolha uma categoria no menu abaixo.\n\n"
        "> `/` = slash  ·  `;` = prefixo  ·  `!` também funciona\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "**Ajuda rápida**\n"
        "`/menu` · `;menu` · `;ajuda` · `;comandos`\n"
        "**Setup**\n"
        "`/montar_servidor` · `;montarservidor`"
    ),
    "servidor": (
        "# 🏰 APLICAÇÃO DO SERVIDOR\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "`/app_servidor` — checklist do que já está configurado\n"
        "`/montar_servidor` — criar canais e cargos com IA\n"
        "`/config logs` · `/config antispam` · `/config antilink`\n"
        "`/config ticket_categoria` · `/config ticket_staff` · `/painel_ticket`\n"
        "`/config cargo_nivel` · `/rank` · `/perfil` (níveis/XP)\n"
        "`/bump_lembrete` · `/bump_confirmar`\n\n"
        "**Dono do bot:** `/dono status` · `/dono guilds` (requer OWNER_ID no .env)"
    ),
    "economia": (
        "# 💰 ECONOMIA E PROGRESSÃO\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "`/daily` · `;daily` — recompensa diária\n"
        "`/missao` · `;missao` — missão da Organização (cooldown 6h)\n"
        "`/work` · `;work` — trabalhar (`;trabalhar`)\n"
        "`/saldo` · `;saldo` — ver Souls (`;carteira`)\n"
        "`/pagar` · `;pagar` — transferir (`;transferir`)\n"
        "`/perfil` · `;perfil` — perfil do membro\n"
        "`/rank` · `;rank` — ranking (`;ranking`)\n\n"
        "Gaste suas Souls na página **Loja e cassino**."
    ),
    "cassino": (
        "# 🎰 LOJA E CASSINO\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "**Loja**\n"
        "`/loja ver` · `;loja` — itens à venda\n"
        "`/loja comprar` · `;comprar <id>` — comprar item ou cargo\n"
        "`/loja itens` — seus itens\n"
        "`/loja adicionar` · `/loja editar` · `/loja remover` — staff\n\n"
        "**Cassino** (aposta mínima 10)\n"
        "`/cassino moeda` · `;moeda` — cara ou coroa (1,9x)\n"
        "`/cassino slots` · `;slots` — caça-níquel (até 75x)\n"
        "`/cassino dados` — acerte o número (5,5x)\n"
        "`/cassino roleta` — cor/par/ímpar 2x · número 36x\n"
        "`/cassino blackjack` — contra a banca (2x · blackjack 2,5x)\n"
        "`/cassino roubar` · `;roubar` — 40% de chance, cooldown 2h\n"
        "`/cassino config` — staff: ligar/desligar, aposta máxima"
    ),
    "comunidade": (
        "# 🎉 COMUNIDADE\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "**Boas-vindas (staff)**\n"
        "`/boasvindas configurar` — canal, mensagens, imagem, DM e despedida\n"
        "`/boasvindas cargo` — cargo automático para membros ou bots\n"
        "`/boasvindas ver` · `/boasvindas testar`\n\n"
        "**Social**\n"
        "`/lembrete criar` · `;lembrar 10m texto` — lembretes\n"
        "`/lembrete listar` · `/lembrete cancelar`\n"
        "`/enquete` — enquete nativa do Discord\n"
        "`/sugestao enviar` · `/sugestao responder` (staff) · `/sugestao canal`\n"
        "`/aniversario definir` · `ver` · `proximos` · `config` (staff)\n"
        "`/afk` · `;afk` — avisar que está ausente"
    ),
    "gacha": (
        "# 🃏 COLEÇÃO E DESAFIOS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "`/roll` · `;roll` — invocar carta (`;gacha`)\n"
        "`/inventario` · `;inventario` — coleção (`;cartas`)\n"
        "`/carta` · `;carta` — ver carta (`;personagem`)\n"
        "`/personagens` · `;personagens` — catálogo com GIFs\n"
        "`/duelo` · `;duelo` — disputa (`;batalha`)\n"
        "`/desafio` · `;desafio` — quiz (`;quiz`)\n"
        "`/vender` · `/trocar` — venda e troca (slash)"
    ),
    "acoes": (
        "# 💞 AÇÕES E GIFS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "`/abracar` · `;abracar` — abraçar (`;hug`)\n"
        "`/beijar` · `;beijar` — beijar (`;kiss`)\n"
        "`/cafune` · `;cafune` — cafuné (`;pat`)\n"
        "`/tapa` · `;tapa` — tapa (`;slap`)\n"
        "`/socar` · `;socar` — soco (`;punch`)\n"
        "`/acariciar` · `;acariciar` — aconchegar (`;cuddle`)\n"
        "`/morder` · `;morder` — morder (`;bite`)\n"
        "`/lambida` — lambida\n"
        "`/dancar` · `;dancar` — dançar (`;dance`)\n"
        "`/acenar` · `/piscar` · `/carinho`\n"
        "`/toca_aqui` · `/cocegas`\n\n"
        "Sem mencionar alguém → age em si mesmo. Cooldown 5s."
    ),
    "moderacao": (
        "# 🛡️ MODERAÇÃO (SLASH)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "`/kick` — expulsar\n"
        "`/ban` — banir\n"
        "`/timeout` — silenciar temporário\n"
        "`/avisar` · `/avisos` — avisos\n"
        "`/cases` — histórico\n"
        "`/lockdown` — trancar/liberar canal\n"
        "`/nuke` — recriar canal atual (confirmação; apaga histórico)\n"
        "`/slowmode` — intervalo entre mensagens\n"
        "`/limpar_usuario` — limpar mensagens de membro\n"
        "`/limpar` — apagar mensagens\n\n"
        "**Automod**\n"
        "`/automod status` · `/automod filtro` (caps, emojis, repetição, linhas, links)\n"
        "`/automod palavra` · `/automod palavras` — filtro de palavras\n"
        "`/automod punicao` — timeout após X infrações\n"
        "`/automod antiraid` · `/automod raid_encerrar` · `/automod idade_minima`\n"
        "`/automod isentar` · `/automod link_permitido`\n\n"
        "Respeitam permissões e hierarquia de cargos."
    ),
    "config": (
        "# ⚙️ CONFIGURAÇÕES (SLASH)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "`/config logs` — auditoria\n"
        "`/config antispam` · `/config antilink`\n"
        "`/config ticket_categoria` · `/config ticket_log`\n"
        "`/config ticket_staff` — cargo da equipe\n"
        "`/config painel_json` — personalizar textos via JSON\n"
        "`/config painel_json_reset` — restaurar textos padrão\n"
        "`/config cargo_nivel` · `/config cargos_nivel`\n"
        "`/montar_servidor` — gerar estrutura com IA"
    ),
    "tickets": (
        "# 🎫 ATENDIMENTO E SORTEIOS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "`/painel_ticket` — painel de chamados\n"
        "`/ticket` — abrir chamado\n"
        "`/ticket_fechar` — fechar chamado\n"
        "`/painel_cargos` — cargos por reação\n"
        "`/sorteio iniciar` — criar sorteio\n"
        "`/sorteio encerrar` · `/sorteio cancelar`\n"
        "`/sorteio reroll` · `/sorteio listar`"
    ),
    "ia": (
        "# 🤖 INTELIGÊNCIA ARTIFICIAL\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "`/ia` · `;ia` — conversar (fallback automático)\n"
        "`/ia_status` · `;ia_status` — estado das APIs\n"
        "`/ia_testar` · `;ia_testar` — testar provedor\n"
        "`/ia_modelos` · `;ia_modelos` — varredura (admin)\n"
        "`/gerar_imagem` · `;gerar_imagem` — gerar imagem\n\n"
        "Provedores: OpenRouter · Groq · Cloudflare · Gemini · NVIDIA · OpenAI"
    ),
    "extras": (
        "# 🧰 UTILIDADES E EXTRAS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "`/stats` · `;stats` — status do bot\n"
        "`/userinfo` · `;userinfo` — info de membro\n"
        "`;ping` — latência\n"
        "`/baixar instagram` · `/baixar tiktok`\n"
        "`/baixar twitter` · `/baixar pinterest` · `/pinterest` · `/baixar status` · `/baixar ajuda`\n"
        "`/bump_lembrete` · `/bump_confirmar` · `/bump_desativar`"
    ),
}

# GIF temático por página (URLs públicas estáveis)
MENU_GIFS = {
    "servidor": "https://cdn.otakugifs.xyz/gifs/pat/f738473258ae31f5.gif",
    "inicio": "https://cdn.otakugifs.xyz/gifs/wave/c265105164e5f6ba.gif",
    "economia": "https://cdn.otakugifs.xyz/gifs/dance/0fd2b6003eb5dad1.gif",
    "gacha": "https://cdn.otakugifs.xyz/gifs/smile/c1Rkkz8X1Z.gif",
    "acoes": "https://cdn.otakugifs.xyz/gifs/hug/522c5565e52dc3c6.gif",
    "moderacao": "https://cdn.otakugifs.xyz/gifs/slap/bb9bdfcbd5c606f7.gif",
    "config": "https://cdn.otakugifs.xyz/gifs/pat/5c90b301ee64c14a.gif",
    "tickets": "https://cdn.otakugifs.xyz/gifs/wave/dd5adff27d4a281e.gif",
    "ia": "https://cdn.otakugifs.xyz/gifs/wink/hQNXqkgUq8zq.gif",
    "extras": "https://cdn.otakugifs.xyz/gifs/poke/7e68001662f53449.gif",
    "cassino": "https://cdn.otakugifs.xyz/gifs/smile/c1Rkkz8X1Z.gif",
    "comunidade": "https://cdn.otakugifs.xyz/gifs/wave/c265105164e5f6ba.gif",
}

# Cores por página (accent)
PAGE_COLORS = {
    "servidor": 0x2ECC71,
    "inicio": 0x89282B,
    "economia": 0xF1C40F,
    "gacha": 0x9B59B6,
    "acoes": 0xE91E63,
    "moderacao": 0xE74C3C,
    "config": 0x95A5A6,
    "tickets": 0x3498DB,
    "ia": 0x1ABC9C,
    "extras": 0xE67E22,
    "cassino": 0xD4AC0D,
    "comunidade": 0x8E44AD,
}

MENU_OPTIONS = [
    discord.SelectOption(
        label="Início",
        value="inicio",
        emoji="🦇",
        description="Visão geral · prefixos · ajuda",
    ),
    discord.SelectOption(
        label="Aplicação do servidor",
        value="servidor",
        emoji="🏰",
        description="Setup, tickets, níveis, checklist",
    ),
    discord.SelectOption(
        label="Economia",
        value="economia",
        emoji="💰",
        description="Souls · daily · work · ranking",
    ),
    discord.SelectOption(
        label="Loja e cassino",
        value="cassino",
        emoji="🎰",
        description="Loja de itens/cargos · apostas · roubo",
    ),
    discord.SelectOption(
        label="Coleção",
        value="gacha",
        emoji="🃏",
        description="Cartas · inventário · duelo · quiz",
    ),
    discord.SelectOption(
        label="Ações & GIFs",
        value="acoes",
        emoji="💞",
        description="Abraçar · beijar · cafuné · tapa…",
    ),
    discord.SelectOption(
        label="Moderação",
        value="moderacao",
        emoji="🛡️",
        description="Kick · ban · timeout · limpar · automod",
    ),
    discord.SelectOption(
        label="Configurações",
        value="config",
        emoji="⚙️",
        description="Boas-vindas · logs · antispam",
    ),
    discord.SelectOption(
        label="Comunidade",
        value="comunidade",
        emoji="🎉",
        description="Boas-vindas · lembretes · enquetes · aniversários",
    ),
    discord.SelectOption(
        label="Atendimento",
        value="tickets",
        emoji="🎫",
        description="Tickets · cargos · sorteios",
    ),
    discord.SelectOption(
        label="Inteligência Artificial",
        value="ia",
        emoji="🤖",
        description="Chat IA · status · gerar imagem",
    ),
    discord.SelectOption(
        label="Utilidades",
        value="extras",
        emoji="🧰",
        description="Stats · baixar · bump · ping",
    ),
]


def _build_options(selected: str) -> list[discord.SelectOption]:
    return [
        discord.SelectOption(
            label=opt.label,
            value=opt.value,
            emoji=opt.emoji,
            description=opt.description,
            default=(opt.value == selected),
        )
        for opt in MENU_OPTIONS
    ]


async def _page_embed(selected: str, guild_id: Optional[int] = None) -> discord.Embed:
    text = MENU_PAGES.get(selected, MENU_PAGES["inicio"])
    if guild_id:
        try:
            import json
            custom = json.loads((await get_config(guild_id)).get("panel_messages", "{}"))
            if isinstance(custom, dict) and isinstance(custom.get(selected), str):
                text = custom[selected]
        except (TypeError, ValueError):
            pass
    color = PAGE_COLORS.get(selected, COLOR)
    e = discord.Embed(description=text, color=color)
    e.set_footer(text=f"{FOOTER}  ·  use o menu para navegar")
    gif = MENU_GIFS.get(selected)
    if gif:
        e.set_image(url=gif)
    return e


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class HellsingMenuSelect(discord.ui.Select):
    def __init__(self, selected: str = "inicio"):
        super().__init__(
            placeholder="🦇  Escolha uma categoria…",
            min_values=1,
            max_values=1,
            options=_build_options(selected),
            custom_id="hellsing:menu:persistent_select",
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        view = HellsingMenuView(selected)
        embed = await _page_embed(selected, interaction.guild_id)
        try:
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except discord.HTTPException:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class HellsingMenuView(discord.ui.View):
    """Menu clássico com embed + GIF (persistente)."""

    def __init__(self, selected: str = "inicio"):
        super().__init__(timeout=None)
        self.add_item(HellsingMenuSelect(selected))


class HellsingMenuSelectV2(discord.ui.Select):
    def __init__(self, selected: str = "inicio"):
        super().__init__(
            placeholder="🦇  Escolha uma categoria…",
            min_values=1,
            max_values=1,
            options=_build_options(selected),
            custom_id="hellsing:menu:v2:persistent_select",
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        await interaction.response.edit_message(view=await build_menu_view(selected, interaction.guild_id))


class HellsingMenuViewV2(discord.ui.LayoutView):
    """Menu Components V2 com texto + GIF (MediaGallery) + select."""

    def __init__(self, selected: str = "inicio", guild_id: Optional[int] = None, panel_override: Optional[dict] = None):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        content = MENU_PAGES.get(selected, MENU_PAGES["inicio"])
        if panel_override and isinstance(panel_override.get(selected), str):
            content = panel_override[selected]
        accent = PAGE_COLORS.get(selected, COLOR)
        gif = MENU_GIFS.get(selected)

        children: list = [
            discord.ui.TextDisplay(content),
            discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        ]

        # GIF da página (Components V2)
        if gif:
            try:
                children.append(
                    discord.ui.MediaGallery(
                        discord.MediaGalleryItem(media=gif),
                    )
                )
                children.append(
                    discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
                )
            except Exception:
                # Fallback silencioso se a versão do discord.py não tiver MediaGallery
                pass

        children.append(discord.ui.ActionRow(HellsingMenuSelectV2(selected)))

        container = discord.ui.Container(*children, accent_color=accent)
        self.add_item(container)



async def build_menu_view(selected: str = "inicio", guild_id: Optional[int] = None):
    """Monta o menu; carrega textos custom do DB de forma async."""
    override = None
    if guild_id:
        try:
            import json
            cfg = await get_config(guild_id)
            raw = cfg.get("panel_messages") or "{}"
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, dict):
                override = data
        except Exception:
            override = None
    return HellsingMenuViewV2(selected, guild_id, override)

class Painel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(HellsingMenuView("inicio"))
        self.bot.add_view(HellsingMenuViewV2("inicio"))

    @app_commands.command(name="menu", description="Abre a central de comandos interativa Hellsing.")
    @app_commands.guild_only()
    async def menu_slash(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            view=await build_menu_view("inicio", interaction.guild_id), ephemeral=True
        )

    @app_commands.command(name="ajuda", description="Abre o menu de ajuda Hellsing.")
    @app_commands.guild_only()
    async def ajuda_slash(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            view=await build_menu_view("inicio", interaction.guild_id), ephemeral=True
        )

    @commands.command(name="menu", aliases=["painel", "comandos"])
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def menu_prefix(self, ctx: commands.Context):
        await ctx.send(view=await build_menu_view("inicio", ctx.guild.id))

    @commands.command(name="ajuda", aliases=["help"])
    @commands.guild_only()
    async def ajuda_prefix(self, ctx: commands.Context):
        await ctx.send(view=await build_menu_view("inicio", ctx.guild.id))

    @commands.command(name="ping")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def ping(self, ctx: commands.Context):
        ms = round(self.bot.latency * 1000)
        await ctx.reply(f"🏓 Pong — `{ms} ms`", mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Painel(bot))
