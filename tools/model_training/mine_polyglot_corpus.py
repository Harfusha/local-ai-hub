import os
import sys
import json
sys.path.insert(0, os.path.abspath("."))
from tools.model_training.mine_code_triplets import CodeTripletMiner

def main():
    miner = CodeTripletMiner()

    sources = [
        # Rust (cargo crates)
        (r"C:\Users\Adam\.cargo\registry\src\index.crates.io-1949cf8c6b5b557f\aho-corasick-1.1.3", "rust", 25),
        (r"C:\Users\Adam\.cargo\registry\src\index.crates.io-1949cf8c6b5b557f\aes-gcm-0.10.3", "rust", 25),
        (r"C:\Users\Adam\.cargo\registry\src\index.crates.io-1949cf8c6b5b557f\ahash-0.8.11", "rust", 25),
        # TypeScript / React (wishflix jellyfin)
        (r"C:\Ostatní\wishflix\jellyfin-web-build\src", "typescript", 40),
        # Kotlin / Java (wishflix androidtv)
        (r"C:\Ostatní\wishflix\wishflix-androidtv\app\src\main", "kotlin", 30),
        # PHP / JS (klinika)
        (r"C:\Ostatní\Pavel\klinika", "php_js", 30),
        # Python (local-ai-hub)
        (r"C:\Users\Adam\.local-ai-hub\src\local_ai_hub", "python", 30),
    ]

    triplets_by_lang = {}
    all_mined = []

    for path, lang, limit in sources:
        if os.path.exists(path):
            t = miner.mine_from_directory(path, max_files=limit)
            triplets_by_lang[lang] = triplets_by_lang.get(lang, 0) + len(t)
            all_mined.extend(t)

    print("=== VYTĚŽENO PODLE SKUPIN / JAZYKŮ ===")
    for lang, cnt in sorted(triplets_by_lang.items(), key=lambda x: x[1], reverse=True):
        print(f"  {lang}: {cnt} tripletů")
    print(f"Celkem vytěženo nových: {len(all_mined)}")

    # Merge into state/retrieval_triplets.jsonl with deduplication
    out_path = "state/retrieval_triplets.jsonl"
    existing_lines = []
    existing_hashes = set()
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    existing_lines.append(line_str)
                    try:
                        obj = json.loads(line_str)
                        q = obj.get("query", "")
                        p = obj.get("positive", "")[:80]
                        existing_hashes.add(f"{q}:{p}")
                    except Exception:
                        pass

    print(f"Původní počet tripletů v inboxu: {len(existing_lines)}")
    added = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for t in all_mined:
            d = t.to_dict()
            q = d.get("query", "")
            p = d.get("positive", "")[:80]
            sig = f"{q}:{p}"
            if sig not in existing_hashes:
                existing_hashes.add(sig)
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
                added += 1

    total = len(existing_lines) + added
    print(f"Přidáno nových unikátních tripletů: {added}")
    print(f"Celkový stav v {out_path}: {total} řádků")

if __name__ == "__main__":
    main()
