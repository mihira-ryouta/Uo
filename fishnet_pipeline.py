"""
fishnet_pipeline.py
===================
FishNet データセットのzipを展開し、fish_classifier.py で
淡水魚 / 海洋魚 / 回遊魚 に分類するパイプラインスクリプト。

【使い方】
  # 基本 (zipと同じフォルダに fish_classifier.py を置いた場合)
  python fishnet_pipeline.py --zip fishnet.zip

  # 出力先を指定
  python fishnet_pipeline.py --zip fishnet.zip --output results/

  # すでに展開済みのフォルダがある場合 (再展開スキップ)
  python fishnet_pipeline.py --zip fishnet.zip --extracted /path/to/extracted/

  # 種ユニーク数の上限を設定 (動作テスト用)
  python fishnet_pipeline.py --zip fishnet.zip --limit 200

【出力ファイル】
  results/
    fish_classification.csv      -- 全種の分類結果
    fish_classification_detail.json
    fish_freshwater.csv          -- 淡水魚のみ
    fish_marine.csv              -- 海洋魚のみ
    fish_migratory.csv           -- 回遊魚のみ
    fishnet_with_category.csv    -- 元のアノテーション + 分類カラム付き
    summary.txt                  -- サマリレポート
"""

import argparse
import csv
import json
import os
import sys
import zipfile
from pathlib import Path
from collections import defaultdict

# ─── fish_classifier を同じフォルダから import ───────────────────
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from fish_classifier import classify_fish, JP_LABELS, get_by_category
    print("✅ fish_classifier をインポートしました")
except ImportError:
    print("❌ fish_classifier.py が見つかりません。")
    print(f"   このスクリプトと同じフォルダ ({SCRIPT_DIR}) に置いてください。")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
#  STEP 1: ZIP展開
# ═══════════════════════════════════════════════════════════════════

