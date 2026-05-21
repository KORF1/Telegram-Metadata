# =====================
# IMPORTS
# =====================
import asyncio
import json
import random
import re
from collections import defaultdict, Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from langdetect import detect

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import (
    ChannelParticipantsAdmins,
    ChannelParticipantsRecent,
    MessageEntityTextUrl,
    MessageEntityUrl,
)

# Optional translation support
ENABLE_TRANSLATION = False
TRANSLATE_TO = "en"
try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except Exception:
    TRANSLATOR_AVAILABLE = False


# =====================
# CONFIG
# =====================
api_id = ADD HERE
api_hash = 'ADD HERE'
session_name = 'tg_session'
TARGETS_FILE = 'chinanscc.txt'  # your handle file


MESSAGE_LIMIT = 300
ADMIN_LIMIT = 25
MEMBER_LIMIT = 5000

# Date-range message depth. Leave dates as None to use MESSAGE_LIMIT only.
# Accepted examples: "2025-01-01", "2025-01-01T00:00:00Z", "2025-01-01 00:00:00".
MESSAGE_START_DATE = None
MESSAGE_END_DATE = None
# When a start date is set, keep walking backward until that date even if MESSAGE_LIMIT is reached.
MESSAGE_DEPTH_BY_DATE_RANGE = True
# Safety cap for date-range collection. Set to None for no explicit cap.
MESSAGE_DATE_RANGE_MAX_MESSAGES = 5000

MESSAGE_SLEEP_MIN = 8
MESSAGE_SLEEP_MAX = 15

RESOLVE_SLEEP_MIN = 45
RESOLVE_SLEEP_MAX = 75

LOCAL_TZ_NAME = "America/New_York"
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)

DETECT_MESSAGE_LANGUAGE = True
MAX_TEXT_CHARS_FOR_LANG = 500
INCLUDE_MESSAGE_TEXT = True
EXTRACT_URLS = True
INCLUDE_FORWARD_ORIGIN = True
INCLUDE_MEDIA_METADATA = True

ENABLE_MEMBER_ENUM = True
ENABLE_REPLY_GRAPH = True
ENABLE_TOP_POSTERS = True
INCLUDE_VIEWS_FORWARDS = True

# Bot enrichment
ENABLE_USERINFOBOT = True
ENABLE_SANGMATA = True
USERINFO_BOT = "userinfobot"
SANGMATA_BOT = "SangMataInfo_bot"

BOT_SLEEP_MIN = 8
BOT_SLEEP_MAX = 14

# =====================
# DISCOVERED-ID ENRICHMENT CONFIG
# =====================
ENABLE_DISCOVERED_ID_ENRICHMENT = True

# Keep this conservative
DISCOVERED_ENRICHMENT_LIMIT = 100

# Prioritization
MIN_TARGET_OVERLAP_FOR_ENRICH = 2
MIN_MESSAGES_FOR_ENRICH = 3
PRIORITIZE_WATCHLIST = True
PRIORITIZE_MULTI_TARGET = True
PRIORITIZE_TOP_POSTERS = True

# Slow bot pacing
DISCOVERED_BOT_SLEEP_MIN = 20
DISCOVERED_BOT_SLEEP_MAX = 40

# Save progress as you go
BOT_ENRICHMENT_OUTPUT = "bot_enrichment.csv"
BOT_ENRICHMENT_CHECKPOINT_EVERY = 10


# =====================
# HELPERS
# =====================
def load_handles(path):
    targets = []
    watchlist = set()

    with open(path, encoding="utf-8") as f:
        for line in f:
            clean = line.strip().replace("\xa0", "").replace("\u200b", "")
            if not clean:
                continue

            if "t.me/" in clean:
                clean = clean.split("/")[-1].split("?")[0]

            if clean.isdigit():
                val = int(clean)
                targets.append(val)
                watchlist.add(val)
            else:
                if not clean.startswith("@"):
                    clean = "@" + clean
                targets.append(clean.lower())

    targets = list(dict.fromkeys(targets))
    return targets, watchlist


def safe_detect_language(text):
    if not text:
        return None
    sample = text.strip()[:MAX_TEXT_CHARS_FOR_LANG]
    try:
        return detect(sample)
    except Exception:
        return None


def maybe_translate(text, detected_lang):
    if (
        not ENABLE_TRANSLATION
        or not TRANSLATOR_AVAILABLE
        or not text
        or not detected_lang
        or detected_lang.lower() == TRANSLATE_TO.lower()
    ):
        return None
    try:
        return GoogleTranslator(source="auto", target=TRANSLATE_TO).translate(text)
    except Exception:
        return None


async def sleep_jitter(min_s, max_s):
    await asyncio.sleep(random.uniform(min_s, max_s))


def normalize_username(username):
    if not username:
        return None
    return username.lower().lstrip("@")


def normalize_target_value(value):
    v = str(value).strip()
    if "t.me/" in v:
        v = v.split("/")[-1].split("?")[0]
    if v.startswith("@"):
        return v.lower()
    if v.lstrip("-").isdigit():
        return v
    return "@" + v.lower()


