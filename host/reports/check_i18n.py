import json
import sys
from pathlib import Path

def get_keys(d, prefix=""):
    keys = set()
    for k, v in d.items():
        if k.startswith("_"):
            continue
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.update(get_keys(v, full_key))
        else:
            keys.add(full_key)
    return keys

def check_i18n():
    i18n_dir = Path(__file__).resolve().parent / "i18n"
    en_path = i18n_dir / "en.json"
    as_path = i18n_dir / "as.json"

    with open(en_path, "r", encoding="utf-8") as f:
        en_data = json.load(f)
    with open(as_path, "r", encoding="utf-8") as f:
        as_data = json.load(f)

    en_keys = get_keys(en_data)
    as_keys = get_keys(as_data)

    missing_in_as = en_keys - as_keys
    missing_in_en = as_keys - en_keys

    failed = False
    if missing_in_as:
        print("[FAIL] Keys present in en.json but missing in as.json:")
        for k in sorted(missing_in_as):
            print(f"  - {k}")
        failed = True

    if missing_in_en:
        print("[FAIL] Keys present in as.json but missing in en.json:")
        for k in sorted(missing_in_en):
            print(f"  - {k}")
        failed = True

    if not failed:
        print(f"[OK] Both i18n files have identical key sets ({len(en_keys)} leaf keys verified).")

    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(check_i18n())
