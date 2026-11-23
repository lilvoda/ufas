# -*- coding: utf-8 -*-
"""
Generator combo user:pass MLBB realistis + database anti-duplikat SQLite lintas run.
Negara: ID, PH, MY, BR, US, VN, TH, MM, KH, IN, SG, TR, RU, SA (nama cowok & cewek).
Aturan ketat: min 6 char (6..20), ASCII alfanumerik [a-zA-Z0-9] tanpa huruf unik/simbol.
"""
import argparse
import json
import os
import random
import re
import sqlite3
import time
import unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "names_db.json")
SEEN_DB_PATH = os.path.join(BASE, "combo_seen.db")

PREFIXES = ("its", "itz", "itss", "iam", "im", "the", "real", "pro")
TAGS = ("gaming", "gamer", "yt", "tv", "ml", "mlbb", "pro", "official", "vip")
ACRONYM_TAGS = {"yt", "tv", "ml", "mlbb", "vip"}
NUMS = tuple(str(i) for i in range(1, 10)) + tuple(f"{i:02d}" for i in range(100))
SPECIAL_NUMS = ("100", "123", "143", "321", "404", "420", "515", "520", "666", "777", "888", "999", "007", "1234", "13579")
YEARS = tuple(str(y) for y in range(1990, 2010)) + tuple(str(y) for y in range(2020, 2027))
SUFFIXES = tuple(dict.fromkeys(NUMS + SPECIAL_NUMS + YEARS))
VALID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{5,19}$")


def clean_ascii_name(raw: str) -> str:
    s = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z]", "", s)
    return (s[0].upper() + s[1:].lower()) if len(s) >= 2 else ""


def load_names_db(
    db_path: str = DB_PATH,
    countries: list[str] | None = None,
    gender: str = "all",
    split_gender: bool = False,
) -> tuple[list[str], list[list[str]], list[int]]:
    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    weights_map = data.get("weights", {})
    all_countries = data.get("countries", {})
    want = {c.strip().upper() for c in countries if c.strip()} if countries else None
    g = (gender or "all").strip().lower()
    if g not in ("all", "male", "female"):
        raise ValueError(f"Gender tidak valid: {gender}")

    codes, pools, weights = [], [], []
    for code, entry in all_countries.items():
        if want and code.upper() not in want:
            continue
        w = max(1, int(weights_map.get(code, 1)))
        if isinstance(entry, dict) and split_gender:
            groups = ("male", "female") if g == "all" else (g,)
        else:
            groups = (None,)
        for grp in groups:
            if isinstance(entry, dict):
                raw_names = (entry.get(grp) or []) if grp else ((entry.get("male") or []) + (entry.get("female") or []) if g == "all" else (entry.get(g) or []))
            else:
                raw_names = entry or []
            cleaned = list(dict.fromkeys(filter(None, (clean_ascii_name(x) for x in raw_names))))
            if cleaned:
                codes.append(code)
                pools.append(cleaned)
                weights.append(w)
    if not pools:
        raise ValueError(f"Database nama kosong / filter tidak cocok: {db_path}")
    return codes, pools, weights