def extract_zip(zip_path: str, extract_to: str = None) -> Path:
    """
    zipを展開し、展開先のルートパスを返す。
    すでに展開済みの場合はスキップ。
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        print(f"❌ ZIPファイルが見つかりません: {zip_path}")
        sys.exit(1)

    if extract_to:
        out_dir = Path(extract_to)
    else:
        out_dir = zip_path.parent / zip_path.stem

    if out_dir.exists():
        print(f"📂 展開済みフォルダを使用: {out_dir}")
        return out_dir

    print(f"📦 ZIP展開中: {zip_path} → {out_dir}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        total = len(zf.namelist())
        for i, member in enumerate(zf.namelist(), 1):
            zf.extract(member, out_dir)
            if i % 5000 == 0:
                print(f"   {i:>6}/{total} ファイル展開済み...")
    print(f"✅ 展開完了: {total} ファイル → {out_dir}")
    return out_dir


# ═══════════════════════════════════════════════════════════════════
#  STEP 2: データ構造を探索してアノテーションを読み込む
# ═══════════════════════════════════════════════════════════════════

def find_annotation_files(root: Path) -> list:
    """
    展開フォルダ内のCSV/JSONアノテーションファイルを検索する。
    FishNet の anns/ フォルダを優先。
    """
    candidates = []

    # 優先1: anns/ フォルダ
    for p in root.rglob("anns/*.csv"):
        candidates.append(p)

    # 優先2: ルート直下のCSV
    if not candidates:
        for p in root.glob("*.csv"):
            candidates.append(p)

    # 優先3: 全体を再帰検索
    if not candidates:
        for p in root.rglob("*.csv"):
            if "checkpoint" not in str(p) and "__MACOSX" not in str(p):
                candidates.append(p)

    return sorted(set(candidates))


def inspect_csv(csv_path: Path) -> dict:
    """CSVの列名と先頭3行を確認する。"""
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = []
            for i, row in enumerate(reader):
                if i >= 3:
                    break
                rows.append(dict(row))
        return {"path": csv_path, "headers": headers, "sample": rows}
    except Exception as e:
        return {"path": csv_path, "headers": [], "sample": [], "error": str(e)}


def detect_species_column(headers: list) -> str:
    """
    CSV のヘッダーから種名カラムを自動検出する。
    FishNet の典型的なカラム名候補を優先順にチェック。
    """
    priority = [
        "species", "Species", "SPECIES",
        "species_name", "SpeciesName",
        "scientific_name", "ScientificName",
        "latin_name", "name",
        "genus_species",
    ]
    for col in priority:
        if col in headers:
            return col

    # 部分一致
    for col in headers:
        if "species" in col.lower() or "latin" in col.lower():
            return col

    return None


def detect_genus_column(headers: list) -> str:
    for col in headers:
        if col.lower() in ("genus", "Genus"):
            return col
    return None


def load_annotations(csv_path: Path, limit: int = None) -> list:
    """
    CSVからアノテーションを読み込み、dict のリストを返す。
    FishNetはGenus + Species を組み合わせて学名を構成することがある。
    """
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        species_col = detect_species_column(headers)
        genus_col = detect_genus_column(headers)

        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            rows.append(dict(row))

    print(f"   カラム: {headers}")
    print(f"   種名カラム: {species_col}  属名カラム: {genus_col}")
    print(f"   行数: {len(rows)}")
    return rows, species_col, genus_col


# ═══════════════════════════════════════════════════════════════════
#  STEP 3: フォルダ構造から種名を抽出 (CSVがない場合のフォールバック)
# ═══════════════════════════════════════════════════════════════════

def extract_species_from_folders(root: Path) -> list:
    """
    FishNet の画像フォルダ構造から種名を抽出する。
    構造例: root/Order/Family/Genus/Species/image.jpg
    または: root/images/Genus_species/image.jpg
    """
    species_set = set()

    # パターン1: 深い階層 (Order/Family/Genus/Species)
    for img in root.rglob("*.jpg"):
        parts = img.relative_to(root).parts
        if len(parts) >= 4:
            genus = parts[-3]
            species = parts[-2]
            if genus[0].isupper() and species[0].islower():
                species_set.add(f"{genus} {species}")

    # パターン2: Genus_species フォルダ名
    if not species_set:
        for d in root.rglob("*/"):
            name = d.name
            if "_" in name:
                parts = name.split("_", 1)
                if len(parts) == 2 and parts[0][0].isupper():
                    species_set.add(f"{parts[0]} {parts[1]}")

    return sorted(species_set)


# ═══════════════════════════════════════════════════════════════════
#  STEP 4: 種名リストを作成して分類
# ═══════════════════════════════════════════════════════════════════

def build_species_list(rows: list, species_col: str, genus_col: str) -> dict:
    """
    アノテーション行から「学名 → 行リスト」の辞書を作成する。
    重複を除いて1種1回だけ分類する。
    """
    species_map = defaultdict(list)

    for row in rows:
        # 学名の組み立て
        if species_col and row.get(species_col):
            sp = row[species_col].strip()
        else:
            sp = ""

        # Genus が別カラムにある場合は結合
        if genus_col and row.get(genus_col) and " " not in sp:
            genus = row[genus_col].strip()
            sp = f"{genus} {sp}" if sp else genus

        if sp:
            species_map[sp].append(row)

    return dict(species_map)


def classify_species_map(species_map: dict, verbose: bool = True) -> dict:
    """
    種名 → 分類結果 の辞書を返す。
    """
    results = {}
    total = len(species_map)
    print(f"\n🔍 {total} 種を分類中...")
    print("-" * 60)

    for i, species_name in enumerate(sorted(species_map.keys()), 1):
        r = classify_fish(species_name)
        results[species_name] = r
        if verbose:
            print(
                f"[{i:>5}/{total}] {r['category_jp']:4s}  {species_name}"
                f"  ({r['source']})"
            )

    return results


# ═══════════════════════════════════════════════════════════════════
#  STEP 5: 結果を保存
# ═══════════════════════════════════════════════════════════════════

def save_all_results(
    rows: list,
    species_map: dict,
    classification: dict,
    out_dir: Path,
    source_csv_path: Path = None,
):
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 分類結果リスト ──
    all_results = list(classification.values())

    # ── 全種CSV ──
    csv_path = out_dir / "fish_classification.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["species", "category", "category_jp", "source"]
        )
        w.writeheader()
        w.writerows(all_results)
    print(f"\n✅ 全分類CSV: {csv_path}")

    # ── JSON ──
    json_path = out_dir / "fish_classification_detail.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"✅ 詳細JSON:   {json_path}")

    # ── カテゴリ別CSV ──
    for cat, jp in JP_LABELS.items():
        subset = get_by_category(all_results, cat)
        if not subset:
            continue
        p = out_dir / f"fish_{cat}.csv"
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=["species", "category", "category_jp", "source"]
            )
            w.writeheader()
            w.writerows(subset)
        print(f"✅ {jp:4s}CSV:   {p}  ({len(subset)} 種)")

    # ── 元アノテーション + カテゴリ列 (FishNet形式) ──
    if rows:
        merged_path = out_dir / "fishnet_with_category.csv"
        # 元の列を確認
        sample_cols = list(rows[0].keys()) if rows else []
        new_cols = sample_cols + ["habitat_category", "habitat_jp", "classifier_source"]

        with open(merged_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=new_cols, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                # 種名を特定して分類結果をマージ
                species_key = _find_species_key(row, classification)
                if species_key:
                    r = classification[species_key]
                    row["habitat_category"] = r["category"]
                    row["habitat_jp"] = r["category_jp"]
                    row["classifier_source"] = r["source"]
                else:
                    row["habitat_category"] = "unknown"
                    row["habitat_jp"] = "不明"
                    row["classifier_source"] = "not_found"
                w.writerow(row)
        print(f"✅ マージCSV:  {merged_path}")

    # ── サマリレポート ──
    summary_path = out_dir / "summary.txt"
    cats = {cat: get_by_category(all_results, cat) for cat in JP_LABELS}
    unknown_species = [r["species"] for r in cats.get("unknown", [])]

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("FishNet 分類パイプライン サマリレポート\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"総種数 (ユニーク): {len(all_results)}\n")
        f.write(f"総画像行数:        {len(rows)}\n\n")
        for cat, jp in JP_LABELS.items():
            f.write(f"{jp} ({cat}): {len(cats[cat])} 種\n")
        f.write("\n")
        if unknown_species:
            f.write(f"【不明な種 ({len(unknown_species)}種)】\n")
            for sp in unknown_species[:50]:
                f.write(f"  {sp}\n")
            if len(unknown_species) > 50:
                f.write(f"  ... 他 {len(unknown_species) - 50} 種\n")

    print(f"✅ サマリ:     {summary_path}")

    # コンソールにもサマリ表示
    print("\n" + "=" * 60)
    print("【分類結果サマリ】")
    print("=" * 60)
    print(f"  ユニーク種数: {len(all_results)}")
    print(f"  総行数:       {len(rows)}")
    print()
    for cat, jp in JP_LABELS.items():
        n = len(cats[cat])
        bar = "█" * min(n * 40 // max(len(all_results), 1), 40)
        pct = n / max(len(all_results), 1) * 100
        print(f"  {jp:4s} ({cat:11s}): {n:5d} 種  {pct:5.1f}%  {bar}")

    if unknown_species:
        print(f"\n  ⚠️  不明な種が {len(unknown_species)} 種あります。")
        print("     fish_classifier.py の既知リストに追加することで改善できます。")


def _find_species_key(row: dict, classification: dict) -> str:
    """行から分類辞書のキーとなる種名を探す。"""
    for val in row.values():
        if isinstance(val, str) and val.strip() in classification:
            return val.strip()
    # Genus + species の結合を試みる
    genus = row.get("Genus") or row.get("genus") or ""
    species = row.get("Species") or row.get("species") or ""
    combined = f"{genus.strip()} {species.strip()}".strip()
    if combined in classification:
        return combined
    return None


# ═══════════════════════════════════════════════════════════════════
#  メインパイプライン
# ═══════════════════════════════════════════════════════════════════

def run_pipeline(args):
    out_dir = Path(args.output)

    # ── STEP 1: ZIP展開 ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 1: ZIP展開")
    print("=" * 60)
    root = extract_zip(args.zip, extract_to=args.extracted)

    # ── STEP 2: アノテーション探索 ──────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2: アノテーションファイル探索")
    print("=" * 60)
    ann_files = find_annotation_files(root)

    rows = []
    species_col = None
    genus_col = None
    source_csv = None

    if ann_files:
        print(f"📄 見つかったCSVファイル:")
        for p in ann_files:
            print(f"   {p}")

        # train.csv を優先、なければ最初のCSV
        target = next(
            (p for p in ann_files if p.name == "train.csv"), ann_files[0]
        )
        print(f"\n✅ 使用するCSV: {target}")

        info = inspect_csv(target)
        print(f"   サンプル行: {info['sample'][:1]}")

        rows, species_col, genus_col = load_annotations(target, limit=args.limit)
        source_csv = target
    else:
        print("⚠️  CSVが見つかりません。フォルダ構造から種名を抽出します...")
        folder_species = extract_species_from_folders(root)
        print(f"   フォルダから {len(folder_species)} 種を発見")
        # rowsの代わりに仮のdictリストを作成
        rows = [{"species": sp} for sp in folder_species]
        species_col = "species"

    # ── STEP 3: 種名リスト作成 ──────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 3: 種名リスト作成")
    print("=" * 60)

    if rows and species_col:
        species_map = build_species_list(rows, species_col, genus_col)
    else:
        print("❌ 種名を抽出できませんでした。")
        sys.exit(1)

    print(f"✅ ユニーク種数: {len(species_map)}")

    # ── STEP 4: 分類 ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 4: 魚類分類 (淡水魚 / 海洋魚 / 回遊魚)")
    print("=" * 60)
    classification = classify_species_map(species_map, verbose=not args.quiet)

    # ── STEP 5: 保存 ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 5: 結果保存")
    print("=" * 60)
    save_all_results(rows, species_map, classification, out_dir, source_csv)

    print("\n🎉 パイプライン完了!")
    print(f"   出力フォルダ: {out_dir.resolve()}")


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="FishNet zipを展開して魚類を淡水魚/海洋魚/回遊魚に分類します"
    )
    parser.add_argument(
        "--zip", "-z", required=True,
        help="ダウンロードした FishNet の zip ファイルパス"
    )
    parser.add_argument(
        "--extracted", "-e", default=None,
        help="展開先フォルダ (省略時: zipと同じ場所にzipと同名フォルダを作成)"
    )
    parser.add_argument(
        "--output", "-o", default="fishnet_results",
        help="出力フォルダ (default: fishnet_results/)"
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=None,
        help="読み込む行数の上限 (動作テスト用)"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="分類中の行ごとの出力を抑制"
    )

    args = parser.parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
