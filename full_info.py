"""Full MLBB player profile inspector (separate from lean info.py lookup)."""

import datetime
import json
import os
import time
from typing import Dict, List, Optional

from info import (
    BaseConnection,
    DEVICE_MODELS,
    DeviceManager,
    GameConnection,
    SdpDataType,
    SdpException,
    SdpStruct,
    _SESSION_RESOLVER_DEVICE,
    map_rank,
)

HERO_ID_MAP = {
    1: "Miya", 2: "Balmond", 3: "Saber", 4: "Alice", 5: "Nana", 6: "Tigreal",
    7: "Alucard", 8: "Karina", 9: "Akai", 10: "Franco", 11: "Bane", 12: "Bruno",
    13: "Clint", 14: "Rafaela", 15: "Eudora", 16: "Zilong", 17: "Fanny", 18: "Layla",
    19: "Minotaur", 20: "Lolita", 21: "Hayabusa", 22: "Freya", 23: "Gord", 24: "Natalia",
    25: "Kagura", 26: "Chou", 27: "Sun", 28: "Alpha", 29: "Ruby", 30: "Yi Sun-shin",
    31: "Moskov", 32: "Johnson", 33: "Cyclops", 34: "Estes", 35: "Hilda", 36: "Aurora",
    37: "Lapu-Lapu", 38: "Vexana", 39: "Roger", 40: "Karrie", 41: "Gatotkaca", 42: "Harley",
    43: "Irithel", 44: "Grock", 45: "Argus", 46: "Odette", 47: "Lancelot", 48: "Diggie",
    49: "Hylos", 50: "Zhask", 51: "Helcurt", 52: "Pharsa", 53: "Lesley", 54: "Jawhead",
    55: "Angela", 56: "Gusion", 57: "Valir", 58: "Martis", 59: "Uranus", 60: "Hanabi",
    61: "Chang'e", 62: "Kaja", 63: "Selena", 64: "Aldous", 65: "Claude", 66: "Vale",
    67: "Leomord", 68: "Lunox", 69: "Hanzo", 70: "Belerick", 71: "Kimmy", 72: "Thamuz",
    73: "Harith", 74: "Minsitthar", 75: "Kadita", 76: "Faramis", 77: "Badang", 78: "Khufra",
    79: "Granger", 80: "Guinevere", 81: "Esmeralda", 82: "Terizla", 83: "X.Borg", 84: "Ling",
    85: "Dyrroth", 86: "Lylia", 87: "Baxia", 88: "Masha", 89: "Wanwan", 90: "Silvanna",
    91: "Cecilion", 92: "Carmilla", 93: "Atlas", 94: "Popol and Kupa", 95: "Yu Zhong",
    96: "Luo Yi", 97: "Benedetta", 98: "Khaleed", 99: "Barats", 100: "Brody", 101: "Yve",
    102: "Mathilda", 103: "Paquito", 104: "Gloo", 105: "Beatrix", 106: "Phoveus",
    107: "Natan", 108: "Aulus", 109: "Aamon", 110: "Valentina", 111: "Edith", 112: "Floryn",
    113: "Yin", 114: "Melissa", 115: "Xavier", 116: "Julian", 117: "Fredrinn", 118: "Joy",
    119: "Novaria", 120: "Arlott", 121: "Ixia", 122: "Nolan", 123: "Cici", 124: "Chip",
    125: "Zhuxin", 126: "Suyou", 127: "Lukas", 128: "Kalea", 129: "Zetian", 130: "Obsidia",
}

SKIN_TIER_LABELS = {
    'common': 'Common',
    'exceptional': 'Exceptional',
    'deluxe': 'Deluxe',
    'exquisite': 'Exquisite',
    'grand': 'Grand',
    'supreme': 'Supreme',
    'unknown': 'Unknown',
}

_SKIN_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skin_db.json')
try:
    with open(_SKIN_DB_PATH, 'r', encoding='utf-8') as _f:
        _raw = _f.read().strip()
        if not _raw.startswith('{'):
            _raw = '{' + _raw
        SKIN_DB = json.loads(_raw)
except Exception:
    SKIN_DB = {}


def get_skin_tier(skin_id):
    tier = SKIN_DB.get(str(skin_id))
    if not tier:
        return None
    return SKIN_TIER_LABELS.get(tier, tier.capitalize())


def get_hero_history(tag_91: list) -> List[str]:
    return [HERO_ID_MAP.get(hid, f"Unknown({hid})") for hid in reversed(tag_91)][:5]