def _open_seen_db(seen_db: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(seen_db)) or ".", exist_ok=True)
    con = sqlite3.connect(seen_db, timeout=30.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS seen (u TEXT PRIMARY KEY)")
    return con


def count_seen_db(seen_db: str = SEEN_DB_PATH) -> int:
    if not seen_db or not os.path.exists(seen_db):
        return 0
    con = _open_seen_db(seen_db)
    try:
        return int(con.execute("SELECT COUNT(*) FROM seen").fetchone()[0])
    finally:
        con.close()


def clear_seen_db(seen_db: str = SEEN_DB_PATH) -> int:
    if not seen_db or not os.path.exists(seen_db):
        return 0
    con = _open_seen_db(seen_db)
    try:
        with con:
            cur = con.execute("DELETE FROM seen")
            return cur.rowcount or 0
    finally:
        con.close()


def load_seen_set(seen_db: str = SEEN_DB_PATH) -> set[str]:
    if not seen_db or not os.path.exists(seen_db):
        return set()
    con = _open_seen_db(seen_db)
    try:
        return {row[0] for row in con.execute("SELECT u FROM seen")}
    finally:
        con.close()


def save_seen_keys(keys: list[str], seen_db: str = SEEN_DB_PATH) -> None:
    if not seen_db or not keys:
        return
    con = _open_seen_db(seen_db)
    try:
        with con:
            con.executemany("INSERT OR IGNORE INTO seen (u) VALUES (?)", ((k,) for k in keys))
    finally:
        con.close()


def import_seen_file(filepath: str, seen_db: str = SEEN_DB_PATH) -> int:
    """Masukkan username dari combo/hasil lama agar tidak ter-generate ulang."""
    keys = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            u = s.split(":", 1)[0].split("|", 1)[0].strip().lower()
            if u:
                keys.append(u)
    keys = list(dict.fromkeys(keys))
    save_seen_keys(keys, seen_db)
    return len(keys)


def gen_pass(user: str) -> str:
    cap = user[0].upper() + user[1:].lower()
    r = random.random()
    if not user[-1].isdigit():
        if r < 0.45:
            pw = cap
        elif r < 0.70 and len(cap) <= 17:
            pw = cap + "123"
        elif r < 0.85:
            pw = user
        elif r < 0.94:
            pw = user.lower()
        else:
            extra = random.choice(("1234", "01", "12", "99"))
            pw = cap + extra if len(cap) + len(extra) <= 20 else cap
    elif r < 0.72:
        pw = cap
    elif r < 0.92:
        pw = user
    else:
        pw = user.lower()
    return pw


def _pick_suffix(base: str, options: tuple[str, ...] = SUFFIXES) -> str:
    lo = max(1, 6 - len(base))
    hi = 20 - len(base)
    valid = [s for s in options if lo <= len(s) <= hi]
    return random.choice(valid) if valid else ""


def _pick_pair(pool: list[str]) -> tuple[str, str]:
    n1 = random.choice(pool)
    a = n1.lower()
    for _ in range(8):
        n2 = random.choice(pool)
        b = n2.lower()
        if a != b and a not in b and b not in a:
            return n1, n2
    others = [x for x in pool if x.lower() != a and a not in x.lower() and x.lower() not in a]
    return (n1, random.choice(others)) if others else (n1, "")


def make_username(pools: list[list[str]], weights: list[int], wide: bool = False) -> str:
    pool = random.choices(pools, weights=weights, k=1)[0]
    r = random.random()
    allow_all_upper = False

    if r < (0.30 if wide else 0.46):
        # Name + angka/tahun realistis (misal: Rizky2002, Jhen16, Putrii99)
        base = random.choice(pool)
        sfx = _pick_suffix(base)
        user = base + sfx if sfx else ""
        allow_all_upper = True
    elif r < (0.68 if wide else 0.74) and len(pool) >= 2:
        # First + Last dari negara sama, tanpa nama kembar + opsional angka/tahun
        n1, n2 = _pick_pair(pool)
        user = n1 + n2 if n2 else ""
        if user and (len(user) < 6 or random.random() < (0.55 if wide else 0.30)):
            sfx = _pick_suffix(user, NUMS + SPECIAL_NUMS)
            if sfx:
                user += sfx
    elif r < (0.82 if wide else 0.86):
        # Prefix natural + Name (+ opsional angka)
        pfx = random.choice(PREFIXES)
        name = random.choice(pool)
        if name.lower().startswith(pfx):
            return ""
        if random.random() < 0.35:
            pfx = pfx[0].upper() + pfx[1:]
        user = pfx + name
        if len(user) < 6 or random.random() < (0.55 if wide else 0.30):
            sfx = _pick_suffix(user, NUMS + SPECIAL_NUMS)
            if sfx:
                user += sfx
    elif r < (0.91 if wide else 0.94):
        # Name + tag gamer/MLBB (+ opsional angka)
        tag = random.choice(TAGS)
        if random.random() < 0.65:
            tag = tag.upper() if tag in ACRONYM_TAGS else (tag[0].upper() + tag[1:])
        user = random.choice(pool) + tag
        if len(user) < 6 or random.random() < (0.55 if wide else 0.25):
            sfx = _pick_suffix(user, NUMS)
            if sfx:
                user += sfx
    else:
        # Inisial + Nama / Nama + Inisial + angka (misal: MRizky02, PutriA99)
        n1, n2 = _pick_pair(pool) if len(pool) >= 2 else (random.choice(pool), "")
        if n2:
            base = (n1[0].upper() + n2) if random.random() < 0.5 else (n1 + n2[0].upper())
            sfx = _pick_suffix(base) if (len(base) < 6 or random.random() < 0.85) else ""
            user = base + sfx
        else:
            base = random.choice(pool)
            user = base + _pick_suffix(base)

    if not user or len(user) < 6 or len(user) > 20:
        return ""

    rc = random.random()
    if allow_all_upper and rc < 0.08:
        return user.upper()
    if rc < 0.34:
        return user.lower()
    return user


def generate_combos(
    count: int,
    db_path: str = DB_PATH,
    seen_db: str | None = SEEN_DB_PATH,
    countries: list[str] | None = None,
    gender: str = "all",
) -> list[str]:
    _, pools, weights = load_names_db(db_path, countries=countries, gender=gender, split_gender=True)
    seen = load_seen_set(seen_db) if seen_db else set()
    new_keys = []
    out = []
    max_attempts = max(count * 15, 2000)
    attempts = 0
    while len(out) < count and attempts < max_attempts:
        attempts += 1
        user = make_username(pools, weights, wide=(attempts > count * 2))
        if not VALID_RE.fullmatch(user):
            continue
        k = user.lower()
        if k in seen:
            continue
        pw = gen_pass(user)
        if not VALID_RE.fullmatch(pw):
            continue
        seen.add(k)
        new_keys.append(k)
        out.append(f"{user}:{pw}")
    if seen_db and new_keys:
        save_seen_keys(new_keys, seen_db)
    return out


def _save_output(rows: list[str], out_arg: str = "") -> str:
    if out_arg:
        out_path = os.path.abspath(out_arg)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    else:
        os.makedirs(BASE, exist_ok=True)
        out_path = os.path.join(BASE, f"gen_{int(time.time() * 1000)}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + ("\n" if rows else ""))
    return out_path


def _ask(label: str, default: str = "") -> str:
    d = f" \033[90m[{default}]\033[0m" if default else ""
    try:
        v = input(f"  \033[36m◈\033[0m {label}{d} \033[90m›\033[0m ").strip().strip('"').strip("'")
    except EOFError:
        v = ""
    return v or default


def _ask_yn(label: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            r = input(f"  \033[96m❯\033[0m {label} \033[90m({hint})\033[0m \033[95m›\033[0m ").strip().lower()
        except EOFError:
            r = ""
        if not r:
            return default
        if r in ("y", "yes"):
            return True
        if r in ("n", "no"):
            return False


def _print_db_stats(db_path: str, seen_db: str) -> None:
    with open(db_path, "r", encoding="utf-8") as f:
        countries = json.load(f).get("countries", {})
    print("\n  \033[1;36m── STATISTIK DATABASE ─────────────────────────────────\033[0m")
    tot_m = tot_f = tot_u = 0
    for code, entry in countries.items():
        if isinstance(entry, dict):
            m = len(dict.fromkeys(filter(None, (clean_ascii_name(x) for x in (entry.get("male") or [])))))
            fe = len(dict.fromkeys(filter(None, (clean_ascii_name(x) for x in (entry.get("female") or [])))))
            u = len(dict.fromkeys(filter(None, (clean_ascii_name(x) for x in (entry.get("male") or []) + (entry.get("female") or [])))))
        else:
            m = fe = 0
            u = len(dict.fromkeys(filter(None, (clean_ascii_name(x) for x in (entry or [])))))
        tot_m += m
        tot_f += fe
        tot_u += u
        print(f"    {code:<4}  male: {m:>4}  │  female: {fe:>4}  │  unik: {u:>4}")
    print(f"  \033[90m{'─' * 54}\033[0m")
    print(f"    Total per negara : {tot_u:,} nama ({tot_m:,} M / {tot_f:,} F)")
    print(f"    Anti-duplikat DB : {count_seen_db(seen_db):,} username ({seen_db})\n")


def interactive_menu(db_path: str = DB_PATH, seen_db: str = SEEN_DB_PATH) -> None:
    if os.name == "nt":
        os.system("")
    try:
        while True:
            codes, pools, _ = load_names_db(db_path)
            total_names = sum(len(p) for p in pools)
            total_seen = count_seen_db(seen_db)
            print("\n  \033[1;35m╭── MLBB COMBO GENERATOR ──────────────────────────────╮\033[0m")
            print(f"  \033[1;35m│\033[0m  DB Nama : \033[36m{len(codes)}\033[0m negara ({total_names:,} nama)               \033[1;35m│\033[0m")
            print(f"  \033[1;35m│\033[0m  Seen DB : \033[33m{total_seen:,}\033[0m username tersimpan               \033[1;35m│\033[0m")
            print("  \033[1;35m╰──────────────────────────────────────────────────────╯\033[0m")
            print("    \033[36m[1]\033[0m Generate Combo")
            print("    \033[36m[2]\033[0m Import Combo Lama ke Anti-Duplikat DB")
            print("    \033[36m[3]\033[0m Statistik Database")
            print("    \033[36m[4]\033[0m Reset / Kosongkan Anti-Duplikat DB")
            print("    \033[90m[0]\033[0m Keluar\n")

            choice = _ask("Pilih menu", "1")
            if choice == "0":
                print("  Keluar.")
                return
            if choice == "1":
                print(f"\n  \033[90mKode negara: {', '.join(codes)}\033[0m")
                raw_c = _ask("Negara (ALL / pisah koma)", "ALL")
                selected_c = None if raw_c.upper() == "ALL" else [x.strip().upper() for x in raw_c.split(",") if x.strip()]
                if selected_c:
                    bad = [x for x in selected_c if x not in codes]
                    if bad:
                        print(f"  \033[31m[!] Kode negara tidak dikenal: {', '.join(bad)}\033[0m")
                        continue
                gender = _ask("Gender (all/male/female)", "all").lower()
                if gender not in ("all", "male", "female"):
                    print("  \033[31m[!] Gender harus all, male, atau female.\033[0m")
                    continue
                try:
                    count = int(_ask("Jumlah combo", "10000").replace(",", "").replace("_", ""))
                    if count <= 0:
                        raise ValueError
                except ValueError:
                    print("  \033[31m[!] Jumlah harus angka > 0.\033[0m")
                    continue
                out_arg = _ask("File output (kosong = otomatis di gen/)", "")
                use_seen = _ask_yn("Aktifkan anti-duplikat DB?", default=True)

                t0 = time.perf_counter()
                active_db = seen_db if use_seen else None
                rows = generate_combos(count, db_path, seen_db=active_db, countries=selected_c, gender=gender)
                if not rows:
                    print("\n  \033[33m[!] Tidak ada combo baru yang bisa dibuat (kombinasi unik sudah habis/tersimpan di DB).\033[0m")
                    continue
                out_path = _save_output(rows, out_arg)
                dt = time.perf_counter() - t0
                if len(rows) < count:
                    print(f"\n  \033[33m[!] Hanya ter-generate {len(rows):,}/{count:,} combo unik ({dt:.2f}s) -> {out_path}\033[0m")
                else:
                    print(f"\n  \033[32m[✓] Generated {len(rows):,} combo ({dt:.2f}s) -> {out_path}\033[0m")
                if active_db:
                    print(f"  \033[90m    DB anti-duplikat sekarang: {count_seen_db(active_db):,} username\033[0m")
                if rows:
                    print("  \033[90m    Preview:\033[0m " + " | ".join(rows[:5]))
            elif choice == "2":
                fp = _ask("Path file combo/hasil lama", "")
                if not fp or not os.path.isfile(fp):
                    print("  \033[31m[!] File tidak ditemukan.\033[0m")
                    continue
                n = import_seen_file(fp, seen_db)
                print(f"  \033[32m[✓] Imported {n:,} username -> total DB: {count_seen_db(seen_db):,}\033[0m")
            elif choice == "3":
                _print_db_stats(db_path, seen_db)
            elif choice == "4":
                if _ask_yn("Yakin kosongkan seluruh histori combo_seen.db?", default=False):
                    removed = clear_seen_db(seen_db)
                    print(f"  \033[33m[✓] Dihapus {removed:,} username dari {seen_db}\033[0m")
            else:
                print("  \033[31m[!] Pilihan tidak valid.\033[0m")
    except (KeyboardInterrupt, EOFError):
        print("\n  Keluar.")


def _selftest():
    import tempfile
    codes, pools, _ = load_names_db()
    expected = {"ID", "PH", "MY", "BR", "US", "VN", "TH", "MM", "KH", "IN", "SG", "TR", "RU", "SA"}
    assert expected.issubset(set(codes)), f"Missing countries: {expected - set(codes)}"

    sub_codes, sub_pools, _ = load_names_db(countries=["ID", "PH"], gender="female")
    assert set(sub_codes) == {"ID", "PH"} and sum(len(p) for p in sub_pools) > 500

    with tempfile.TemporaryDirectory() as tmpd:
        sdb = os.path.join(tmpd, "test_seen.db")
        b1 = generate_combos(400, seen_db=sdb)
        b2 = generate_combos(400, seen_db=sdb, countries=["ID"], gender="male")
        assert len(b1) == 400 and len(b2) == 400
        assert count_seen_db(sdb) == 800
        u1 = {x.split(":", 1)[0].lower() for x in b1}
        u2 = {x.split(":", 1)[0].lower() for x in b2}
        assert u1.isdisjoint(u2), "Cross-run duplicate found!"
        for line in b1 + b2:
            u, p = line.split(":", 1)
            assert VALID_RE.fullmatch(u) and VALID_RE.fullmatch(p)
            assert len(u) >= 6 and len(p) >= 6
            assert not re.match(r"^([a-z]{6,})\1", u, re.I), f"Doubled name found: {u}"
        assert clear_seen_db(sdb) == 800
        assert count_seen_db(sdb) == 0
    print(f"[✓] gen.py selftest OK ({len(codes)} negara, {sum(len(p) for p in pools)} nama, 0 cross-run duplicates)")


def main():
    pa = argparse.ArgumentParser(description="Generator Combo MLBB + SQLite Anti-Duplikat")
    pa.add_argument("count", nargs="?", type=int, default=0, help="Jumlah combo yang dibuat (kosong = mode interaktif)")
    pa.add_argument("--out", type=str, default="", help="Path file output (default: gen/gen_<ts>.txt)")
    pa.add_argument("--country", type=str, default="", help="Filter kode negara pisah koma (misal: ID,PH,MY)")
    pa.add_argument("--gender", choices=("all", "male", "female"), default="all", help="Filter gender nama")
    pa.add_argument("--db", type=str, default=DB_PATH, help="Path JSON database nama")
    pa.add_argument("--seen-db", type=str, default=SEEN_DB_PATH, help="Path SQLite database anti-duplikat")
    pa.add_argument("--no-seen-db", action="store_true", help="Nonaktifkan simpan/cek histori duplikat")
    pa.add_argument("--import-seen", type=str, default="", help="Impor combo/output lama ke database anti-duplikat")
    pa.add_argument("--selftest", action="store_true", help="Jalankan verifikasi aturan & anti-duplikat")
    args = pa.parse_args()

    if args.selftest:
        _selftest()
        return

    seen_db = None if args.no_seen_db else args.seen_db
    if args.import_seen:
        n = import_seen_file(args.import_seen, args.seen_db)
        print(f"[✓] Imported {n:,} username ke {args.seen_db}")
        if args.count <= 0:
            return

    if args.count <= 0:
        interactive_menu(args.db, args.seen_db)
        return

    countries = [x.strip().upper() for x in args.country.split(",") if x.strip()] or None
    rows = generate_combos(args.count, args.db, seen_db=seen_db, countries=countries, gender=args.gender)
    if not rows:
        print("[!] Tidak ada combo baru yang bisa dibuat (kombinasi unik sudah habis/tersimpan di DB).")
        return
    out_path = _save_output(rows, args.out)
    total_seen = count_seen_db(seen_db) if seen_db else 0
    if len(rows) < args.count:
        print(f"[!] Hanya ter-generate {len(rows):,}/{args.count:,} combo unik -> {out_path} (DB anti-duplikat: {total_seen:,} tersimpan)")
    else:
        print(f"[✓] Generated {len(rows):,} combo -> {out_path} (DB anti-duplikat: {total_seen:,} tersimpan)")


if __name__ == "__main__":
    main()
