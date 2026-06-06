"""
fishnet_annotation_loader.py
=============================
FishNet の anns/ フォルダの CSV を読み込み、
fish_classifier.py で 淡水魚 / 海洋魚 / 回遊魚 に分類するスクリプト。

【前提ファイル構成】
  your_folder/
    fish_classifier.py          ← 分類エンジン
    fishnet_annotation_loader.py← このファイル
    anns/
      train.csv                 ← GitHub からダウンロード
      test.csv                  ← 同上
      val.csv                   ← 同上

【使い方】
  # train.csv を処理（デフォルト）
  python fishnet_annotation_loader.py

  # 複数ファイルをまとめて処理
  python fishnet_annotation_loader.py --anns anns/train.csv anns/test.csv anns/val.csv

  # 出力先を指定
  python fishnet_annotation_loader.py --output my_results/

【CSVの主なカラム (FishNet anns/)】
  image_path  : 画像の相対パス
  Class       : 分類階層 (8 クラス)
  Order       : 目
  Family      : 科
  Genus       : 属
  Species     : 種小名
  Saltwater   : 海水フラグ (0/1)
  Freshwater  : 淡水フラグ (0/1)
  Brackish    : 汽水フラグ (0/1)
  + 22種の機能的特性カラム
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

# ─── fish_classifier をインポート ────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
try:
    from fish_classifier import classify_fish, JP_LABELS, get_by_category
except ImportError:
    print("❌ fish_classifier.py が見つかりません。同じフォルダに置いてください。")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
#  FishNet CSV 読み込み
# ═══════════════════════════════════════════════════════════════════

# FishNet の anns/*.csv に含まれる主要カラム
TAXONOMY_COLS = ["Class", "Order", "Family", "Genus", "Species"]
HABITAT_COLS  = ["Saltwater", "Freshwater", "Brackish"]   # FishNet 内蔵の生息環境フラグ


def load_fishnet_csv(csv_path: Path) -> tuple[list[dict], list[str]]:
    """FishNet の CSV を読み込む。(rows, headers) を返す。"""
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for row in reader:
            rows.append(dict(row))
    print(f"  📄 {csv_path.name}: {len(rows)} 行, カラム数: {len(headers)}")
    return rows, headers


def merge_csv_files(csv_paths: list[Path]) -> tuple[list[dict], list[str]]:
    """複数の CSV ファイルを結合する。"""
    all_rows = []
    all_headers = []
    for p in csv_paths:
        rows, headers = load_fishnet_csv(p)
        all_rows.extend(rows)
        if not all_headers:
            all_headers = headers
    print(f"  合計: {len(all_rows)} 行")
    return all_rows, all_headers


def build_species_index(rows: list[dict]) -> dict[str, dict]:
    """
    Genus + Species を結合して学名を作り、
    {学名: 代表行} の辞書を返す（重複除去）。
    """
    species_index = {}
    for row in rows:
        genus   = row.get("Genus", "").strip()
        species = row.get("Species", "").strip()
        if genus and species:
            key = f"{genus} {species}"
        elif genus:
            key = genus
        else:
            continue
        if key not in species_index:
            species_index[key] = row   # 代表行として最初の1行を保持
    return species_index


# ═══════════════════════════════════════════════════════════════════
#  FishNet 内蔵フラグとの比較
# ═══════════════════════════════════════════════════════════════════

def fishnet_flag_category(row: dict) -> str:
    """
    FishNet CSV の Saltwater / Freshwater / Brackish フラグから
    生息環境カテゴリを判定する（データセット本来の情報）。
    """
    sw = str(row.get("Saltwater", "0")).strip() == "1"
    fw = str(row.get("Freshwater", "0")).strip() == "1"
    bk = str(row.get("Brackish", "0")).strip() == "1"

    if sw and fw:
        return "migratory"   # 両方に生息 → 回遊魚とみなす
    elif fw and not sw:
        return "freshwater"
    elif sw and not fw:
        return "marine"
    elif bk:
        return "marine"      # 汽水のみ → 便宜上 marine
    else:
        return "unknown"


# ═══════════════════════════════════════════════════════════════════
#  分類の実行
# ═══════════════════════════════════════════════════════════════════

def classify_all(
    species_index: dict[str, dict],
    verbose: bool = True,
) -> list[dict]:
    """
    全種を fish_classifier.py で分類し、
    FishNet 内蔵フラグとの一致/不一致も記録する。
    """
    results = []
    total = len(species_index)
    print(f"\n🔍 {total} 種を分類中...")
    print("-" * 65)

    for i, (species_name, rep_row) in enumerate(sorted(species_index.items()), 1):
        # ① fish_classifier による分類
        clf = classify_fish(species_name)

        # ② FishNet 内蔵フラグによる分類
        fishnet_cat = fishnet_flag_category(rep_row)
        fishnet_jp  = JP_LABELS.get(fishnet_cat, "不明")

        # ③ 一致チェック
        match = (clf["category"] == fishnet_cat)
        flag  = "✅" if match else "⚠️ "

        result = {
            "species"           : species_name,
            "order"             : rep_row.get("Order", ""),
            "family"            : rep_row.get("Family", ""),
            # fish_classifier の結果
            "category"          : clf["category"],
            "category_jp"       : clf["category_jp"],
            "classifier_source" : clf["source"],
            # FishNet 内蔵フラグの結果
            "fishnet_category"  : fishnet_cat,
            "fishnet_category_jp": fishnet_jp,
            "saltwater_flag"    : rep_row.get("Saltwater", ""),
            "freshwater_flag"   : rep_row.get("Freshwater", ""),
            "brackish_flag"     : rep_row.get("Brackish", ""),
            # 一致フラグ
            "match"             : match,
        }
        results.append(result)

        if verbose:
            print(
                f"[{i:>5}/{total}] {flag} "
                f"分類器:{clf['category_jp']:4s} "
                f"FishNet:{fishnet_jp:4s}  "
                f"{species_name}"
            )

    return results


# ═══════════════════════════════════════════════════════════════════
#  元 CSV に分類カラムを追加して保存
# ═══════════════════════════════════════════════════════════════════

def save_merged_csv(
    rows: list[dict],
    species_index: dict[str, dict],
    classification: list[dict],
    out_path: Path,
    original_headers: list[str],
):
    """
    元の FishNet CSV 全行に分類結果カラムを追加して保存する。
    """
    # 学名 → 分類結果 の辞書を作成
    clf_map = {r["species"]: r for r in classification}

    new_cols = ["habitat_category", "habitat_jp", "classifier_source", "fishnet_match"]
    fieldnames = original_headers + new_cols

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            genus   = row.get("Genus", "").strip()
            species = row.get("Species", "").strip()
            key     = f"{genus} {species}".strip()

            if key in clf_map:
                r = clf_map[key]
                row["habitat_category"]  = r["category"]
                row["habitat_jp"]        = r["category_jp"]
                row["classifier_source"] = r["classifier_source"]
                row["fishnet_match"]     = "1" if r["match"] else "0"
            else:
                row["habitat_category"]  = "unknown"
                row["habitat_jp"]        = "不明"
                row["classifier_source"] = "not_found"
                row["fishnet_match"]     = ""
            writer.writerow(row)


# ═══════════════════════════════════════════════════════════════════
#  保存 & サマリ
# ═══════════════════════════════════════════════════════════════════

def save_results(
    results: list[dict],
    rows: list[dict],
    original_headers: list[str],
    species_index: dict[str, dict],
    out_dir: Path,
):
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 全種 CSV ──
    p = out_dir / "fish_classification.csv"
    fieldnames = [
        "species", "order", "family",
        "category", "category_jp", "classifier_source",
        "fishnet_category", "fishnet_category_jp",
        "saltwater_flag", "freshwater_flag", "brackish_flag",
        "match",
    ]
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    print(f"\n✅ 全種CSV:    {p}")

    # ── JSON ──
    p = out_dir / "fish_classification_detail.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"✅ 詳細JSON:   {p}")

    # ── カテゴリ別 CSV ──
    for cat, jp in JP_LABELS.items():
        subset = [r for r in results if r["category"] == cat]
        if not subset:
            continue
        p = out_dir / f"fish_{cat}.csv"
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(subset)
        print(f"✅ {jp:4s}CSV:  {p}  ({len(subset)} 種)")

    # ── 元CSV + 分類カラム追加 ──
    p = out_dir / "fishnet_with_category.csv"
    save_merged_csv(rows, species_index, results, p, original_headers)
    print(f"✅ マージCSV:  {p}")

    # ── 一致率レポート ──
    total   = len(results)
    matched = sum(1 for r in results if r["match"])
    unknown = sum(1 for r in results if r["category"] == "unknown")
    mismatch_rows = [r for r in results if not r["match"] and r["fishnet_category"] != "unknown"]

    p = out_dir / "summary.txt"
    with open(p, "w", encoding="utf-8") as f:
        f.write("=" * 65 + "\n")
        f.write("FishNet アノテーション × fish_classifier 分類サマリ\n")
        f.write("=" * 65 + "\n\n")
        f.write(f"ユニーク種数 : {total}\n")
        f.write(f"一致率       : {matched}/{total} ({matched/max(total,1)*100:.1f}%)\n")
        f.write(f"不明         : {unknown} 種\n\n")

        for cat, jp in JP_LABELS.items():
            n = sum(1 for r in results if r["category"] == cat)
            pct = n / max(total, 1) * 100
            f.write(f"  {jp} ({cat}): {n} 種  {pct:.1f}%\n")

        if mismatch_rows:
            f.write(f"\n【不一致の種 ({len(mismatch_rows)} 種)】\n")
            f.write("  (分類器 vs FishNetフラグ)\n")
            for r in mismatch_rows[:30]:
                f.write(
                    f"  {r['species']}: "
                    f"分類器={r['category_jp']} / "
                    f"FishNet={r['fishnet_category_jp']}\n"
                )
    print(f"✅ サマリ:     {p}")

    # コンソール表示
    print("\n" + "=" * 65)
    print("【分類結果サマリ】")
    print("=" * 65)
    print(f"  ユニーク種数: {total}")
    print(f"  FishNetフラグとの一致率: {matched}/{total} ({matched/max(total,1)*100:.1f}%)")
    print()
    for cat, jp in JP_LABELS.items():
        n = sum(1 for r in results if r["category"] == cat)
        bar = "█" * min(n * 40 // max(total, 1), 40)
        pct = n / max(total, 1) * 100
        print(f"  {jp:4s}: {n:5d} 種  {pct:5.1f}%  {bar}")


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="FishNet anns/*.csv を読み込んで魚類を分類します"
    )
    parser.add_argument(
        "--anns", "-a", nargs="+",
        default=["anns/train.csv"],
        help="アノテーションCSVのパス (デフォルト: anns/train.csv)"
    )
    parser.add_argument(
        "--output", "-o", default="fishnet_results",
        help="出力フォルダ (デフォルト: fishnet_results/)"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="種ごとの出力を抑制"
    )
    args = parser.parse_args()

    # CSV 読み込み
    print("=" * 65)
    print("STEP 1: CSV読み込み")
    print("=" * 65)
    csv_paths = [Path(p) for p in args.anns]
    for p in csv_paths:
        if not p.exists():
            print(f"❌ ファイルが見つかりません: {p}")
            sys.exit(1)
    rows, headers = merge_csv_files(csv_paths)

    # 種名インデックス構築
    print("\n" + "=" * 65)
    print("STEP 2: 種名インデックス構築")
    print("=" * 65)
    species_index = build_species_index(rows)
    print(f"  ユニーク種数: {len(species_index)}")

    # 分類
    print("\n" + "=" * 65)
    print("STEP 3: 分類")
    print("=" * 65)
    results = classify_all(species_index, verbose=not args.quiet)

    # 保存
    print("\n" + "=" * 65)
    print("STEP 4: 保存")
    print("=" * 65)
    save_results(results, rows, headers, species_index, Path(args.output))

    print("\n🎉 完了!")


if __name__ == "__main__":
    main()