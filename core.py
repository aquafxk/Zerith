"""Core compartilhado: DB, embeds, constantes, helpers."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import aiosqlite
import sqlite3  # OperationalError / Row compatibility
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

def owner_ids() -> set[int]:
    """IDs do dono do bot (OWNER_ID ou OWNER_IDS no .env, separados por vírgula)."""
    raw = (os.getenv("OWNER_IDS") or os.getenv("OWNER_ID") or "").strip()
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return ids


def is_bot_owner(user_id: int) -> bool:
    return int(user_id) in owner_ids()


def xp_needed(level: int) -> int:
    """XP necessário para avançar do nível atual (progressão linear).

    A implementação anterior referenciava esta função nos Cogs, mas ela não
    existia no core.py distribuído. Mantém um contrato único para perfil,
    mensagens e recompensas de voz.
    """
    return max(100, int(level) * 100)



DB_PATH = os.getenv("DB_PATH", "hellsing.db")
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
NVIDIA_KEY = os.getenv("NVIDIA_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
POLLINATIONS_KEY = os.getenv("POLLINATIONS_KEY")
STABLE_DIFFUSION_KEY = os.getenv("STABLE_DIFFUSION_KEY")

log = logging.getLogger("hellsing")

COLOR = 0x89282B
FOOTER = "RANDOM • HELLSING"
START_TS = int(time.time())

DAILY_CD = 20 * 3600
WORK_CD = 3600
QUIZ_CD = 300
XP_CD = 60
ROLLS_PER_HOUR = 5
WARN_TIMEOUT_AT = 3
SPAM_LIMIT, SPAM_WINDOW = 6, 5
RAID_JOINS, RAID_WINDOW = 8, 15
AI_CD = 15
IMAGE_CD = 30
MENTION_CD = 20
TRADE_TIMEOUT = 60

db_file = Path(DB_PATH).expanduser()
if str(db_file.parent) not in ("", "."):
    db_file.parent.mkdir(parents=True, exist_ok=True)

# Conexão assíncrona — preenchida por init_db() no startup.
# Opera em autocommit (isolation_level=None): cada comando é gravado na hora e
# nunca fica uma transação implícita aberta segurando o lock de escrita.
db: aiosqlite.Connection | None = None

# Conexão dedicada a operações multi-etapa (troca, forja, venda, pagamento).
# Fica separada para que gravações de outras corrotinas não entrem no meio
# de uma transação nem a confirmem/desfaçam por acidente.
_tx_db: aiosqlite.Connection | None = None
_TX_LOCK = asyncio.Lock()


def get_db() -> aiosqlite.Connection:
    """Retorna a conexão ativa sem capturar o valor global antes do startup."""
    if db is None:
        raise RuntimeError("Banco ainda não inicializado; aguarde setup_hook().")
    return db

async def explain_query(sql: str, params: tuple = ()) -> list[str]:
    """Roda EXPLAIN QUERY PLAN (diagnostico; nao usar em hot path de producao)."""
    conn = get_db()
    lines: list[str] = []
    async with conn.execute(f"EXPLAIN QUERY PLAN {sql}", params) as cur:
        async for row in cur:
            lines.append(str(dict(row)))
    return lines


async def fetchone_dict(sql: str, params: tuple = ()) -> dict | None:
    """Consulta unica tipada; evita cursor vazado."""
    conn = get_db()
    async with conn.execute(sql, params) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None



_SCHEMA = """
    CREATE TABLE IF NOT EXISTS users(
        guild_id INTEGER, user_id INTEGER,
        souls INTEGER NOT NULL DEFAULT 100,
        xp INTEGER NOT NULL DEFAULT 0,
        level INTEGER NOT NULL DEFAULT 1,
        streak INTEGER NOT NULL DEFAULT 0,
        last_daily INTEGER NOT NULL DEFAULT 0,
        last_work INTEGER NOT NULL DEFAULT 0,
        last_quiz INTEGER NOT NULL DEFAULT 0,
        last_xp INTEGER NOT NULL DEFAULT 0,
        roll_window INTEGER NOT NULL DEFAULT 0,
        rolls_used INTEGER NOT NULL DEFAULT 0,
        roll_day INTEGER NOT NULL DEFAULT 0,
        rolls_today INTEGER NOT NULL DEFAULT 0,
        last_ai INTEGER NOT NULL DEFAULT 0,
        last_image INTEGER NOT NULL DEFAULT 0,
        duels_played INTEGER NOT NULL DEFAULT 0,
        duels_won INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS ai_user_profiles(
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        style_scores TEXT NOT NULL DEFAULT '{}',
        interactions INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS cards(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER, user_id INTEGER, card_key TEXT,
        level INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX IF NOT EXISTS idx_cards_owner ON cards(guild_id, user_id);
    CREATE INDEX IF NOT EXISTS idx_cards_forge ON cards(guild_id, user_id, card_key, level);
    CREATE INDEX IF NOT EXISTS idx_users_souls_rank ON users(guild_id, souls DESC);
    CREATE INDEX IF NOT EXISTS idx_users_level_rank ON users(guild_id, level DESC, xp DESC);
    CREATE TABLE IF NOT EXISTS warns(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER, user_id INTEGER, mod_id INTEGER,
        reason TEXT, ts INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_warns_user ON warns(guild_id, user_id);
    CREATE TABLE IF NOT EXISTS config(
        guild_id INTEGER PRIMARY KEY,
        welcome_channel INTEGER, log_channel INTEGER,
        antispam INTEGER NOT NULL DEFAULT 0,
        antilink INTEGER NOT NULL DEFAULT 0,
        ticket_category INTEGER,
        ticket_log INTEGER,
        ticket_staff_role INTEGER,
        setup_staff_role INTEGER,
        bump_channel INTEGER,
        bump_enabled INTEGER NOT NULL DEFAULT 0,
        bump_interval INTEGER NOT NULL DEFAULT 120,
        bump_next_at INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_config_bump_due ON config(bump_enabled, bump_next_at);
    CREATE TABLE IF NOT EXISTS level_roles(
        guild_id INTEGER, level INTEGER, role_id INTEGER,
        PRIMARY KEY (guild_id, level)
    );
    CREATE TABLE IF NOT EXISTS mod_cases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER, user_id INTEGER, mod_id INTEGER,
        action TEXT, reason TEXT, ts INTEGER
    );
    CREATE TABLE IF NOT EXISTS tickets(
        channel_id INTEGER PRIMARY KEY,
        guild_id INTEGER, user_id INTEGER, open INTEGER NOT NULL DEFAULT 1, ts INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_tickets_active ON tickets(guild_id, user_id, open);
    CREATE TABLE IF NOT EXISTS reaction_roles(
        message_id INTEGER, emoji TEXT, role_id INTEGER,
        PRIMARY KEY (message_id, emoji)
    );
    CREATE TABLE IF NOT EXISTS role_panels(
        message_id INTEGER PRIMARY KEY,
        guild_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        panel_id TEXT NOT NULL UNIQUE,
        panel_type TEXT NOT NULL CHECK(panel_type IN ('buttons', 'menu')),
        entries TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_role_panels_guild ON role_panels(guild_id);
    CREATE TABLE IF NOT EXISTS giveaways(
        message_id INTEGER PRIMARY KEY,
        channel_id INTEGER, guild_id INTEGER,
        prize TEXT, ends_at INTEGER, winners INTEGER, ended INTEGER NOT NULL DEFAULT 0
    );
    -- v3.1.0: configurações por módulo (JSON) e funções novas
    CREATE TABLE IF NOT EXISTS feature_settings(
        guild_id INTEGER NOT NULL,
        feature TEXT NOT NULL,
        data TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (guild_id, feature)
    );
    CREATE TABLE IF NOT EXISTS shop_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        price INTEGER NOT NULL,
        role_id INTEGER,
        stock INTEGER NOT NULL DEFAULT -1,
        active INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX IF NOT EXISTS idx_shop_guild ON shop_items(guild_id, active);
    CREATE TABLE IF NOT EXISTS user_items(
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        qty INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, item_id)
    );
    CREATE TABLE IF NOT EXISTS reminders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER, channel_id INTEGER, user_id INTEGER NOT NULL,
        text TEXT NOT NULL, due_at INTEGER NOT NULL, created_at INTEGER NOT NULL,
        in_channel INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(due_at);
    CREATE TABLE IF NOT EXISTS suggestions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL, channel_id INTEGER, message_id INTEGER,
        user_id INTEGER NOT NULL, text TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'aberta', staff_id INTEGER, reason TEXT, ts INTEGER
    );
    CREATE TABLE IF NOT EXISTS birthdays(
        guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        day INTEGER NOT NULL, month INTEGER NOT NULL, year INTEGER,
        last_announced INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    );
    CREATE INDEX IF NOT EXISTS idx_birthdays_date ON birthdays(guild_id, month, day);
    CREATE INDEX IF NOT EXISTS idx_tickets_channel ON tickets(channel_id);
    CREATE INDEX IF NOT EXISTS idx_tickets_open ON tickets(guild_id, open);
    CREATE INDEX IF NOT EXISTS idx_mod_cases_guild ON mod_cases(guild_id, ts);
    CREATE INDEX IF NOT EXISTS idx_suggestions_guild ON suggestions(guild_id);
    CREATE TABLE IF NOT EXISTS roll_stats(
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        week INTEGER NOT NULL,
        rolls INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, week)
    );
    CREATE INDEX IF NOT EXISTS idx_roll_stats_week ON roll_stats(guild_id, week, rolls DESC);
    CREATE TABLE IF NOT EXISTS afk(
        guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        reason TEXT NOT NULL, since INTEGER NOT NULL,
        PRIMARY KEY (guild_id, user_id)
    );
    """


async def _open_connection() -> aiosqlite.Connection:
    # isolation_level=None = autocommit; transações só com BEGIN explícito.
    # Precisa ir no connect(): o setter do aiosqlite roda fora da thread do SQLite.
    conn = await aiosqlite.connect(str(db_file), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    async with conn.execute("PRAGMA busy_timeout=5000") as cursor:
        await cursor.fetchone()
    return conn


@asynccontextmanager
async def transaction() -> AsyncIterator[aiosqlite.Connection]:
    """Transação atômica (BEGIN IMMEDIATE) em conexão dedicada.

    Com isolation_level=None, conn.in_transaction é sempre False — não dependa dele.
    """
    global _tx_db
    async with _TX_LOCK:
        if _tx_db is None:
            _tx_db = await _open_connection()
        conn = _tx_db
        await conn.execute("BEGIN IMMEDIATE")
        committed = False
        try:
            yield conn
            await conn.execute("COMMIT")
            committed = True
        except BaseException:
            if not committed:
                try:
                    await conn.execute("ROLLBACK")
                except Exception:
                    pass
            raise



async def init_db() -> aiosqlite.Connection:
    """Abre o SQLite via aiosqlite, aplica PRAGMAs (WAL, busy_timeout) e migrations."""
    global db
    if db is not None:
        return db
    conn = await _open_connection()
    try:
        for pragma in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA busy_timeout=5000",
        ):
            async with conn.execute(pragma) as cursor:
                await cursor.fetchone()
    except sqlite3.DatabaseError:
        log.exception("Não foi possível aplicar todas as otimizações do SQLite.")
        await conn.close()
        raise
    await conn.executescript(_SCHEMA)
    await conn.commit()

    try:
        await conn.execute(
            "ALTER TABLE config ADD COLUMN panel_messages TEXT NOT NULL DEFAULT '{}'"
        )
        await conn.commit()
    except sqlite3.OperationalError:
        pass

    for col, default in (
        ("last_contract", 0),
        ("last_ai", 0),
        ("last_image", 0),
        ("duels_played", 0),
        ("duels_won", 0),
        ("roll_day", 0),
        ("rolls_today", 0),
        ("last_rob", 0),
    ):
        try:
            await conn.execute(
                f"ALTER TABLE users ADD COLUMN {col} INTEGER NOT NULL DEFAULT {int(default)}"
            )
            await conn.commit()
        except sqlite3.OperationalError:
            pass

    # Colunas texto do perfil (não INTEGER)
    for col in ("fav_card", "title"):
        try:
            await conn.execute(
                f"ALTER TABLE users ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
            )
            await conn.commit()
        except sqlite3.OperationalError:
            pass

    for col, declaration in (
        ("ticket_category", "INTEGER"),
        ("ticket_log", "INTEGER"),
        ("ticket_staff_role", "INTEGER"),
        ("setup_staff_role", "INTEGER"),
        ("bump_channel", "INTEGER"),
        ("bump_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("bump_interval", "INTEGER NOT NULL DEFAULT 120"),
        ("bump_next_at", "INTEGER NOT NULL DEFAULT 0"),
        ("rules_channel", "INTEGER"),
        ("verify_role", "INTEGER"),
        ("curiosity_channel", "INTEGER"),
        ("panel_messages", "TEXT NOT NULL DEFAULT '{}'"),
        ("log_events", "INTEGER NOT NULL DEFAULT 1"),
    ):
        try:
            await conn.execute(f"ALTER TABLE config ADD COLUMN {col} {declaration}")
            await conn.commit()
        except sqlite3.OperationalError:
            pass

    # Música removida na v3.0.59: limpa a tabela antiga, se existir.
    await conn.execute("DROP TABLE IF EXISTS music_player_panels")

    db = conn
    log.info("SQLite (aiosqlite) pronto em %s", db_file)
    return conn


async def close_db() -> None:
    """PRAGMA wal_checkpoint(TRUNCATE) e fecha a conexão."""
    global db, _tx_db
    if _tx_db is not None:
        try:
            await _tx_db.close()
        except Exception:
            log.exception("Falha ao fechar a conexão de transações.")
        finally:
            _tx_db = None
    if db is None:
        return
    try:
        async with db.execute("PRAGMA wal_checkpoint(TRUNCATE)") as cursor:
            checkpoint = await cursor.fetchone()
        if checkpoint and int(checkpoint[0]) != 0:
            log.warning("WAL checkpoint terminou com busy=%s (log=%s, checkpointed=%s).", *checkpoint)
    except Exception:
        log.exception("Falha no wal_checkpoint ao encerrar.")
    try:
        await db.close()
    except Exception:
        log.exception("Falha ao fechar o banco.")
    finally:
        db = None


USER_UPDATE_FIELDS = {
    "souls", "xp", "level", "streak", "last_daily", "last_work", "last_quiz",
    "last_xp", "roll_window", "rolls_used", "roll_day", "rolls_today",
    "last_ai", "last_image", "duels_played", "duels_won", "last_contract", "last_rob", "fav_card", "title",
}

CONFIG_UPDATE_FIELDS = {
    "welcome_channel", "log_channel", "antispam", "antilink", "ticket_category",
    "ticket_log", "ticket_staff_role", "setup_staff_role", "bump_channel",
    "bump_enabled", "bump_interval", "bump_next_at", "rules_channel",
    "verify_role", "curiosity_channel", "panel_messages", "log_events",
}


async def get_user(gid: int, uid: int) -> sqlite3.Row:
    assert db is not None, "init_db() não foi chamado"
    async with db.execute(
        "INSERT OR IGNORE INTO users(guild_id, user_id) VALUES(?, ?)", (gid, uid)
    ):
        pass
    async with db.execute(
        "SELECT * FROM users WHERE guild_id=? AND user_id=?", (gid, uid)
    ) as c:
        row = await c.fetchone()
    assert row is not None
    return row


async def send_private_after_defer(
    interaction: discord.Interaction, content: str, *, deferred_ephemeral: bool = False
) -> None:
    """Envia followup privado; exige que o defer/resposta inicial já seja efêmero.

    A visibilidade da resposta original de uma interação é imutável. Apagar uma
    resposta pública não transforma o followup em privado de forma confiável.
    Portanto, os chamadores devem usar ``defer(ephemeral=True)`` antes de chamar
    este helper. A função não tenta apagar nem editar uma resposta pública.
    """
    if not deferred_ephemeral:
        raise RuntimeError(
            "Resposta privada exige defer(ephemeral=True); não é possível converter um defer público."
        )
    if not interaction.response.is_done():
        raise RuntimeError("send_private_after_defer exige defer(ephemeral=True) antes do envio.")
    await interaction.followup.send(content, ephemeral=True)


async def grant_xp(
    gid: int,
    uid: int,
    xp_gain: int,
    *,
    souls: int = 0,
    level_bonus: int = 0,
    xp_cooldown: Optional[int] = None,
) -> Optional[tuple[int, int, int]]:
    """Credita XP de forma atômica (mensagem e voz usam o mesmo caminho).

    Lê e grava dentro de uma única transação, então duas fontes de XP
    simultâneas não sobrescrevem uma à outra. Com ``xp_cooldown``, respeita e
    atualiza ``last_xp``; se o cooldown ainda não passou, retorna ``None``.
    Retorna ``(nível_antigo, nível_novo, bônus_de_souls)``.
    """
    now = int(time.time())
    async with transaction() as tx:
        await tx.execute("INSERT OR IGNORE INTO users(guild_id, user_id) VALUES(?, ?)", (gid, uid))
        async with tx.execute(
            "SELECT xp, level, last_xp FROM users WHERE guild_id=? AND user_id=?", (gid, uid)
        ) as cur:
            row = await cur.fetchone()
        if xp_cooldown is not None and now - int(row["last_xp"] or 0) < xp_cooldown:
            return None
        xp, level = int(row["xp"] or 0) + int(xp_gain), int(row["level"] or 0)
        old_level = level
        while xp >= xp_needed(level):
            xp -= xp_needed(level)
            level += 1
        bonus = level_bonus * level if level > old_level else 0
        last_xp = now if xp_cooldown is not None else int(row["last_xp"] or 0)
        await tx.execute(
            "UPDATE users SET xp=?, level=?, last_xp=?, souls=souls+? WHERE guild_id=? AND user_id=?",
            (xp, level, last_xp, int(souls) + bonus, gid, uid),
        )
    return old_level, level, bonus


async def update_user(gid: int, uid: int, **fields) -> None:
    assert db is not None, "init_db() não foi chamado"
    if not fields:
        return
    unknown = set(fields) - USER_UPDATE_FIELDS
    if unknown:
        raise ValueError(f"Campos de usuário não permitidos: {', '.join(sorted(unknown))}")
    cols = ", ".join(f"{k}=?" for k in fields)
    await db.execute(
        f"UPDATE users SET {cols} WHERE guild_id=? AND user_id=?",
        (*fields.values(), gid, uid),
    )
    await db.commit()


async def get_config(gid: int) -> dict:
    assert db is not None, "init_db() não foi chamado"
    async with db.execute("SELECT * FROM config WHERE guild_id=?", (gid,)) as c:
        row = await c.fetchone()
    if not row:
        return {
            "guild_id": gid,
            "welcome_channel": None,
            "log_channel": None,
            "rules_channel": None,
            "verify_role": None,
            "curiosity_channel": None,
            "antispam": 0,
            "antilink": 0,
            "ticket_category": None,
            "ticket_log": None,
            "ticket_staff_role": None,
            "setup_staff_role": None,
            "bump_channel": None,
            "bump_enabled": 0,
            "bump_interval": 120,
            "bump_next_at": 0,
            "panel_messages": "{}",
            "log_events": 1,
        }
    keys = row.keys()
    return {
        "guild_id": row["guild_id"],
        "welcome_channel": row["welcome_channel"],
        "log_channel": row["log_channel"],
        "antispam": row["antispam"] if "antispam" in keys else 0,
        "antilink": row["antilink"] if "antilink" in keys else 0,
        "ticket_category": row["ticket_category"] if "ticket_category" in keys else None,
        "ticket_log": row["ticket_log"] if "ticket_log" in keys else None,
        "ticket_staff_role": row["ticket_staff_role"] if "ticket_staff_role" in keys else None,
        "setup_staff_role": row["setup_staff_role"] if "setup_staff_role" in keys else None,
        "bump_channel": row["bump_channel"] if "bump_channel" in keys else None,
        "bump_enabled": row["bump_enabled"] if "bump_enabled" in keys else 0,
        "bump_interval": row["bump_interval"] if "bump_interval" in keys else 120,
        "bump_next_at": row["bump_next_at"] if "bump_next_at" in keys else 0,
        "rules_channel": row["rules_channel"] if "rules_channel" in keys else None,
        "verify_role": row["verify_role"] if "verify_role" in keys else None,
        "curiosity_channel": row["curiosity_channel"] if "curiosity_channel" in keys else None,
        "panel_messages": row["panel_messages"] if "panel_messages" in keys else "{}",
        "log_events": row["log_events"] if "log_events" in keys else 1,
    }


async def set_config(gid: int, **fields) -> None:
    assert db is not None, "init_db() não foi chamado"
    if not fields:
        return
    unknown = set(fields) - CONFIG_UPDATE_FIELDS
    if unknown:
        raise ValueError(f"Campos de configuração não permitidos: {', '.join(sorted(unknown))}")
    await db.execute("INSERT OR IGNORE INTO config(guild_id) VALUES(?)", (gid,))
    cols = ", ".join(f"{k}=?" for k in fields)
    await db.execute(
        f"UPDATE config SET {cols} WHERE guild_id=?",
        (*fields.values(), gid),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Configurações por módulo (boas-vindas, automod, cassino, social…)
# Guardadas como JSON em feature_settings e mantidas em cache na RAM.
# ---------------------------------------------------------------------------

_feature_cache: dict[tuple[int, str], dict] = {}


async def get_feature(gid: int, feature: str, defaults: Optional[dict] = None) -> dict:
    """Retorna uma cópia da configuração do módulo, já mesclada aos padrões."""
    key = (int(gid), feature)
    data = _feature_cache.get(key)
    if data is None:
        assert db is not None, "init_db() não foi chamado"
        async with db.execute(
            "SELECT data FROM feature_settings WHERE guild_id=? AND feature=?", key
        ) as c:
            row = await c.fetchone()
        try:
            data = json.loads(row["data"]) if row else {}
        except (TypeError, ValueError):
            log.warning("Configuração %s corrompida no servidor %s; usando padrão.", feature, gid)
            data = {}
        if not isinstance(data, dict):
            data = {}
        _feature_cache[key] = data
    merged = dict(defaults or {})
    merged.update(data)
    return json.loads(json.dumps(merged))  # cópia profunda: quem chama pode alterar à vontade


async def set_feature(gid: int, feature: str, **changes) -> dict:
    """Atualiza chaves da configuração do módulo e devolve o resultado salvo."""
    current = await get_feature(gid, feature)
    current.update(changes)
    assert db is not None, "init_db() não foi chamado"
    await db.execute(
        "INSERT INTO feature_settings(guild_id, feature, data) VALUES(?,?,?) "
        "ON CONFLICT(guild_id, feature) DO UPDATE SET data=excluded.data",
        (int(gid), feature, json.dumps(current, ensure_ascii=False)),
    )
    _feature_cache[(int(gid), feature)] = current
    return dict(current)


def fmt_souls(value: int) -> str:
    return f"{int(value):,}".replace(",", ".") + " Souls"


class AbuseGuard:
    """Contador em memória por (guild, user, ação) com janela em segundos."""

    def __init__(self) -> None:
        self._hits: dict[tuple[int, int, str], deque[float]] = {}

    def hit(self, guild_id: int, user_id: int, action: str, *, window: float = 60.0, limit: int = 8) -> tuple[bool, int]:
        key = (int(guild_id), int(user_id), action)
        now = time.monotonic()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > window:
            q.popleft()
        q.append(now)
        count = len(q)
        return count > limit, count


ABUSE = AbuseGuard()
ABUSE_ROLL_WINDOW = float(os.getenv("ABUSE_ROLL_WINDOW", "45") or "45")
ABUSE_ROLL_LIMIT = int(os.getenv("ABUSE_ROLL_LIMIT", "4") or "4")
ABUSE_BET_WINDOW = float(os.getenv("ABUSE_BET_WINDOW", "20") or "20")
ABUSE_BET_LIMIT = int(os.getenv("ABUSE_BET_LIMIT", "6") or "6")
ABUSE_BIG_BET = int(os.getenv("ABUSE_BIG_BET", "25000") or "25000")

_log_channel_warned: dict[int, float] = {}


async def send_log(guild: discord.Guild, embed: discord.Embed, *, file: Optional[discord.File] = None) -> bool:
    """Envia um registro ao canal de logs configurado (/config logs).

    Retorna True se enviou. Falhas de permissão são avisadas no console no
    máximo uma vez por hora por servidor, para não inundar o log.
    """
    channel_id = (await get_config(guild.id)).get("log_channel")
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return False
    me = guild.me
    perms = channel.permissions_for(me) if me else None
    if perms is None or not (perms.send_messages and perms.embed_links):
        now = time.monotonic()
        if now - _log_channel_warned.get(guild.id, -3600) >= 3600:
            _log_channel_warned[guild.id] = now
            log.warning(
                "Sem permissão (Enviar mensagens/Inserir links) no canal de logs #%s do servidor %s (%s).",
                channel, guild.name, guild.id,
            )
        return False
    try:
        if file is not None:
            await channel.send(embed=embed, file=file, allowed_mentions=discord.AllowedMentions.none())
        else:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        return True
    except discord.HTTPException as exc:
        log.warning("Falha ao enviar log no servidor %s (HTTP %s): %s", guild.id, exc.status, exc.text)
        return False


async def economy_log(
    guild: discord.Guild,
    *,
    title: str,
    description: str,
    user: Optional[discord.abc.User] = None,
) -> bool:
    """Publica evento econômico no canal de logs configurado (API Discord: channel.send)."""
    e = emb(title, description)
    e.color = 0xC4553A
    if user is not None:
        avatar = getattr(user, "display_avatar", None)
        e.set_author(name=str(user), icon_url=getattr(avatar, "url", None))
    e.timestamp = discord.utils.utcnow()
    return await send_log(guild, e)



def emb(title: str, desc: Optional[str] = None) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=COLOR)
    e.set_footer(text=FOOTER)
    return e


async def add_case(gid: int, uid: int, mod_id: int, action: str, reason: str) -> int:
    assert db is not None, "init_db() não foi chamado"
    cur = await db.execute(
        "INSERT INTO mod_cases(guild_id, user_id, mod_id, action, reason, ts) VALUES(?,?,?,?,?,?)",
        (gid, uid, mod_id, action, reason[:500], int(time.time())),
    )
    await db.commit()
    return int(cur.lastrowid)


RARITY = {
    "UR": ("⭐⭐⭐⭐⭐ [UR]", 2),
    "SSR": ("⭐⭐⭐⭐ [SSR]", 8),
    "SR": ("⭐⭐⭐ [SR]", 25),
    "R": ("⭐⭐ [R]", 65),
}

# Cores do embed por raridade
RARITY_COLOR = {
    "UR": 0xFFD700,   # dourado
    "SSR": 0x9B59B6,  # roxo
    "SR": 0x3498DB,   # azul
    "R": 0x95A5A6,    # cinza
}

# Imagens remotas: URLs de arte fornecidas no histórico do projeto.
# Se um host bloquear hotlink, defina DEFAULT_CARD_IMAGE com uma URL HTTPS própria.
DEFAULT_CARD_IMAGE = os.getenv("DEFAULT_CARD_IMAGE", "").strip()


def is_valid_image_url(url: Optional[str]) -> bool:
    if not isinstance(url, str):
        return False
    value = url.strip().lower()
    return value.startswith("https://") and len(value) <= 2048


def make_bar(value: int, maximum: int = 100, length: int = 7) -> str:
    """Barra visual segura para atributos de cartas."""
    maximum = max(1, int(maximum))
    length = max(1, min(20, int(length)))
    bounded = min(maximum, max(0, int(value)))
    filled = round((bounded / maximum) * length)
    return "▰" * filled + "▱" * (length - filled)



def pick_card_image(card: dict) -> str:
    """Sorteia um GIF/ilustração do personagem a cada exibição."""
    pool = []
    images = card.get("images")
    if isinstance(images, (list, tuple)):
        pool.extend(str(item).strip() for item in images if is_valid_image_url(str(item) if item else ""))
    primary = card.get("image")
    if is_valid_image_url(primary) and primary not in pool:
        pool.append(str(primary).strip())
    if pool:
        return random.choice(pool)
    return DEFAULT_CARD_IMAGE


def card_embed(card: dict, footer_extra: str = "") -> discord.Embed:
    """Ficha de personagem com barras visuais; atributos permanecem cosméticos."""
    rarity = card.get("rarity", "R")
    color = RARITY_COLOR.get(rarity, COLOR)
    label = RARITY.get(rarity, ("⭐", 0))[0]
    desc = str(card.get("description") or "Personagem do catálogo Hellsing.")[:900]
    atk = max(0, min(100, int(card.get("atk", 50))))
    deff = max(0, min(100, int(card.get("def", 50))))
    hp = max(0, min(300, int(card.get("hp", 100))))
    value = max(0, int(card.get("value", 0)))
    power = atk + deff + hp // 3
    stats = (
        f"⚔️ **ATK:** `{atk:>3}` `[{make_bar(atk)}]`\n"
        f"🛡️ **DEF:** `{deff:>3}` `[{make_bar(deff)}]`\n"
        f"❤️ **HP:** `{hp:>3}` `[{make_bar(hp, 300)}]`"
    )
    e = discord.Embed(
        title=f"🃏 {str(card.get('name') or 'Personagem')[:256]}",
        description=f">>> *{desc}*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    e.add_field(name="⚜️ Raridade", value=label, inline=True)
    e.add_field(name="💰 Cotação", value=f"`{value:,} Souls`".replace(",", "."), inline=True)
    e.add_field(name="⚡ Poder Geral", value=f"`{power} CP`", inline=True)
    e.add_field(name="📊 Atributos", value=stats, inline=False)
    image = pick_card_image(card)
    if is_valid_image_url(image):
        e.set_image(url=image.strip())
    e.set_footer(text=FOOTER if not footer_extra else f"{FOOTER} • {footer_extra}")
    return e


CARDS = {
    "alucard": {
        "name": 'Alucard', "rarity": 'UR', "value": 1200,
        "atk": 98, "def": 95, "hp": 300,
        "image": 'https://yourimageshare.com/ib/XoSed3ZNEq.gif',
        "images": [
            'https://yourimageshare.com/ib/XoSed3ZNEq.gif',
            'https://safebooru.org/images/1111/fc74e890d5f616444a23a85b0f2f0be9701a1437.jpg',
            'https://safebooru.org/images/598/afde5322d0a3540920f489d44bcdb89fce2bb5fc.jpg',
            'https://safebooru.org/images/598/d470047f974c14074ab1d56acfed28aec2a20c6c.jpg',
        ],
        "description": 'O vampiro lendário e principal agente da Organização Hellsing.',
    },
    "seras": {
        "name": 'Seras Victoria', "rarity": 'SSR', "value": 550,
        "atk": 82, "def": 78, "hp": 220,
        "image": 'https://yourimageshare.com/ib/lSyGldPF3E.gif',
        "images": [
            'https://yourimageshare.com/ib/lSyGldPF3E.gif',
            'https://safebooru.org/images/1111/5a6902e7c963eefa83f3923add3dff992c5f93e2.jpg',
            'https://safebooru.org/images/599/9f356cfeeccf6adeaa2cb97a896f834752db2fb9.jpg',
            'https://safebooru.org/images/599/86a5110d3b04584715c141ad318af939a29d2d0e.jpg',
        ],
        "description": 'Integrante da Organização Hellsing e companheira de Alucard.',
    },
    "anderson": {
        "name": 'Alexander Anderson', "rarity": 'SSR', "value": 520,
        "atk": 88, "def": 84, "hp": 240,
        "image": 'https://yourimageshare.com/ib/jJNSsmRZFj.gif',
        "images": [
            'https://yourimageshare.com/ib/jJNSsmRZFj.gif',
            'https://safebooru.org/images/340/b16f8fa719e900cf7b5618efc9dac05033dff79d.jpg',
            'https://safebooru.org/images/3921/b5a35a20cfccc37f0ab3b7995c274f90984299e4.jpg',
            'https://safebooru.org/images/1096/c0e07959bde4688c1fdf31312e809f002294d07a.jpg',
        ],
        "description": 'Membro da Seção XIII Iscariot.',
    },
    "integra": {
        "name": 'Sir Integra Hellsing', "rarity": 'SSR', "value": 480,
        "atk": 65, "def": 80, "hp": 180,
        "image": 'https://yourimageshare.com/ib/Ki9IJ52xDP.gif',
        "images": [
            'https://yourimageshare.com/ib/Ki9IJ52xDP.gif',
            'https://safebooru.org/images/598/eae07a02c9b56ac90d67f7130e18a9450079e28e.jpg',
            'https://safebooru.org/images/595/244ccbe0aad6f1949d29a3f4deb8f1dc927402a3.jpg',
            'https://safebooru.org/images/1351/4a4bbf5bdc424b5b9ad4f69a2ada14e94ccdf520.jpg',
        ],
        "description": 'Líder da Organização Hellsing.',
    },
    "major": {
        "name": 'O Major', "rarity": 'SSR', "value": 470,
        "atk": 70, "def": 60, "hp": 160,
        "image": 'https://yourimageshare.com/ib/fSLZChORxn.gif',
        "images": [
            'https://yourimageshare.com/ib/fSLZChORxn.gif',
            'https://safebooru.org/images/1607/2a9c1a6c9007435f51bb17566d451e725a9284ed.jpg',
            'https://safebooru.org/images/574/2cb394303ca0feda0f063da2ab2062805ed74e08.jpg',
            'https://safebooru.org/images/3883/92705488d5b121b624884a51ef2e1419ca788a37.png',
        ],
        "description": 'Líder do grupo Millennium.',
    },
    "walter": {
        "name": 'Walter C. Dornez', "rarity": 'SR', "value": 280,
        "atk": 74, "def": 62, "hp": 150,
        "image": 'https://yourimageshare.com/ib/NpvWUUPIb8.gif',
        "images": [
            'https://yourimageshare.com/ib/NpvWUUPIb8.gif',
            'https://safebooru.org/images/850/cd05af3c0c90d958622e8279686ebc1872901249.jpg',
            'https://safebooru.org/images/1614/30468b53754646be84a6f5e19a18bb97772277f4.jpg',
            'https://safebooru.org/images/3661/22ae7731df2fa1fb69f58803e367f514ed0dfa68.jpg',
        ],
        "description": 'Mordomo da Mansão Hellsing, conhecido como Anjo da Morte.',
    },
    "pip": {
        "name": 'Pip Bernadotte', "rarity": 'SR', "value": 240,
        "atk": 66, "def": 58, "hp": 140,
        "image": 'https://yourimageshare.com/ib/AtyEMjRp94.gif',
        "images": [
            'https://yourimageshare.com/ib/AtyEMjRp94.gif',
            'https://safebooru.org/images/1469/83eaf6eb294a7d1f75dc7b0462276c16.jpeg',
            'https://safebooru.org/images/966/207f4a9491e8002f43b39248ac376fd74b6a5d7e.jpg',
            'https://safebooru.org/images/927/b2e3626929ae4d49b3c4b2905fdb1c28906af0ba.jpg',
        ],
        "description": 'Líder dos mercenários Wild Geese.',
    },
    "hans": {
        "name": 'Capitão Hans Günsche', "rarity": 'SR', "value": 260,
        "atk": 76, "def": 75, "hp": 190,
        "image": 'https://yourimageshare.com/ib/ZcdQP8pfDB.gif',
        "images": [
            'https://yourimageshare.com/ib/ZcdQP8pfDB.gif',
            'https://safebooru.org/images/1351/2bd094b46fe95b2e165c42b3848fc8db7857b2a2.png',
            'https://safebooru.org/images/3883/92705488d5b121b624884a51ef2e1419ca788a37.png',
            'https://safebooru.org/images/269/9882ef9d36516882255afddc65b52daa24aa0940.png',
        ],
        "description": 'Integrante do grupo Millennium.',
    },
    "rip": {
        "name": 'Rip van Winkle', "rarity": 'R', "value": 140,
        "atk": 56, "def": 45, "hp": 120,
        "image": 'https://yourimageshare.com/ib/I30rxGj6qR.gif',
        "images": [
            'https://yourimageshare.com/ib/I30rxGj6qR.gif',
            'https://safebooru.org/images/1101/e843a7151fa22b15f3348911f8c2aca2879ef738.jpg',
            'https://safebooru.org/images/1100/8ec8fd154c76d2084bc2268a7165310e44a9b0dd.jpg',
            'https://safebooru.org/images/4423/317cc60923aec831dd59f7b63f1f6f3732d88c87.jpg',
        ],
        "description": 'Integrante do Millennium.',
    },
    "schrodinger": {
        "name": 'Schrödinger', "rarity": 'R', "value": 160,
        "atk": 40, "def": 85, "hp": 130,
        "image": 'https://yourimageshare.com/ib/ax8bA96xWm.gif',
        "images": [
            'https://yourimageshare.com/ib/ax8bA96xWm.gif',
            'https://safebooru.org/images/4421/5ce18861ebce1e439441101c7b92eb077a1393c5.png',
            'https://safebooru.org/images/4307/740dcd1a29fabc7e40be459655b60f05f7377ab5.jpg',
            'https://safebooru.org/images/3499/59dc24ff8bb8c56c2d763f52a17bb921be296402.jpg',
        ],
        "description": 'Personagem associado ao Millennium.',
    },
    "luke": {
        "name": 'Luke Valentine', "rarity": 'R', "value": 120,
        "atk": 58, "def": 42, "hp": 110,
        "image": 'https://yourimageshare.com/ib/g1aciAoanw.gif',
        "images": [
            'https://yourimageshare.com/ib/g1aciAoanw.gif',
            'https://safebooru.org/images/1083/84af980fc55cea2cfbb09a01211b430cfa0fd44c.jpg',
            'https://safebooru.org/images/272/4a664699b961a177a6762e95544b5f57bc905ccd.jpg',
            'https://safebooru.org/images/4620/c9ec0774c557d33c6c3f3173ee48b0cf7c203e41.png',
        ],
        "description": 'Um dos irmãos Valentine.',
    },
    "jan": {
        "name": 'Jan Valentine', "rarity": 'R', "value": 115,
        "atk": 57, "def": 39, "hp": 110,
        "image": 'https://yourimageshare.com/ib/crAGYCF2Xr.gif',
        "images": [
            'https://yourimageshare.com/ib/crAGYCF2Xr.gif',
            'https://safebooru.org/images/272/4a664699b961a177a6762e95544b5f57bc905ccd.jpg',
            'https://safebooru.org/images/4620/c9ec0774c557d33c6c3f3173ee48b0cf7c203e41.png',
            'https://safebooru.org/images/1544/b13e91d7cd529510c5ffc7064b70bb72833fc019.png',
        ],
        "description": 'Um dos irmãos Valentine.',
    },
    "zorin": {
        "name": 'Zorin Blitz', "rarity": 'SR', "value": 275,
        "atk": 79, "def": 68, "hp": 175,
        "image": 'https://safebooru.org/images/4620/c9ec0774c557d33c6c3f3173ee48b0cf7c203e41.png',
        "images": [
            'https://safebooru.org/images/4620/c9ec0774c557d33c6c3f3173ee48b0cf7c203e41.png',
            'https://safebooru.org/images/1544/b13e91d7cd529510c5ffc7064b70bb72833fc019.png',
            'https://safebooru.org/images/3584/58c11cc5fa7f6ad3fe4ab39b2e54a2aef66c0735.jpg',
            'https://safebooru.org/images/4619/ce5a35c7cdba546b400428c011f817c026a8d339.jpg',
        ],
        "description": 'Integrante da Millennium, conhecida por suas habilidades de ilusão.',
    },
    "tubalcain": {
        "name": 'Tubalcain Alhambra', "rarity": 'SR', "value": 265,
        "atk": 77, "def": 65, "hp": 165,
        "image": 'https://safebooru.org/images/4154/1b018aea66d47942d51e6ceffa86d18ae31f02db.jpg',
        "images": [
            'https://safebooru.org/images/4154/1b018aea66d47942d51e6ceffa86d18ae31f02db.jpg',
            'https://safebooru.org/images/4620/c9ec0774c557d33c6c3f3173ee48b0cf7c203e41.png',
            'https://safebooru.org/images/1544/b13e91d7cd529510c5ffc7064b70bb72833fc019.png',
            'https://safebooru.org/images/4619/28aa774862b9595f9bb1bbe92960897a452feaf5.jpg',
        ],
        "description": 'Agente da Millennium conhecido como Dandy Man.',
    },
    "the_captain": {
        "name": 'O Capitão', "rarity": 'SSR', "value": 490,
        "atk": 91, "def": 92, "hp": 260,
        "image": 'https://safebooru.org/images/1351/2bd094b46fe95b2e165c42b3848fc8db7857b2a2.png',
        "images": [
            'https://safebooru.org/images/1351/2bd094b46fe95b2e165c42b3848fc8db7857b2a2.png',
            'https://safebooru.org/images/3883/92705488d5b121b624884a51ef2e1419ca788a37.png',
            'https://safebooru.org/images/269/9882ef9d36516882255afddc65b52daa24aa0940.png',
            'https://safebooru.org/images/4620/e56cfa954cae62e1ba1a043888cbd0898aa94015.png',
        ],
        "description": 'O silencioso e poderoso membro da Millennium.',
    },
    "maxwell": {
        "name": 'Enrico Maxwell', "rarity": 'R', "value": 150,
        "atk": 48, "def": 55, "hp": 125,
        "image": 'https://safebooru.org/images/11/389b3df12e28fb5db91a648c73e1c5eee99c5466.png',
        "images": [
            'https://safebooru.org/images/11/389b3df12e28fb5db91a648c73e1c5eee99c5466.png',
            'https://safebooru.org/images/4362/251dc43f92a77ace26bd4be36e62435cbb981dcb.png',
            'https://safebooru.org/images/4362/3d7d1064bcf7165bf36b542b919d2f4ca413ca38.jpg',
            'https://safebooru.org/images/4362/3ed2641414d839b234792fe58b9f346fd1ead544.jpg',
        ],
        "description": 'Líder da organização Iscariot.',
    },
    "heinkel": {
        "name": 'Heinkel Wolfe', "rarity": 'SR', "value": 250,
        "atk": 72, "def": 70, "hp": 155,
        "image": 'https://safebooru.org/images/1292/5e4190ff27c52892fe8f2be41579571432966870.jpg',
        "images": [
            'https://safebooru.org/images/1292/5e4190ff27c52892fe8f2be41579571432966870.jpg',
            'https://safebooru.org/images/4362/fc0514d8e47f99df6aab0fe15538f0f0acf207b9.png',
            'https://safebooru.org/images/4362/95c27b1911491a828ea5cf8af78af6b285e75102.png',
            'https://safebooru.org/images/4362/251dc43f92a77ace26bd4be36e62435cbb981dcb.png',
        ],
        "description": 'Integrante da Seção XIII Iscariot.',
    },
    "yumie": {
        "name": 'Yumie Takagi', "rarity": 'R', "value": 145,
        "atk": 63, "def": 52, "hp": 120,
        "image": 'https://safebooru.org/images/1781/33d373281fb99ea4cdce3df398e95405eeb14e67.jpg',
        "images": [
            'https://safebooru.org/images/1781/33d373281fb99ea4cdce3df398e95405eeb14e67.jpg',
            'https://safebooru.org/images/876/9f8eba3f70c86b5aa527600a1cf3adc22709b57e.jpg',
            'https://safebooru.org/images/812/a8315992ae5f04dc4ea772c23497ac52651b36ac.jpg',
            'https://safebooru.org/images/812/dd43817691c7ed9d0250cdd2ff7aea36fd331659.png',
        ],
        "description": 'Integrante da Seção XIII Iscariot.',
    },
}

JOBS = [
    "caçou ghouls nos subúrbios de Londres",
    "poliu as armas de prata da Mansão",
    "auxiliou Sir Integra numa reunião de emergência",
    "patrulhou o perímetro contra a Millennium",
    "escoltou um carregamento de munição consagrada",
]

QUIZ = [
    ("Qual pistola de Alucard dispara balas de 13 mm?", "Jackal", ["Dominator", "Murasame", "Harkonnen"]),
    ("Qual era a profissão de Seras Victoria antes de virar vampira?", "Policial", ["Médica", "Professora", "Estudante"]),
    ("Qual é a organização inimiga principal em Hellsing Ultimate?", "Millennium", ["Akatsuki", "Espada", "Phantom Troupe"]),
    ("Quem é o mordomo dos Hellsing, conhecido como Anjo da Morte?", "Walter C. Dornez", ["Pip Bernadotte", "Alexander Anderson", "Hans Günsche"]),
    ("A qual organização pertence o padre Alexander Anderson?", "Iscariot (Seção XIII)", ["Millennium", "Wild Geese", "Round Table"]),
    ("Qual é o nome do canhão usado por Seras Victoria?", "Harkonnen", ["Jackal", "Panzerfaust", "Excalibur"]),
    ("Qual é o título do líder da Millennium?", "O Major", ["O Conde", "O Barão", "O Duque"]),
]

spam_log = defaultdict(lambda: deque(maxlen=10))
join_log = defaultdict(lambda: deque(maxlen=RAID_JOINS))
