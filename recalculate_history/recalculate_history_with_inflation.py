from config import *
from elo import *

import shutil
import sqlite3
import math
import sys

INPUT_DB = "input.db"
OUTPUT_DB = "database.db"

def main():
    # 1) Copy the file wholesale
    try:
        shutil.copy2(INPUT_DB, OUTPUT_DB)
    except Exception as e:
        print(f"Error copying database: {e}", file=sys.stderr)
        sys.exit(1)

    # 2) Open both DBs
    src = sqlite3.connect(INPUT_DB)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(OUTPUT_DB)

    # 3) Wipe the two tables we will fully re-populate
    dst.execute("PRAGMA foreign_keys = OFF;")
    dst.execute("DELETE FROM history;")
    dst.execute("DELETE FROM armwrestlers;")
    dst.execute("DELETE FROM sqlite_sequence WHERE name IN ('history','armwrestlers');")
    dst.commit()

    # 4) Load static armwrestler data
    arm_q = """
      SELECT id, name, right_elo, left_elo,
             right_rank, left_rank,
             added_by, active_until, last_edited_by
      FROM armwrestlers
    """
    static_rows = src.execute(arm_q).fetchall()
    static = {r["id"]: r for r in static_rows}

    # 5) Load full history in chronological order (Rearranged IDs handled here)
    hist_rows = src.execute("SELECT * FROM history ORDER BY id").fetchall()

    # 6) Determine each armwrestler’s initial Elo (per arm)
    current_elo = {}
    for aw_id in static:
        for arm in ("right", "left"):
            current_elo[(aw_id, arm)] = None

    for r in hist_rows:
        arm = r["arm"]
        a1, a2 = r["armwrestler1_id"], r["armwrestler2_id"]
        if current_elo[(a1, arm)] is None:
            current_elo[(a1, arm)] = r["armwrestler1_elo"]
        if current_elo[(a2, arm)] is None:
            current_elo[(a2, arm)] = r["armwrestler2_elo"]

    # Fallback to the static table’s Elo if they never wrestled that arm
    for (aw_id, arm), val in list(current_elo.items()):
        if val is None:
            fld = "right_elo" if arm == "right" else "left_elo"
            current_elo[(aw_id, arm)] = static[aw_id][fld]

    # 7) Re-play every match using I from config.py
    for r in hist_rows:
        arm = r["arm"]
        a1, a2 = r["armwrestler1_id"], r["armwrestler2_id"]
        old_a = current_elo[(a1, arm)]
        old_b = current_elo[(a2, arm)]
        sc1, sc2 = r["armwrestler1_score"], r["armwrestler2_score"]
        fmt = r["selected_format"]
        if fmt not in SUPERMATCH_FORMATS:
            raise ValueError(f"Unknown format: {fmt!r}")
        k = SUPERMATCH_FORMATS[fmt][1]

        diff_a, diff_b = elo_diff_from_match(old_a, old_b, (sc1, sc2), k, I)
        
        new_a = old_a + diff_a
        new_b = old_b + diff_b

        dst.execute(
            """
            INSERT INTO history (
              id, armwrestler1_id, armwrestler2_id,
              arm, selected_format,
              armwrestler1_rank, armwrestler2_rank,
              armwrestler1_elo, armwrestler2_elo,
              armwrestler1_score, armwrestler2_score,
              armwrestler1_elo_diff, armwrestler2_elo_diff,
              date, added_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                r["id"], a1, a2,
                arm, fmt,
                r["armwrestler1_rank"], r["armwrestler2_rank"],
                old_a, old_b,
                sc1, sc2,
                diff_a, diff_b,
                r["date"], r["added_by"],
            )
        )

        current_elo[(a1, arm)] = new_a
        current_elo[(a2, arm)] = new_b

    # 8) INSERT every armwrestler row back, overriding only the Elo fields
    for aw_id, r in static.items():
        new_r = current_elo[(aw_id, "right")]
        new_l = current_elo[(aw_id, "left")]
        dst.execute(
            """
            INSERT INTO armwrestlers (
              id, name, right_elo, left_elo,
              right_rank, left_rank,
              added_by, active_until, last_edited_by
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                aw_id, r["name"],
                new_r, new_l,
                r["right_rank"], r["left_rank"],
                r["added_by"], r["active_until"], r["last_edited_by"]
            )
        )

    # 9) Reset the autoincrement counters
    max_h = dst.execute("SELECT MAX(id) FROM history").fetchone()[0] or 0
    max_a = dst.execute("SELECT MAX(id) FROM armwrestlers").fetchone()[0] or 0
    dst.execute("UPDATE sqlite_sequence SET seq=? WHERE name='history'", (max_h,))
    dst.execute("UPDATE sqlite_sequence SET seq=? WHERE name='armwrestlers'",(max_a,))

    dst.commit()
    src.close()
    dst.close()
    print(f"Done! Created {OUTPUT_DB} using {INPUT_DB} with inflation={I}%.")

if __name__ == "__main__":
    main()