def parse_config_datetime(value, tz=timezone.utc):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def json_dumps_safe(value):
    if value in (None, [], {}, ""):
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def extract_urls_from_message(msg, text):
    urls = []
    seen = set()

    def add_url(url, source, display_text=None):
        if not url:
            return
        clean = str(url).strip()
        if not clean or clean in seen:
            return
        seen.add(clean)
        urls.append({
            "url": clean,
            "source": source,
            "display_text": display_text,
        })

    if text:
        for match in re.finditer(r"(?i)\b(?:https?://|www\.)[^\s<>()]+", text):
            add_url(match.group(0).rstrip('.,;:!?)\"]\''), "regex")

    for entity in getattr(msg, "entities", None) or []:
        try:
            offset = getattr(entity, "offset", 0)
            length = getattr(entity, "length", 0)
            entity_text = text[offset:offset + length] if text is not None else None

            if isinstance(entity, MessageEntityTextUrl):
                add_url(getattr(entity, "url", None), "text_url_entity", entity_text)
            elif isinstance(entity, MessageEntityUrl):
                add_url(entity_text, "url_entity")
        except Exception:
            continue

    return urls


def get_forward_origin_metadata(msg):
    fwd = getattr(msg, "fwd_from", None)
    if not fwd:
        return {}

    from_id = getattr(fwd, "from_id", None)
    from_id_value = None
    if from_id is not None:
        from_id_value = getattr(from_id, "user_id", None) or getattr(from_id, "channel_id", None) or str(from_id)

    saved_from_peer = getattr(fwd, "saved_from_peer", None)
    saved_from_peer_value = None
    if saved_from_peer is not None:
        saved_from_peer_value = (
            getattr(saved_from_peer, "user_id", None)
            or getattr(saved_from_peer, "channel_id", None)
            or getattr(saved_from_peer, "chat_id", None)
            or str(saved_from_peer)
        )

    fwd_date = getattr(fwd, "date", None)
    if fwd_date:
        fwd_date = fwd_date.astimezone(timezone.utc)

    return {
        "is_forwarded": True,
        "forward_date_utc": fwd_date,
        "forward_from_id": from_id_value,
        "forward_from_name": getattr(fwd, "from_name", None),
        "forward_channel_post": getattr(fwd, "channel_post", None),
        "forward_post_author": getattr(fwd, "post_author", None),
        "forward_saved_from_peer_id": saved_from_peer_value,
        "forward_saved_from_msg_id": getattr(fwd, "saved_from_msg_id", None),
        "forward_psa_type": getattr(fwd, "psa_type", None),
    }


def get_media_metadata(msg):
    media = getattr(msg, "media", None)
    document = getattr(msg, "document", None)
    photo = getattr(msg, "photo", None)
    webpage = getattr(msg, "web_preview", None) or getattr(media, "webpage", None)

    info = {
        "has_media": bool(media),
        "media_type": type(media).__name__ if media else None,
        "mime_type": getattr(document, "mime_type", None) if document else None,
        "file_name": None,
        "file_size": getattr(document, "size", None) if document else None,
        "duration_seconds": None,
        "width": None,
        "height": None,
        "photo_id": getattr(photo, "id", None) if photo else None,
        "document_id": getattr(document, "id", None) if document else None,
        "sticker_alt": None,
        "webpage_url": getattr(webpage, "url", None) if webpage else None,
        "webpage_display_url": getattr(webpage, "display_url", None) if webpage else None,
        "webpage_title": getattr(webpage, "title", None) if webpage else None,
        "webpage_site_name": getattr(webpage, "site_name", None) if webpage else None,
        "media_attributes_json": None,
    }

    attrs_out = []
    for attr in getattr(document, "attributes", None) or []:
        attr_name = type(attr).__name__
        attr_row = {"type": attr_name}
        for key in ("file_name", "duration", "w", "h", "round_message", "voice", "alt", "stickerset"):
            if hasattr(attr, key):
                attr_row[key] = getattr(attr, key)
        attrs_out.append(attr_row)

        if hasattr(attr, "file_name"):
            info["file_name"] = getattr(attr, "file_name", None)
        if hasattr(attr, "duration"):
            info["duration_seconds"] = getattr(attr, "duration", None)
        if hasattr(attr, "w"):
            info["width"] = getattr(attr, "w", None)
        if hasattr(attr, "h"):
            info["height"] = getattr(attr, "h", None)
        if hasattr(attr, "alt"):
            info["sticker_alt"] = getattr(attr, "alt", None)

    info["media_attributes_json"] = json_dumps_safe(attrs_out)
    return info


def should_keep_message_by_date(msg_dt_utc, start_dt_utc, end_dt_utc):
    if not msg_dt_utc:
        return True
    if end_dt_utc and msg_dt_utc > end_dt_utc:
        return False
    if start_dt_utc and msg_dt_utc < start_dt_utc:
        return False
    return True


def build_iter_messages_kwargs():
    start_dt_utc = parse_config_datetime(MESSAGE_START_DATE)
    end_dt_utc = parse_config_datetime(MESSAGE_END_DATE)

    if MESSAGE_DEPTH_BY_DATE_RANGE and start_dt_utc:
        limit = MESSAGE_DATE_RANGE_MAX_MESSAGES
    else:
        limit = MESSAGE_LIMIT

    kwargs = {"limit": limit}
    if end_dt_utc:
        kwargs["offset_date"] = end_dt_utc

    return kwargs, start_dt_utc, end_dt_utc


async def get_first_post_date(client, entity, limit=1):
    try:
        async for msg in client.iter_messages(entity, limit=limit, reverse=True):
            if msg and msg.date:
                return msg.date.astimezone(timezone.utc)
    except Exception:
        return None
    return None


