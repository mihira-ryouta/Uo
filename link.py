"""
link.py
=======
fishnet_with_category.csv を使って、
画像ファイルと分類結果（淡水魚/海洋魚/回遊魚）をリンクさせます。

【機能】
  1. fishnet_with_category.csv から画像パスと分類結果を抽出
  2. カテゴリ別にフォルダを作成
  3. 画像ファイルをカテゴリ別フォルダにシンボリックリンク
  4. 分類結果をカテゴリ別CSVに出力

【使い方】
  python link.py --csv fishnet_results/fishnet_with_category.csv --output linked_images/
"""

import argparse
import csv
import os
import sys
from pathlib import Path
from collections import defaultdict


def load_classification_data(csv_path: Path) -> list:
    """
    fishnet_with_category.csv を読み込んで、
    [{"image_path": ..., "habitat_category": ..., "habitat_jp": ..., ...}, ...]
    のリストを返す。
    """
    rows = []
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
    except Exception as e:
        print(f"❌ CSVの読み込みに失敗: {e}")
        sys.exit(1)
    
    print(f"✅ {len(rows)} 行のデータを読み込みました")
    return rows


def detect_image_column(headers: list) -> str:
    """
    CSVのヘッダーから画像ファイルパスカラムを自動検出する。
    """
    priority = [
        "image_path", "image", "file_path", "file",
        "filepath", "filename", "path",
        "image_file", "image_name",
    ]
    for col in priority:
        if col in headers:
            return col
    
    # 部分一致
    for col in headers:
        if "path" in col.lower() or "image" in col.lower() or "file" in col.lower():
            return col
    
    return None


def organize_by_category(rows: list, image_col: str) -> dict:
    """
    行をカテゴリ別（淡水魚/海洋魚/回遊魚）に分類し、
    {category: [{row}, ...], ...} の形式で返す。
    """
    grouped = defaultdict(list)
    
    for row in rows:
        category = row.get("habitat_category", "unknown")
        category_jp = row.get("habitat_jp", "不明")
        image_path = row.get(image_col, "").strip()
        
        if not image_path:
            continue
        
        row["_category"] = category
        row["_category_jp"] = category_jp
        grouped[category].append(row)
    
    return dict(grouped)


def create_category_folders(output_dir: Path):
    """カテゴリ別フォルダを作成する。"""
    categories = ["freshwater", "marine", "migratory", "unknown"]
    paths = {}
    
    for cat in categories:
        p = output_dir / cat
        p.mkdir(parents=True, exist_ok=True)
        paths[cat] = p
    
    return paths


def link_images(
    rows: list,
    image_col: str,
    category_dict: dict,
    output_dir: Path,
    extracted_root: Path,
):
    """
    画像ファイルをカテゴリ別フォルダにシンボリックリンクする。
    """
    category_paths = create_category_folders(output_dir)
    
    stats = defaultdict(int)
    missing = []
    
    for category, group_rows in category_dict.items():
        cat_folder = category_paths.get(category, output_dir)
        
        for row in group_rows:
            image_path_str = row.get(image_col, "").strip()
            if not image_path_str:
                continue
            
            # 絶対パスと相対パスの両方を試す
            image_path = Path(image_path_str)
            if not image_path.is_absolute():
                image_path = extracted_root / image_path
            
            if not image_path.exists():
                missing.append(f"{category}: {image_path_str}")
                continue
            
            # シンボリックリンクを作成
            link_name = cat_folder / image_path.name
            try:
                # 既存リンクを削除
                if link_name.exists() or link_name.is_symlink():
                    link_name.unlink()
                
                # リンク作成
                link_name.symlink_to(image_path.resolve())
                stats[category] += 1
            except Exception as e:
                print(f"⚠️  リンク作成失敗 ({category}/{image_path.name}): {e}")
    
    return stats, missing