def map_collector_point(point: int) -> str:
    if point < 1000:
        return "No Tier"
    tiers = [
        (1000, 4000, "Amateur Collector"),
        (4000, 10000, "Junior Collector"),
        (10000, 22000, "Seasoned Collector"),
        (22000, 44000, "Expert Collector"),
        (44000, 84000, "Renowned Collector"),
        (84000, 160000, "Exalted Collector"),
        (160000, 280000, "Mega Collector"),
        (280000, float('inf'), "World Collector"),
    ]
    for min_p, max_p, name in tiers:
        if min_p <= point < max_p:
            if name == "World Collector":
                return "World Collector"
            level = int((point - min_p) // ((max_p - min_p) / 5))
            roman = ["V", "IV", "III", "II", "I"][level]
            return f"{name} {roman}"
    return "Unknown"


def parse_skin_counts(tag_118) -> dict:
    if not tag_118 or not isinstance(tag_118, dict):
        return {}
    skin_data = next((tag_118[k] for k in (4, '4') if isinstance(tag_118.get(k), dict) and tag_118[k]), tag_118)
    if not isinstance(skin_data, dict):
        return {}
    skin_types = {
        6: "Supreme Skins", 5: "Grand Skins", 4: "Exquisite Skins",
        3: "Deluxe Skins", 2: "Exceptional Skins", 1: "Common Skins",
    }
    skin_counts, total_skins = {}, 0
    for skin_id, count in skin_data.items():
        try:
            sid_int = int(skin_id)
        except (ValueError, TypeError):
            continue
        if sid_int in skin_types:
            skin_counts[skin_types[sid_int]] = count
            total_skins += count
    if total_skins > 0:
        skin_counts["Total Skins"] = total_skins
    return skin_counts


def format_timestamp(timestamp: int) -> str:
    try:
        if timestamp == 0:
            return "Never"
        return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "Unknown"


def format_timestamp_full(timestamp: int) -> str:
    try:
        if timestamp == 0:
            return "N/A"
        utc_dt = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
        return (utc_dt + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "Invalid timestamp"


def extract_player_data(result, role_info=None, creation_ts=0) -> Optional[Dict]:
    if not isinstance(result, dict) or not result.get(0) or len(result[0]) == 0:
        return None
    try:
        player = result[0][0]
        ri = role_info if isinstance(role_info, dict) else {}

        nickname = player.get(2, "Unknown")
        player_id = player.get(0, "Unknown")
        server = player.get(1, "Unknown")
        level = player.get(3, "Unknown")
        skin = player.get(83, "Unknown")
        hero_count = ri.get(9, 0)
        matches = ri.get(22, 0)

        loc_data = player.get(71)
        location = ", ".join(str(x) for x in loc_data) if isinstance(loc_data, list) and len(loc_data) >= 2 else "NOT FOUND"
        last_login = player.get(5, 0)
        last_login_country = player.get(87, "Unknown")
        create_account_country = player.get(97, "Unknown")

        squad_icon = player.get(31, "")
        squad_name = str(player.get(30, "") or "").replace("`", "").strip()
        squad = f"{squad_icon} {squad_name}".strip() if squad_name else "—"
        squad_id = ri.get(34, 0) or player.get(34, player.get(28, 0))

        tag_95, tag_8 = player.get(95), player.get(8)
        high_rank = map_rank(tag_95) if tag_95 is not None else "Unknown"
        current_rank = map_rank(tag_8) if tag_8 is not None else "Unknown"
        achievement_points = player.get(7, 0)

        tag_136 = player.get(136, {})
        collector_point = tag_136.get(9, 0) if isinstance(tag_136, dict) else 0
        collector_rank = tag_136.get(10, 0) if isinstance(tag_136, dict) else 0
        collector_tier = map_collector_point(collector_point)

        tag_91 = player.get(91, [])
        hero_history = get_hero_history(tag_91) if tag_91 else ["Private / Not Available"]

        tag_118 = ri.get(118, {})
        skin_counts = parse_skin_counts(tag_118) if isinstance(tag_118, dict) else {}

        rating_score = player.get(9, 0)
        followers = ri.get(23, 0) or player.get(15, 0)
        popularity = player.get(14, 0)

        _v24 = ri.get(24, 0)
        likes = _v24 if isinstance(_v24, int) and _v24 else (player.get(61, 0) if isinstance(player.get(61, 0), int) else 0)

        _t111 = player.get(111, {})
        _cs_current = _t111.get(0, 0) if isinstance(_t111, dict) else (_t111 if isinstance(_t111, int) else 0)
        credits_score = f"{_cs_current}/110" if _cs_current else "N/A"

        restriction_flags = "None"
        _t135 = player.get(135, {})
        _flags_val = ri.get(102, 0) or (_t135.get(0, 0) if isinstance(_t135, dict) else 0)
        if _flags_val:
            _pct = round((bin(int(_flags_val)).count('1') / 7) * 100, 1)
            _risk, _risk_icon = ("Low Risk", "✅") if _pct < 30 else (("Medium Risk", "⚠️") if _pct < 60 else ("High Risk", "🚨"))
            restriction_flags = f"{_pct}% {_risk_icon} ({_risk})"

        _aff_level = _t135.get(1, 0) if isinstance(_t135, dict) else 0
        _AFFINITY_MAP = {0: "None", 1: "Bronze", 2: "Silver", 3: "Gold", 4: "Platinum", 5: "Diamond"}
        affinity_label = _AFFINITY_MAP.get(_aff_level, f"Level {_aff_level}") if _aff_level else "None"

        _now_ts = time.time()
        _sl_expiry = player.get(50, 0)
        starlight_user = "Yes ⭐" if (_sl_expiry and isinstance(_sl_expiry, int) and _now_ts < _sl_expiry < _now_ts + 400 * 86400) else "No"

        _MIN_VALID_TS = 1451577600
        _create_ts_fallback = player.get(6, 0)
        if creation_ts and creation_ts >= _MIN_VALID_TS:
            creation_date = format_timestamp_full(creation_ts)
        elif _create_ts_fallback and _create_ts_fallback >= _MIN_VALID_TS:
            creation_date = format_timestamp_full(_create_ts_fallback)
        else:
            creation_date = "N/A"

        _tag45 = player.get(45, {})
        if isinstance(_tag45, dict) and _tag45:
            _hero_entries = [
                (_e.get(1, 0), HERO_ID_MAP.get(_e.get(0, 0), f"Unknown({_e.get(0, 0)})"))
                for _e in _tag45.values() if isinstance(_e, dict)
            ]
            _hero_entries.sort(key=lambda x: x[0], reverse=True)
            last_heroes_purchase = ", ".join(h for _, h in _hero_entries) if _hero_entries else "N/A"
        else:
            _hero_buy_ts = player.get(175, 0)
            last_heroes_purchase = format_timestamp(_hero_buy_ts) if _hero_buy_ts else "N/A"

        mcl_wins = ri.get(46, 0) or player.get(104, player.get(103, 0))
        win_count = ri.get(22, 0)
        total_battles = ri.get(77, 0) or player.get(17, 0)
        win_rate = f"{(win_count / total_battles * 100):.1f}%" if (isinstance(total_battles, int) and isinstance(win_count, int) and total_battles > 0 and 0 <= win_count <= total_battles) else "N/A"

        _bp_raw = ri.get(111, 0)
        bp = _bp_raw if isinstance(_bp_raw, int) else (_bp_raw.get(0, 0) if isinstance(_bp_raw, dict) else 0)
        _motto = ri.get(24, "")
        squad_motto = _motto if (_motto and isinstance(_motto, str)) else "N/A"
        diamonds = ri.get(46, 0)
        starlight_count = ri.get(60, 0)

        skin_history = []
        _tag92 = ri.get(92, [])
        if isinstance(_tag92, list):
            _TIER_M = {1: "Common", 2: "Exceptional", 3: "Deluxe", 4: "Exquisite", 5: "Grand", 6: "Supreme"}
            for _e in _tag92[:10]:
                if isinstance(_e, dict):
                    skin_history.append(f"SkinID:{_e.get(0, 0)}({_TIER_M.get(_e.get(2, 0), f'T{_e.get(2, 0)}')})|{format_timestamp(_e.get(4, 0)) if _e.get(4, 0) else '?'}")
        skin_history_str = ", ".join(skin_history) if skin_history else "N/A"

        _EMBLEM_MAP = {1: "Fighter", 2: "Assassin", 3: "Mage", 4: "Marksman", 5: "Support", 6: "Tank", 7: "Common"}
        _tag101 = ri.get(101, {})
        emblem_levels = ", ".join(f"{_EMBLEM_MAP.get(k, f'E{k}')}:Lv{_tag101[k]}" for k in sorted(_tag101.keys())) if isinstance(_tag101, dict) and _tag101 else "N/A"

        _skin_ts = player.get(176, 0)
        latest_skin_date = format_timestamp(_skin_ts) if _skin_ts else "N/A"
        _latest_skin_id = player.get(175, 0)
        latest_skin_id_str = str(_latest_skin_id) if _latest_skin_id else "N/A"
        latest_skin_tier = get_skin_tier(_latest_skin_id) if _latest_skin_id else "N/A"

        bindings = "N/A"
        _bindings = player.get(47, {})
        if isinstance(_bindings, dict) and _bindings:
            _bt_map = {0: "Facebook", 1: "Google", 2: "VK", 3: "Twitter", 4: "Game Center", 5: "Moonton", 6: "Email", 7: "Phone"}
            _bl = []
            for bt in _bindings:
                try:
                    _bl.append(_bt_map.get(int(bt), f"Type{int(bt)}"))
                except Exception:
                    pass
            bindings = ", ".join(_bl) if _bl else "N/A"

        return {
            'status': 'success',
            'data': {
                'basic_info': {
                    'nickname': nickname, 'player_id': player_id, 'server': server,
                    'level': level, 'skin_count': skin, 'hero_count': hero_count,
                },
                'skin_info': {'skin_breakdown': skin_counts},
                'location_info': {
                    'location': location, 'last_login': format_timestamp(last_login),
                    'last_login_country': last_login_country, 'create_account_country': create_account_country,
                },
                'game_info': {
                    'current_rank': current_rank, 'high_rank': high_rank,
                    'achievement_points': achievement_points, 'squad': squad,
                    'squad_id': squad_id, 'hero_history': hero_history, 'matches': matches,
                },
                'collector_info': {'collector_point': collector_point, 'collector_tier': collector_tier, 'collector_rank': collector_rank},
                'security_info': {'v2l_status': 'No', 'bindings': bindings},
                'extra_info': {
                    'rating_score': rating_score, 'followers': followers, 'popularity': popularity,
                    'likes': likes, 'credits_score': credits_score if credits_score != "N/A" else None,
                    'restriction_flags': restriction_flags, 'affinity': affinity_label,
                    'starlight_user': starlight_user, 'creation_date': creation_date,
                    'last_heroes_purchase': last_heroes_purchase, 'mcl_champion_wins': mcl_wins,
                    'win_count': win_count, 'total_battles': total_battles, 'win_rate': win_rate,
                    'battle_points': bp if bp else None, 'squad_motto': squad_motto if squad_motto != "N/A" else None,
                    'diamonds': diamonds if diamonds else None, 'starlight_count': starlight_count if starlight_count else None,
                    'skin_history': skin_history_str if skin_history_str != "N/A" else None,
                    'emblem_levels': emblem_levels if emblem_levels != "N/A" else None,
                    'latest_skin_date': latest_skin_date, 'latest_skin_id': latest_skin_id_str, 'latest_skin_tier': latest_skin_tier,
                },
                'raw_data': player,
            },
        }
    except Exception:
        return None


def get_full_player_info(
    guid: int,
    session: str,
    device_manager: DeviceManager,
    max_device_retries: int = 20,
) -> Optional[Dict]:
    """Full 2-stage profile lookup (role_detail 11153 + role_info 10143 + all extracted metadata)."""
    result = None
    role_id, zone_id = None, None
    deadline = time.monotonic() + 20.0
    resolver_devs = [d for d in device_manager.devices if len(d) >= 88] or [_SESSION_RESOLVER_DEVICE]
    for rdev in resolver_devs[:3]:
        if time.monotonic() >= deadline:
            break
        rconn: Optional[GameConnection] = None
        try:
            rconn = GameConnection(device_id=rdev, device_manager=device_manager)
            rconn.connect()
            if not (rconn.login_to_login_server() and rconn.get_game_server() and rconn.connect_to_game_server(max_retries=2, deadline=deadline)):
                continue
            for atype in ("and", "ios"):
                if time.monotonic() >= deadline:
                    break
                cand = rconn.get_account_info(guid, session, atype, deadline=deadline)
                if cand:
                    rid, zid = rconn.get_highest_level_role(cand)
                    if rid:
                        result, role_id, zone_id = cand, rid, zid
                        break
            if role_id:
                break
        except Exception:
            pass
        finally:
            if rconn:
                rconn.cleanup()

    if not result or not role_id:
        return None

    used_devices: List[str] = []
    for attempt in range(1, max_device_retries + 1):
        if time.monotonic() >= deadline:
            break
        exclude = used_devices[-1] if used_devices else None
        device_id = device_manager.get_next_device(exclude)
        if not device_id:
            break
        used_devices.append(device_id)
        conn: Optional[GameConnection] = None
        try:
            conn = GameConnection(device_id=device_id, device_manager=device_manager)
            conn.connect()
            if not conn.login_to_login_server():
                device_manager.mark_device_failure(device_id)
                continue
            if not conn.get_game_server() or not conn.connect_to_game_server(deadline=deadline):
                continue
            role_detail = conn.get_role_detail(role_id)
            role_info = conn.get_role_info(role_id, zone_id)
            if not role_detail:
                if not role_info:
                    continue
                role_detail = {0: [{
                    0: role_id, 1: zone_id,
                    2: role_info.get(2, 'Unknown'), 3: role_info.get(3, 0),
                    8: role_info.get(6), 95: role_info.get(15),
                    83: role_info.get(10, 0),
                }]}
            player_data = extract_player_data(role_detail, role_info, 0)
            if not player_data:
                continue
            v2l = 'Yes' if result.get(13, 0) == 1 else 'No'
            player_data['data']['security_info']['v2l_status'] = v2l
            player_data['v2l_status'] = v2l
            player_data['device_used'] = device_id
            player_data['attempts'] = attempt
            return player_data
        except Exception:
            continue
        finally:
            if conn:
                conn.cleanup()
    return None


get_player_info = get_full_player_info


def _format_report(acct: str, pdata: Dict) -> str:
    d = pdata['data']
    bi, gi, ci, si, li, sk, ex = (
        d['basic_info'], d['game_info'], d['collector_info'],
        d['security_info'], d['location_info'], d['skin_info'], d['extra_info'],
    )
    lines = [
        f"=== {acct} ===",
        f"Nick / ID   : {bi['nickname']} | {bi['player_id']} ({bi['server']}) | Lv.{bi['level']}",
        f"Rank        : {gi['current_rank']} (Peak: {gi['high_rank']}) | Matches: {gi['matches']} | WR: {ex['win_rate']}",
        f"Skins / Hero: {bi['skin_count']} skins / {bi['hero_count']} heroes | Collector: {ci['collector_tier']} ({ci['collector_point']})",
        f"Skin Detail : {sk.get('skin_breakdown') or '{}'}",
        f"Bindings    : {si['bindings']} | V2L: {si['v2l_status']} | Created: {ex['creation_date']}",
        f"Location    : {li['location']} (Create: {li['create_account_country']} | Last: {li['last_login_country']} @ {li['last_login']})",
        f"Squad       : {gi['squad']} (ID:{gi['squad_id']}) | Badges/Fav: {gi['hero_history']}",
        f"Extra       : Credit:{ex['credits_score']} | Risk:{ex['restriction_flags']} | Likes:{ex['likes']} | Pop:{ex['popularity']} | Starlight:{ex['starlight_user']}",
        f"Emblems     : {ex['emblem_levels']}",
    ]
    return "\n".join(lines)


if __name__ == '__main__':
    import sys
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dm = DeviceManager(os.path.join(base_dir, 'devices.txt'))
    args = sys.argv[1:]
    if len(args) >= 2 and args[0].isdigit():
        res = get_full_player_info(int(args[0]), args[1], dm)
        print(_format_report(f"GUID:{args[0]}", res) if res else "[!] Lookup gagal / session expired")
    else:
        target = (args[0] if args else input("Path hit_valid.txt (atau 'guid session'): ")).strip().strip('"').strip("'")
        parts = target.split()
        if len(parts) == 2 and parts[0].isdigit():
            res = get_full_player_info(int(parts[0]), parts[1], dm)
            print(_format_report(f"GUID:{parts[0]}", res) if res else "[!] Lookup gagal / session expired")
        elif os.path.isfile(target):
            out_path = os.path.join(os.path.dirname(os.path.abspath(target)), 'full_info.txt')
            ok_cnt = 0
            with open(target, 'r', encoding='utf-8', errors='ignore') as fin, open(out_path, 'w', encoding='utf-8') as fout:
                for raw in fin:
                    cols = [x.strip() for x in raw.strip().split('|')]
                    if len(cols) < 3 or not cols[1] or not cols[2].isdigit():
                        continue
                    res = get_full_player_info(int(cols[2]), cols[1], dm)
                    if res:
                        ok_cnt += 1
                        rep = _format_report(cols[0], res)
                        print(rep + "\n")
                        fout.write(rep + "\n\n")
                    else:
                        print(f"[!] Gagal: {cols[0]} (GUID:{cols[2]})")
            print(f"[*] Selesai: {ok_cnt} full info disimpan ke {out_path}")
        else:
            print("Usage:\n  python full_info.py <hit_valid.txt>\n  python full_info.py <guid> <session>")