async def enumerate_members(client, entity, target_value, watchlist):
    rows = []
    offset = 0

    while offset < MEMBER_LIMIT:
        batch_limit = min(200, MEMBER_LIMIT - offset)

        result = await client(GetParticipantsRequest(
            channel=entity,
            filter=ChannelParticipantsRecent(),
            offset=offset,
            limit=batch_limit,
            hash=0
        ))

        users = getattr(result, "users", []) or []
        if not users:
            break

        for user in users:
            rows.append({
                "target": str(target_value),
                "user_id": user.id,
                "username": normalize_username(user.username),
                "first_name": user.first_name,
                "last_name": user.last_name,
                "bot": getattr(user, "bot", None),
                "verified": getattr(user, "verified", None),
                "scam": getattr(user, "scam", None),
                "fake": getattr(user, "fake", None),
                "is_watchlisted": user.id in watchlist
            })

        offset += len(users)

        if len(users) < batch_limit:
            break

    return rows


async def ask_bot(client, bot_username, message):
    async with client.conversation(bot_username, timeout=45) as conv:
        await conv.send_message(message)
        resp = await conv.get_response()
        return (resp.raw_text or "").strip()


def parse_userinfobot(text):
    import re

    result = {
        "provider": "userinfobot",
        "raw_response": text,
        "resolved_id": None,
        "first_name": None,
        "last_name": None,
        "username": None,
        "language_code": None,
    }

    patterns = {
        "resolved_id": r"(?:id|user id)\s*[:#-]?\s*([0-9-]+)",
        "first_name": r"(?:first name)\s*[:#-]?\s*(.+)",
        "last_name": r"(?:last name)\s*[:#-]?\s*(.+)",
        "username": r"(?:username)\s*[:#-]?\s*@?([A-Za-z0-9_]{3,})",
        "language_code": r"(?:language)\s*[:#-]?\s*([A-Za-z_-]+)",
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, text or "", flags=re.IGNORECASE)
        if m:
            result[key] = m.group(1).strip()

    return result


def parse_sangmata(text):
    import re

    result = {
        "provider": "sangmata",
        "raw_response": text,
        "resolved_id": None,
        "username": None,
        "name_history": [],
        "username_history": [],
    }

    id_match = re.search(r"(?:id|user id)\s*[:#-]?\s*([0-9-]+)", text or "", flags=re.IGNORECASE)
    if id_match:
        result["resolved_id"] = id_match.group(1).strip()

    username_match = re.search(r"(?:username)\s*[:#-]?\s*@?([A-Za-z0-9_]{3,})", text or "", flags=re.IGNORECASE)
    if username_match:
        result["username"] = username_match.group(1).strip().lower()

    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        s_low = s.lower()
        if "@" in s:
            result["username_history"].append(s)
        elif "name" in s_low:
            result["name_history"].append(s)

    result["name_history"] = list(dict.fromkeys(result["name_history"]))
    result["username_history"] = list(dict.fromkeys(result["username_history"]))
    return result


def total_messages_for_user(user_id, user_message_counts):
    total = 0
    for (uid, _target), count in user_message_counts.items():
        if uid == user_id:
            total += count
    return total


def load_already_enriched_ids(path):
    try:
        df = pd.read_csv(path)
        if "lookup_user_id" not in df.columns:
            return set()
        return set(
            int(x) for x in df["lookup_user_id"].dropna().tolist()
            if str(x).lstrip("-").isdigit()
        )
    except Exception:
        return set()


def build_discovered_enrichment_queue(
    all_user_ids,
    watchlist,
    user_targets,
    user_message_counts,
    user_map,
    limit=None
):
    candidates = []

    for uid in all_user_ids:
        targets_seen = user_targets.get(uid, set())
        target_count = len(targets_seen)
        message_total = total_messages_for_user(uid, user_message_counts)

        if target_count < MIN_TARGET_OVERLAP_FOR_ENRICH and message_total < MIN_MESSAGES_FOR_ENRICH:
            continue

        score = 0
        if PRIORITIZE_WATCHLIST and uid in watchlist:
            score += 1000
        if PRIORITIZE_MULTI_TARGET and target_count > 1:
            score += 100 + (target_count * 10)
        if PRIORITIZE_TOP_POSTERS:
            score += message_total

        candidates.append({
            "lookup_user_id": uid,
            "current_username": user_map.get(uid),
            "target_count": target_count,
            "message_total": message_total,
            "score": score
        })

    candidates = sorted(
        candidates,
        key=lambda x: (x["score"], x["target_count"], x["message_total"], x["lookup_user_id"]),
        reverse=True
    )

    if limit:
        candidates = candidates[:limit]

    return candidates