def save_category_csvs(
    category_dict: dict,
    output_dir: Path,
):
    """カテゴリ別のCSVファイルを作成する。"""
    category_names = {
        "freshwater": "淡水魚",
        "marine": "海洋魚",
        "migratory": "回遊魚",
        "unknown": "不明",
    }
    
    for category, rows in category_dict.items():
        if not rows:
            continue
        
        csv_path = output_dir / f"{category}_linked.csv"
        headers = list(rows[0].keys())
        
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        
        jp_name = category_names.get(category, category)
        print(f"✅ {jp_name}CSV: {csv_path}  ({len(rows)} 行)")


def run_linking(args):
    """
    メインのリンク処理
    """
    csv_path = Path(args.csv)
    output_dir = Path(args.output)
    extracted_root = Path(args.extracted) if args.extracted else csv_path.parent.parent / "fishnet"
    
    if not csv_path.exists():
        print(f"❌ CSVファイルが見つかりません: {csv_path}")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("画像と分類結果のリンク処理")
    print("=" * 60)
    
    # ── STEP 1: データ読み込み ────────────────────────────────────
    print("\nSTEP 1: CSVデータ読み込み")
    print("-" * 60)
    rows = load_classification_data(csv_path)
    
    # ── STEP 2: 画像カラム検出 ────────────────────────────────────
    print("\nSTEP 2: 画像パスカラム検出")
    print("-" * 60)
    if rows:
        headers = list(rows[0].keys())
        image_col = detect_image_column(headers)
        
        if not image_col:
            print("❌ 画像パスカラムが見つかりません")
            print(f"   使用可能なカラム: {headers}")
            sys.exit(1)
        
        print(f"✅ 画像パスカラム: {image_col}")
    
    # ── STEP 3: カテゴリ別に分類 ──────────────────────────────────
    print("\nSTEP 3: カテゴリ別に分類")
    print("-" * 60)
    category_dict = organize_by_category(rows, image_col)
    
    for cat, group in category_dict.items():
        cat_names = {
            "freshwater": "淡水魚",
            "marine": "海洋魚",
            "migratory": "回遊魚",
            "unknown": "不明",
        }
        jp = cat_names.get(cat, cat)
        print(f"  {jp} ({cat}): {len(group)} 行")
    
    # ── STEP 4: シンボリックリンク作成 ────────────────────────────
    print("\nSTEP 4: シンボリックリンク作成")
    print("-" * 60)
    print(f"出力フォルダ: {output_dir.resolve()}")
    
    stats, missing = link_images(rows, image_col, category_dict, output_dir, extracted_root)
    
    print("\n✅ リンク作成結果:")
    for cat, count in stats.items():
        cat_names = {
            "freshwater": "淡水魚",
            "marine": "海洋魚",
            "migratory": "回遊魚",
            "unknown": "不明",
        }
        jp = cat_names.get(cat, cat)
        print(f"  {jp} ({cat}): {count} ファイル")
    
    if missing:
        print(f"\n⚠️  見つからなかったファイル: {len(missing)} 件")
        for m in missing[:5]:
            print(f"    {m}")
        if len(missing) > 5:
            print(f"    ... 他 {len(missing) - 5} 件")
    
    # ── STEP 5: カテゴリ別CSV作成 ──────────────────────────────────
    print("\nSTEP 5: カテゴリ別CSVファイル作成")
    print("-" * 60)
    save_category_csvs(category_dict, output_dir)
    
    print("\n🎉 リンク処理完了!")
    print(f"   出力フォルダ: {output_dir.resolve()}")


def main():
    parser = argparse.ArgumentParser(
        description="fishnet_with_category.csv から画像と分類結果をリンクさせます"
    )
    parser.add_argument(
        "--csv", "-c", required=True,
        help="fishnet_with_category.csv のパス"
    )
    parser.add_argument(
        "--output", "-o", default="linked_images",
        help="出力フォルダ (default: linked_images/)"
    )
    parser.add_argument(
        "--extracted", "-e", default=None,
        help="展開されたfishnetフォルダのパス (省略時: CSVの親親フォルダ/fishnet)"
    )
    
    args = parser.parse_args()
    run_linking(args)


if __name__ == "__main__":
    main()