async def enrich_single_user_id_with_bots(client, user_id):
    rows = []

    if ENABLE_USERINFOBOT:
        try:
            reply = await ask_bot(client, USERINFO_BOT, str(user_id))
            parsed = parse_userinfobot(reply)
            parsed["lookup_user_id"] = user_id
            parsed["lookup_type"] = "discovered_user_id"
            rows.append(parsed)
        except FloodWaitError as e:
            rows.append({
                "provider": "userinfobot",
                "lookup_user_id": user_id,
                "lookup_type": "discovered_user_id",
                "raw_response": None,
                "resolved_id": None,
                "first_name": None,
                "last_name": None,
                "username": None,
                "language_code": None,
                "error": f"Flood wait: {e.seconds}s"
            })
        except Exception as e:
            rows.append({
                "provider": "userinfobot",
                "lookup_user_id": user_id,
                "lookup_type": "discovered_user_id",
                "raw_response": None,
                "resolved_id": None,
                "first_name": None,
                "last_name": None,
                "username": None,
                "language_code": None,
                "error": str(e)
            })

        await sleep_jitter(DISCOVERED_BOT_SLEEP_MIN, DISCOVERED_BOT_SLEEP_MAX)

    if ENABLE_SANGMATA:
        try:
            reply = await ask_bot(client, SANGMATA_BOT, f"/search_id {user_id}")
            parsed = parse_sangmata(reply)
            parsed["lookup_user_id"] = user_id
            parsed["lookup_type"] = "discovered_user_id"
            parsed["name_history"] = " | ".join(parsed.get("name_history", []))
            parsed["username_history"] = " | ".join(parsed.get("username_history", []))
            rows.append(parsed)
        except FloodWaitError as e:
            rows.append({
                "provider": "sangmata",
                "lookup_user_id": user_id,
                "lookup_type": "discovered_user_id",
                "raw_response": None,
                "resolved_id": None,
                "username": None,
                "name_history": None,
                "username_history": None,
                "error": f"Flood wait: {e.seconds}s"
            })
        except Exception as e:
            rows.append({
                "provider": "sangmata",
                "lookup_user_id": user_id,
                "lookup_type": "discovered_user_id",
                "raw_response": None,
                "resolved_id": None,
                "username": None,
                "name_history": None,
                "username_history": None,
                "error": str(e)
            })

        await sleep_jitter(DISCOVERED_BOT_SLEEP_MIN, DISCOVERED_BOT_SLEEP_MAX)

    return rows


# =====================
# MAIN
# =====================
async def main():
    targets, watchlist = load_handles(TARGETS_FILE)

    print(f"[+] Loaded {len(targets)} targets")
    print(f"[DEBUG] Sample targets: {targets[:10]}")

    admin_rows = []
    member_rows = []
    message_rows = []
    status_rows = []
    target_metadata_rows = []
    bot_enrichment_rows = []

    user_map = {}
    user_first_seen_utc = {}
    user_first_seen_local = {}

    usernames_by_user = {}
    user_targets = {}
    user_message_counts = {}
    entity_cache = {}

    reply_edges_rows = []
    reply_summary_counter = Counter()
    translated_message_rows = []
    extracted_url_rows = []

    per_target_message_sender = defaultdict(dict)

    async with TelegramClient(session_name, api_id, api_hash) as client:
        me = await client.get_me()
        print(f"[✓] Logged in as {me.username or me.id}")

        for idx, target in enumerate(targets, start=1):
            print(f"\n[+] Processing {target} ({idx}/{len(targets)})")

            admin_count = 0
            member_count = 0
            message_count = 0
            admin_access = False
            member_access = False
            message_access = False
            entity_type = None
            error_msg = None
            message_error = None

            # ---- RESOLVE ----
            try:
                if target in entity_cache:
                    entity = entity_cache[target]
                    print(f"[DEBUG] Cache hit for {target}")
                else:
                    entity = await client.get_entity(target)
                    entity_cache[target] = entity
                    await sleep_jitter(RESOLVE_SLEEP_MIN, RESOLVE_SLEEP_MAX)

                entity_type = type(entity).__name__
                print(f"[DEBUG] Resolved {target} as {entity_type}")

            except FloodWaitError as e:
                error_msg = f"Flood wait during resolve: {e.seconds}s"
                print(f"[-] {error_msg}")
                status_rows.append({
                    "target": str(target),
                    "resolved": False,
                    "entity_type": None,
                    "admin_access": False,
                    "admin_count": 0,
                    "member_access": False,
                    "member_count": 0,
                    "message_access": False,
                    "message_count": 0,
                    "error": error_msg
                })
                continue

            except Exception as e:
                error_msg = str(e)
                print(f"[-] Resolve failed: {e}")
                status_rows.append({
                    "target": str(target),
                    "resolved": False,
                    "entity_type": None,
                    "admin_access": False,
                    "admin_count": 0,
                    "member_access": False,
                    "member_count": 0,
                    "message_access": False,
                    "message_count": 0,
                    "error": error_msg
                })
                continue

            # ---- TARGET METADATA ----
            first_post_date_utc = await get_first_post_date(client, entity)
            target_metadata_rows.append({
                "target": str(target),
                "entity_id": getattr(entity, "id", None),
                "access_hash": getattr(entity, "access_hash", None),
                "entity_type": entity_type,
                "title": getattr(entity, "title", None),
                "username": normalize_username(getattr(entity, "username", None)),
                "url": f"https://t.me/{getattr(entity, 'username', '')}" if getattr(entity, "username", None) else None,
                "participants_count": getattr(entity, "participants_count", None),
                "megagroup": getattr(entity, "megagroup", None),
                "broadcast": getattr(entity, "broadcast", None),
                "verified": getattr(entity, "verified", None),
                "scam": getattr(entity, "scam", None),
                "fake": getattr(entity, "fake", None),
                "restricted": getattr(entity, "restricted", None),
                "restriction_reason": str(getattr(entity, "restriction_reason", None)),
                "first_post_date_utc": first_post_date_utc
            })

            # ---- ORIGINAL TARGET BOT ENRICHMENT ----
            normalized_target = normalize_target_value(target)

            if ENABLE_USERINFOBOT:
                try:
                    reply = await ask_bot(client, USERINFO_BOT, normalized_target)
                    parsed = parse_userinfobot(reply)
                    parsed["target"] = str(target)
                    parsed["lookup_type"] = "original_target"
                    parsed["lookup_user_id"] = None
                    bot_enrichment_rows.append(parsed)
                    await sleep_jitter(BOT_SLEEP_MIN, BOT_SLEEP_MAX)
                except FloodWaitError as e:
                    bot_enrichment_rows.append({
                        "target": str(target),
                        "provider": "userinfobot",
                        "lookup_type": "original_target",
                        "lookup_user_id": None,
                        "raw_response": None,
                        "resolved_id": None,
                        "first_name": None,
                        "last_name": None,
                        "username": None,
                        "language_code": None,
                        "error": f"Flood wait: {e.seconds}s"
                    })
                except Exception as e:
                    bot_enrichment_rows.append({
                        "target": str(target),
                        "provider": "userinfobot",
                        "lookup_type": "original_target",
                        "lookup_user_id": None,
                        "raw_response": None,
                        "resolved_id": None,
                        "first_name": None,
                        "last_name": None,
                        "username": None,
                        "language_code": None,
                        "error": str(e)
                    })

            if ENABLE_SANGMATA:
                try:
                    sangmata_query = normalized_target
                    if str(normalized_target).lstrip("-").isdigit():
                        sangmata_query = f"/search_id {normalized_target}"

                    reply = await ask_bot(client, SANGMATA_BOT, sangmata_query)
                    parsed = parse_sangmata(reply)
                    parsed["target"] = str(target)
                    parsed["lookup_type"] = "original_target"
                    parsed["lookup_user_id"] = None
                    parsed["name_history"] = " | ".join(parsed["name_history"])
                    parsed["username_history"] = " | ".join(parsed["username_history"])
                    bot_enrichment_rows.append(parsed)
                    await sleep_jitter(BOT_SLEEP_MIN, BOT_SLEEP_MAX)
                except FloodWaitError as e:
                    bot_enrichment_rows.append({
                        "target": str(target),
                        "provider": "sangmata",
                        "lookup_type": "original_target",
                        "lookup_user_id": None,
                        "raw_response": None,
                        "resolved_id": None,
                        "username": None,
                        "name_history": None,
                        "username_history": None,
                        "error": f"Flood wait: {e.seconds}s"
                    })
                except Exception as e:
                    bot_enrichment_rows.append({
                        "target": str(target),
                        "provider": "sangmata",
                        "lookup_type": "original_target",
                        "lookup_user_id": None,
                        "raw_response": None,
                        "resolved_id": None,
                        "username": None,
                        "name_history": None,
                        "username_history": None,
                        "error": str(e)
                    })

            # ---- ADMINS ----
            if getattr(entity, "megagroup", False):
                try:
                    result = await client(GetParticipantsRequest(
                        channel=entity,
                        filter=ChannelParticipantsAdmins(),
                        offset=0,
                        limit=ADMIN_LIMIT,
                        hash=0
                    ))

                    admin_access = True
                    admin_count = len(result.users)

                    for admin in result.users:
                        admin_username = normalize_username(admin.username)

                        admin_rows.append({
                            "target": str(target),
                            "user_id": admin.id,
                            "username": admin_username,
                            "first_name": admin.first_name,
                            "last_name": admin.last_name,
                            "is_watchlisted": admin.id in watchlist
                        })

                        if admin_username:
                            user_map[admin.id] = admin_username
                            usernames_by_user.setdefault(admin.id, set()).add(admin_username)

                        user_targets.setdefault(admin.id, set()).add(str(target))

                except FloodWaitError as e:
                    print(f"[-] Admin fetch flood wait: {e.seconds}s")
                    error_msg = f"Admin flood wait: {e.seconds}s"

                except Exception as e:
                    print(f"[-] Admin fetch failed: {e}")

                await sleep_jitter(MESSAGE_SLEEP_MIN, MESSAGE_SLEEP_MAX)

            # ---- MEMBERS ----
            if ENABLE_MEMBER_ENUM and getattr(entity, "megagroup", False):
                try:
                    batch_member_rows = await enumerate_members(client, entity, target, watchlist)
                    member_rows.extend(batch_member_rows)
                    member_count = len(batch_member_rows)
                    member_access = True

                    for member in batch_member_rows:
                        uid = member["user_id"]
                        uname = member["username"]
                        if uname:
                            user_map[uid] = uname
                            usernames_by_user.setdefault(uid, set()).add(uname)
                        else:
                            user_map.setdefault(uid, None)
                            usernames_by_user.setdefault(uid, set())

                        user_targets.setdefault(uid, set()).add(str(target))

                except FloodWaitError as e:
                    print(f"[-] Member fetch flood wait: {e.seconds}s")
                    error_msg = f"Member flood wait: {e.seconds}s"

                except Exception as e:
                    print(f"[-] Member fetch failed: {e}")

                await sleep_jitter(MESSAGE_SLEEP_MIN, MESSAGE_SLEEP_MAX)

            # ---- MESSAGES ----
            try:
                iter_kwargs, message_start_dt_utc, message_end_dt_utc = build_iter_messages_kwargs()

                async for msg in client.iter_messages(entity, **iter_kwargs):
                    msg_dt_utc = msg.date.astimezone(timezone.utc) if msg.date else None

                    # iter_messages walks newest to oldest. Once below the start date, this target is done.
                    if message_start_dt_utc and msg_dt_utc and msg_dt_utc < message_start_dt_utc:
                        break

                    if not should_keep_message_by_date(msg_dt_utc, message_start_dt_utc, message_end_dt_utc):
                        continue

                    message_count += 1
                    message_access = True

                    if not msg.sender_id:
                        continue

                    sender_username = None
                    sender_obj = getattr(msg, "sender", None)
                    if sender_obj is not None:
                        sender_username = normalize_username(getattr(sender_obj, "username", None))

                    if sender_username:
                        user_map[msg.sender_id] = sender_username
                        usernames_by_user.setdefault(msg.sender_id, set()).add(sender_username)
                    else:
                        user_map.setdefault(msg.sender_id, None)
                        usernames_by_user.setdefault(msg.sender_id, set())

                    user_targets.setdefault(msg.sender_id, set()).add(str(target))
                    user_message_counts[(msg.sender_id, str(target))] = (
                        user_message_counts.get((msg.sender_id, str(target)), 0) + 1
                    )

                    date_utc = msg_dt_utc
                    date_local = msg.date.astimezone(LOCAL_TZ) if msg.date else None

                    if date_utc:
                        prev_utc = user_first_seen_utc.get(msg.sender_id)
                        if not prev_utc or date_utc < prev_utc:
                            user_first_seen_utc[msg.sender_id] = date_utc

                    if date_local:
                        prev_local = user_first_seen_local.get(msg.sender_id)
                        if not prev_local or date_local < prev_local:
                            user_first_seen_local[msg.sender_id] = date_local

                    text = msg.message or ""
                    detected_lang = safe_detect_language(text) if DETECT_MESSAGE_LANGUAGE else None
                    translated_text = maybe_translate(text, detected_lang)

                    reply_to_msg_id = getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None)

                    row = {
                        "target": str(target),
                        "user_id": msg.sender_id,
                        "username": sender_username,
                        "message_id": msg.id,
                        "reply_to_msg_id": reply_to_msg_id,
                        "date_utc": date_utc,
                        "date_local": date_local,
                        "detected_lang": detected_lang,
                        "is_watchlisted": msg.sender_id in watchlist
                    }

                    if INCLUDE_VIEWS_FORWARDS:
                        row["views"] = getattr(msg, "views", None)
                        row["forwards"] = getattr(msg, "forwards", None)

                    if INCLUDE_FORWARD_ORIGIN:
                        forward_meta = get_forward_origin_metadata(msg)
                        row.update({
                            "is_forwarded": False,
                            "forward_date_utc": None,
                            "forward_from_id": None,
                            "forward_from_name": None,
                            "forward_channel_post": None,
                            "forward_post_author": None,
                            "forward_saved_from_peer_id": None,
                            "forward_saved_from_msg_id": None,
                            "forward_psa_type": None,
                        })
                        row.update(forward_meta)

                    if INCLUDE_MEDIA_METADATA:
                        row.update(get_media_metadata(msg))

                    if EXTRACT_URLS:
                        urls = extract_urls_from_message(msg, text)
                        row["url_count"] = len(urls)
                        row["urls_json"] = json_dumps_safe(urls)
                        row["urls_flat"] = " | ".join(u["url"] for u in urls) if urls else None

                        for url_item in urls:
                            extracted_url_rows.append({
                                "target": str(target),
                                "user_id": msg.sender_id,
                                "username": sender_username,
                                "message_id": msg.id,
                                "date_utc": date_utc,
                                "url": url_item.get("url"),
                                "source": url_item.get("source"),
                                "display_text": url_item.get("display_text"),
                            })

                    if INCLUDE_MESSAGE_TEXT:
                        row["message_text"] = text

                    message_rows.append(row)
                    per_target_message_sender[str(target)][msg.id] = msg.sender_id

                    if translated_text:
                        translated_message_rows.append({
                            "target": str(target),
                            "user_id": msg.sender_id,
                            "username": sender_username,
                            "message_id": msg.id,
                            "detected_lang": detected_lang,
                            "translated_to": TRANSLATE_TO,
                            "original_text": text,
                            "translated_text": translated_text
                        })

                await sleep_jitter(MESSAGE_SLEEP_MIN, MESSAGE_SLEEP_MAX)

            except FloodWaitError as e:
                message_error = f"Message flood wait: {e.seconds}s"
                print(f"[-] {message_error}")

            except Exception as e:
                message_error = str(e)
                print(f"[-] Message scrape failed: {e}")

            print(
                f"[✓] {target}: type={entity_type}, admins={admin_count}, "
                f"members={member_count}, messages={message_count}"
            )

            status_rows.append({
                "target": str(target),
                "resolved": True,
                "entity_type": entity_type,
                "admin_access": admin_access,
                "admin_count": admin_count,
                "member_access": member_access,
                "member_count": member_count,
                "message_access": message_access,
                "message_count": message_count,
                "message_start_date": MESSAGE_START_DATE,
                "message_end_date": MESSAGE_END_DATE,
                "message_date_range_max_messages": MESSAGE_DATE_RANGE_MAX_MESSAGES,
                "error": error_msg or message_error
            })

            await sleep_jitter(MESSAGE_SLEEP_MIN, MESSAGE_SLEEP_MAX)

        # =====================
        # SECOND PASS: DISCOVERED USER ID ENRICHMENT
        # =====================
        if ENABLE_DISCOVERED_ID_ENRICHMENT:
            print("\n[+] Building discovered-user enrichment queue...")

            all_user_ids = set(user_map.keys()) | set(user_first_seen_utc.keys()) | set(user_first_seen_local.keys())
            already_done_ids = load_already_enriched_ids(BOT_ENRICHMENT_OUTPUT)

            enrichment_queue = build_discovered_enrichment_queue(
                all_user_ids=all_user_ids,
                watchlist=watchlist,
                user_targets=user_targets,
                user_message_counts=user_message_counts,
                user_map=user_map,
                limit=DISCOVERED_ENRICHMENT_LIMIT
            )

            print(f"[+] Candidate discovered users for enrichment: {len(enrichment_queue)}")
            print(f"[+] Already enriched IDs found on disk: {len(already_done_ids)}")

            processed_since_checkpoint = 0

            for idx, item in enumerate(enrichment_queue, start=1):
                lookup_user_id = item["lookup_user_id"]

                if lookup_user_id in already_done_ids:
                    print(f"[DEBUG] Skipping already-enriched user_id={lookup_user_id}")
                    continue

                print(
                    f"[+] Enriching discovered user {lookup_user_id} "
                    f"({idx}/{len(enrichment_queue)}) "
                    f"targets={item['target_count']} messages={item['message_total']}"
                )

                try:
                    new_rows = await enrich_single_user_id_with_bots(client, lookup_user_id)

                    for row in new_rows:
                        row["target"] = None
                        row["current_username"] = item.get("current_username")
                        row["target_count"] = item.get("target_count")
                        row["message_total"] = item.get("message_total")
                        row["priority_score"] = item.get("score")
                        bot_enrichment_rows.append(row)

                    already_done_ids.add(lookup_user_id)
                    processed_since_checkpoint += 1

                    if processed_since_checkpoint >= BOT_ENRICHMENT_CHECKPOINT_EVERY:
                        pd.DataFrame(bot_enrichment_rows).to_csv(BOT_ENRICHMENT_OUTPUT, index=False)
                        processed_since_checkpoint = 0
                        print(f"[✓] Checkpoint saved to {BOT_ENRICHMENT_OUTPUT}")

                except FloodWaitError as e:
                    print(f"[-] Flood wait during discovered enrichment: {e.seconds}s")
                    await asyncio.sleep(e.seconds + random.uniform(5, 15))
                except Exception as e:
                    print(f"[-] Discovered enrichment failed for {lookup_user_id}: {e}")

            pd.DataFrame(bot_enrichment_rows).to_csv(BOT_ENRICHMENT_OUTPUT, index=False)
            print(f"[✓] Final discovered enrichment saved to {BOT_ENRICHMENT_OUTPUT}")

    # =====================
    # DERIVED ANALYTICS
    # =====================
    user_map_rows = [
        {"user_id": uid, "username": uname}
        for uid, uname in user_map.items()
    ]

    all_user_ids = set(user_map.keys()) | set(user_first_seen_utc.keys()) | set(user_first_seen_local.keys())
    user_first_seen_rows = [
        {
            "user_id": uid,
            "username": user_map.get(uid),
            "first_seen_utc": user_first_seen_utc.get(uid),
            "first_seen_local": user_first_seen_local.get(uid)
        }
        for uid in all_user_ids
    ]

    usernames_by_user_rows = [
        {
            "user_id": uid,
            "current_username": user_map.get(uid),
            "observed_username_count": len(names),
            "observed_usernames": sorted(list(names))
        }
        for uid, names in usernames_by_user.items()
    ]

    user_target_overlap_rows = [
        {
            "user_id": uid,
            "current_username": user_map.get(uid),
            "target_count": len(targets_seen),
            "targets": sorted(list(targets_seen))
        }
        for uid, targets_seen in user_targets.items()
    ]

    multi_target_users_rows = [
        row for row in user_target_overlap_rows
        if row["target_count"] > 1
    ]

    user_target_message_counts_rows = [
        {
            "user_id": uid,
            "current_username": user_map.get(uid),
            "target": target,
            "message_count": count
        }
        for (uid, target), count in user_message_counts.items()
    ]

    messages_df = pd.DataFrame(message_rows)
    early_users_by_target_rows = []

    if not messages_df.empty:
        first_seen_per_target = (
            messages_df.dropna(subset=["date_utc"])
            .groupby(["target", "user_id"], as_index=False)
            .agg(
                first_seen_utc=("date_utc", "min"),
                username=("username", "last")
            )
        )

        for target_value, group_df in first_seen_per_target.groupby("target"):
            group_sorted = group_df.sort_values("first_seen_utc").head(50).copy()
            group_sorted["first_seen_rank_within_target"] = range(1, len(group_sorted) + 1)

            for _, row in group_sorted.iterrows():
                early_users_by_target_rows.append({
                    "target": target_value,
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "first_seen_utc": row["first_seen_utc"],
                    "first_seen_rank_within_target": row["first_seen_rank_within_target"]
                })

    first_seen_clusters_rows = []
    first_seen_df = pd.DataFrame(user_first_seen_rows)

    if not first_seen_df.empty and "first_seen_utc" in first_seen_df.columns:
        first_seen_df = first_seen_df.dropna(subset=["first_seen_utc"]).copy()
        if not first_seen_df.empty:
            first_seen_df["first_seen_utc"] = pd.to_datetime(first_seen_df["first_seen_utc"], utc=True)
            first_seen_df["first_seen_bucket_1h"] = first_seen_df["first_seen_utc"].dt.floor("1h")

            cluster_counts = (
                first_seen_df.groupby("first_seen_bucket_1h", as_index=False)
                .agg(user_count=("user_id", "count"))
                .sort_values("first_seen_bucket_1h")
            )

            first_seen_clusters_rows = cluster_counts.to_dict("records")

    user_enriched_profiles_rows = []
    for uid in all_user_ids:
        targets_seen = user_targets.get(uid, set())
        names_seen = usernames_by_user.get(uid, set())

        user_enriched_profiles_rows.append({
            "user_id": uid,
            "current_username": user_map.get(uid),
            "observed_username_count": len(names_seen),
            "observed_usernames": sorted(list(names_seen)),
            "first_seen_utc": user_first_seen_utc.get(uid),
            "first_seen_local": user_first_seen_local.get(uid),
            "target_count": len(targets_seen),
            "targets": sorted(list(targets_seen)),
            "is_watchlisted": uid in watchlist
        })

    top_posters_by_target_rows = []
    if ENABLE_TOP_POSTERS and user_target_message_counts_rows:
        counts_df = pd.DataFrame(user_target_message_counts_rows)
        if not counts_df.empty:
            totals_df = (
                counts_df.groupby("target", as_index=False)
                .agg(total_messages=("message_count", "sum"))
            )
            merged_df = counts_df.merge(totals_df, on="target", how="left")
            merged_df["message_share_pct"] = (
                merged_df["message_count"] / merged_df["total_messages"] * 100.0
            )

            for target_value, group_df in merged_df.groupby("target"):
                group_sorted = group_df.sort_values(
                    ["message_count", "user_id"], ascending=[False, True]
                ).copy()
                group_sorted["rank_within_target"] = range(1, len(group_sorted) + 1)

                for _, row in group_sorted.head(50).iterrows():
                    top_posters_by_target_rows.append({
                        "target": target_value,
                        "user_id": row["user_id"],
                        "current_username": row["current_username"],
                        "message_count": int(row["message_count"]),
                        "total_messages": int(row["total_messages"]),
                        "message_share_pct": round(float(row["message_share_pct"]), 4),
                        "rank_within_target": int(row["rank_within_target"])
                    })

    reply_summary_by_user_rows = []
    if ENABLE_REPLY_GRAPH and message_rows:
        for row in message_rows:
            target_value = row["target"]
            src_uid = row["user_id"]
            reply_to_msg_id = row.get("reply_to_msg_id")

            if not reply_to_msg_id:
                continue

            dst_uid = per_target_message_sender.get(target_value, {}).get(reply_to_msg_id)
            if not dst_uid:
                continue

            reply_edges_rows.append({
                "target": target_value,
                "src_user_id": src_uid,
                "src_username": user_map.get(src_uid),
                "dst_user_id": dst_uid,
                "dst_username": user_map.get(dst_uid),
                "reply_to_msg_id": reply_to_msg_id
            })

            reply_summary_counter[(target_value, src_uid, dst_uid)] += 1

        for (target_value, src_uid, dst_uid), count in reply_summary_counter.items():
            reply_summary_by_user_rows.append({
                "target": target_value,
                "src_user_id": src_uid,
                "src_username": user_map.get(src_uid),
                "dst_user_id": dst_uid,
                "dst_username": user_map.get(dst_uid),
                "reply_count": count
            })

    # =====================
    # OUTPUT
    # =====================
    pd.DataFrame(admin_rows).drop_duplicates().to_csv("admins.csv", index=False)
    pd.DataFrame(member_rows).drop_duplicates().to_csv("group_members.csv", index=False)
    pd.DataFrame(message_rows).to_csv("messages.csv", index=False)
    pd.DataFrame(status_rows).to_csv("target_status.csv", index=False)
    pd.DataFrame(target_metadata_rows).to_csv("target_metadata.csv", index=False)

    pd.DataFrame(user_map_rows).to_csv("user_map.csv", index=False)
    pd.DataFrame(user_first_seen_rows).to_csv("user_first_seen.csv", index=False)

    pd.DataFrame(usernames_by_user_rows).to_csv("usernames_by_user.csv", index=False)
    pd.DataFrame(user_target_overlap_rows).to_csv("user_target_overlap.csv", index=False)
    pd.DataFrame(multi_target_users_rows).to_csv("multi_target_users.csv", index=False)
    pd.DataFrame(user_target_message_counts_rows).to_csv("user_target_message_counts.csv", index=False)
    pd.DataFrame(early_users_by_target_rows).to_csv("early_users_by_target.csv", index=False)
    pd.DataFrame(first_seen_clusters_rows).to_csv("first_seen_clusters_1h.csv", index=False)
    pd.DataFrame(user_enriched_profiles_rows).to_csv("user_enriched_profiles.csv", index=False)

    pd.DataFrame(top_posters_by_target_rows).to_csv("top_posters_by_target.csv", index=False)
    pd.DataFrame(reply_edges_rows).to_csv("reply_edges.csv", index=False)
    pd.DataFrame(reply_summary_by_user_rows).to_csv("reply_summary_by_user.csv", index=False)
    pd.DataFrame(translated_message_rows).to_csv("translated_messages.csv", index=False)
    pd.DataFrame(extracted_url_rows).to_csv("url_mentions.csv", index=False)
    pd.DataFrame(bot_enrichment_rows).to_csv(BOT_ENRICHMENT_OUTPUT, index=False)

    print("\n[✓] COMPLETE")
    print("[✓] admins.csv")
    print("[✓] group_members.csv")
    print("[✓] messages.csv")
    print("[✓] target_status.csv")
    print("[✓] target_metadata.csv")
    print("[✓] user_map.csv")
    print("[✓] user_first_seen.csv")
    print("[✓] usernames_by_user.csv")
    print("[✓] user_target_overlap.csv")
    print("[✓] multi_target_users.csv")
    print("[✓] user_target_message_counts.csv")
    print("[✓] early_users_by_target.csv")
    print("[✓] first_seen_clusters_1h.csv")
    print("[✓] user_enriched_profiles.csv")
    print("[✓] top_posters_by_target.csv")
    print("[✓] reply_edges.csv")
    print("[✓] reply_summary_by_user.csv")
    print("[✓] translated_messages.csv")
    print("[✓] url_mentions.csv")
    print(f"[✓] {BOT_ENRICHMENT_OUTPUT}")


# =====================
# RUN
# =====================
if __name__ == "__main__":
    asyncio.run(main())
