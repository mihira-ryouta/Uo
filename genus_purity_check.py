"""
genus_purity_check.py
=====================
属 (Genus) の生息環境フラグが純粋か混在しているかを判定し、
信頼できる行だけを抽出するクリーニングスクリプト。

【背景】
FishNet データセットの 40,600 行 (53.7%) は species 列が空で、
Genus レベルでしかラベル付けされていない。同じ属に淡水種と海洋種が
混在する場合 (例: Oncorhynchus, Salvelinus, Gasterosteus)、
属レベルの分類は生物学的に誤りになる。

【処理内容】
1. 各属について、所属する全種の habitat フラグを集計
2. 属を「純粋」「やや純粋」「混在」「不明」に分類
3. 信頼度ランクを各行に付与
   high   : 学名 (2語) あり + 種固有のフラグあり
   medium : 属名のみ + 純粋な属
   low    : 属名のみ + やや純粋な属
   exclude: 属名のみ + 混在する属 → 分析から除外

【使い方】
  python genus_purity_check.py --csv fishnet_with_category.csv
  python genus_purity_check.py --csv fishnet_with_category.csv --threshold 0.9
"""

import argparse
import csv
import sys
from collections import defaultdict, Counter
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


# ═══════════════════════════════════════════════════════════════════
#  habitat フラグから生息環境カテゴリを判定
# ═══════════════════════════════════════════════════════════════════

def habitat_pattern(row: dict) -> str:
    """
    1行の freshwater/saltwater/brackish フラグから生息環境を判定。
    """
    fw = str(row.get("freshwater", "")).strip() == "1"
    sw = str(row.get("saltwater",  "")).strip() == "1"
    bk = str(row.get("brackish",   "")).strip() == "1"

    if fw and sw:
        return "migratory"
    elif fw and not sw:
        return "freshwater"
    elif sw and not fw:
        return "marine"
    elif bk:
        return "brackish"
    else:
        return "unknown"


# ═══════════════════════════════════════════════════════════════════
#  属の純粋度を計算
# ═══════════════════════════════════════════════════════════════════

def analyze_genus_purity(rows: list) -> dict:
    """
    各属について habitat パターンの分布を集計し、純粋度スコアを算出する。

    Returns
    -------
    {genus_name: {
        "n_rows": int,                    # この属の総行数
        "n_unique_species": int,          # 属内のユニーク種数
        "patterns": Counter,              # habitat パターンの分布
        "dominant": str,                  # 最頻パターン
        "purity_score": float,            # 0〜1, 最頻パターンの割合
        "is_pure": bool,                  # threshold以上なら True
        "trust_level": str,               # "pure" / "mostly_pure" / "mixed" / "unknown"
    }}
    """
    genus_data = defaultdict(lambda: {
        "rows": [],
        "species_set": set(),
        "patterns": Counter(),
    })

    for row in rows:
        genus = row.get("Genus", "").strip()
        if not genus:
            continue
        species = row.get("species", "").strip()
        pattern = habitat_pattern(row)

        genus_data[genus]["rows"].append(row)
        genus_data[genus]["patterns"][pattern] += 1
        if species:
            genus_data[genus]["species_set"].add(species)

    return genus_data


def classify_genus(genus_info: dict, threshold: float = 0.9) -> dict:
    """
    属の純粋度を判定して trust_level を付与する。
    """
    patterns = genus_info["patterns"]
    total    = sum(patterns.values())

    if total == 0 or "unknown" in patterns and patterns["unknown"] == total:
        return {"dominant": "unknown", "purity_score": 0.0,
                "is_pure": False, "trust_level": "unknown_genus"}

    # unknownを除外して判定
    valid = Counter({k: v for k, v in patterns.items() if k != "unknown"})
    valid_total = sum(valid.values())

    if valid_total == 0:
        return {"dominant": "unknown", "purity_score": 0.0,
                "is_pure": False, "trust_level": "unknown_genus"}

    dominant, dominant_count = valid.most_common(1)[0]
    purity_score = dominant_count / valid_total

    if len(valid) == 1:
        trust_level = "pure"               # 1パターンのみ → 完全純粋
    elif purity_score >= threshold:
        trust_level = "mostly_pure"        # 90%以上が最頻パターン
    else:
        trust_level = "mixed"              # 混在

    return {
        "dominant"    : dominant,
        "purity_score": purity_score,
        "is_pure"     : trust_level in ("pure", "mostly_pure"),
        "trust_level" : trust_level,
    }


# ═══════════════════════════════════════════════════════════════════
#  各行に信頼度ランクを付与
# ═══════════════════════════════════════════════════════════════════

def assign_trust_to_rows(rows: list, genus_data: dict) -> list:
    """
    各行に trust_level を付与する。

    high    : 学名(2語)あり + フラグあり → 種固有のラベル
    medium  : 属名のみ + 純粋な属      → 信頼可能
    low     : 属名のみ + やや純粋な属  → 注意して使用
    exclude : 属名のみ + 混在する属    → 分析から除外
    """
    enriched = []
    counter = Counter()

    for row in rows:
        genus   = row.get("Genus", "").strip()
        species = row.get("species", "").strip()
        has_full_name = bool(species and " " in species)
        pattern = habitat_pattern(row)

        if not genus:
            row_trust = "no_genus"
        elif has_full_name and pattern != "unknown":
            row_trust = "high"
        elif pattern == "unknown":
            row_trust = "exclude_no_flag"
        else:
            g_info = genus_data.get(genus, {})
            g_class = g_info.get("classification", {})
            tl = g_class.get("trust_level", "unknown_genus")
            if tl == "pure":
                row_trust = "medium"
            elif tl == "mostly_pure":
                row_trust = "low"
            elif tl == "mixed":
                row_trust = "exclude_mixed_genus"
            else:
                row_trust = "exclude_unknown"

        row["genus_pattern"]    = pattern
        row["trust_level"]      = row_trust
        row["dominant_habitat"] = genus_data.get(genus, {}).get(
            "classification", {}).get("dominant", "unknown")
        row["purity_score"]     = genus_data.get(genus, {}).get(
            "classification", {}).get("purity_score", 0.0)
        enriched.append(row)
        counter[row_trust] += 1

    return enriched, counter


# ═══════════════════════════════════════════════════════════════════
#  CSV読み込み・保存
# ═══════════════════════════════════════════════════════════════════

def load_csv(path: Path) -> tuple:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)
    print(f"📄 読み込み: {len(rows)} 行")
    return rows, headers


def save_genus_report(genus_data: dict, out_path: Path):
    """属ごとの純粋度レポートを CSV 保存。"""
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Genus", "n_rows", "n_unique_species",
            "n_freshwater", "n_marine", "n_migratory", "n_brackish", "n_unknown",
            "dominant_habitat", "purity_score", "trust_level",
        ])
        for genus, info in sorted(genus_data.items()):
            p = info["patterns"]
            c = info["classification"]
            w.writerow([
                genus,
                len(info["rows"]),
                len(info["species_set"]),
                p.get("freshwater", 0),
                p.get("marine", 0),
                p.get("migratory", 0),
                p.get("brackish", 0),
                p.get("unknown", 0),
                c["dominant"],
                f"{c['purity_score']:.3f}",
                c["trust_level"],
            ])
    print(f"✅ 属別レポート: {out_path}")


def save_trustworthy_dataset(rows: list, headers: list, out_dir: Path):
    """信頼度別にデータセットを分割保存。"""
    new_headers = headers + ["genus_pattern", "trust_level",
                              "dominant_habitat", "purity_score"]

    # 全行 + trust_level 付き
    p_all = out_dir / "all_rows_with_trust.csv"
    with open(p_all, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=new_headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"✅ 全行(信頼度付):  {p_all}")

    # 分析に使える行のみ (high + medium)
    trustworthy = [r for r in rows if r["trust_level"] in ("high", "medium")]
    p_t = out_dir / "trustworthy_for_analysis.csv"
    with open(p_t, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=new_headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(trustworthy)
    print(f"✅ 分析用(high+med):{p_t}  ({len(trustworthy)} 行)")

    # 注意付きで使える行 (+ low)
    cautious = [r for r in rows if r["trust_level"] in ("high", "medium", "low")]
    p_c = out_dir / "cautious_for_analysis.csv"
    with open(p_c, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=new_headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(cautious)
    print(f"✅ 注意付(+low):    {p_c}  ({len(cautious)} 行)")

    # 除外された行 (混在属など)
    excluded = [r for r in rows if r["trust_level"].startswith("exclude")]
    p_e = out_dir / "excluded_rows.csv"
    with open(p_e, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=new_headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(excluded)
    print(f"✅ 除外行:          {p_e}  ({len(excluded)} 行)")


# ═══════════════════════════════════════════════════════════════════
#  可視化
# ═══════════════════════════════════════════════════════════════════

def plot_summary(genus_data: dict, trust_counter: Counter, out_dir: Path):
    plt.rcParams['font.family'] = ['DejaVu Sans']

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.patch.set_facecolor('#0d1117')

    # ── 左: 属の信頼度分布 ──
    ax = axes[0]
    ax.set_facecolor('#161b22')
    genus_trust = Counter(g["classification"]["trust_level"] for g in genus_data.values())
    labels = ["pure", "mostly_pure", "mixed", "unknown_genus"]
    label_jp = ["純粋", "やや純粋", "混在(問題)", "不明"]
    colors = ['#2d8c4e', '#7ab87a', '#c04040', '#888888']
    values = [genus_trust.get(l, 0) for l in labels]
    bars = ax.bar(label_jp, values, color=colors, alpha=0.85)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + max(values)*0.01,
                f'{v}', ha='center', va='bottom', color='white', fontsize=11, weight='bold')
    ax.set_title('Genus Purity Distribution', color='white', fontsize=12)
    ax.set_ylabel('Number of Genera', color='white')
    ax.tick_params(colors='#bbbbbb')
    for sp in ['top', 'right']: ax.spines[sp].set_visible(False)
    ax.spines['bottom'].set_color('#444'); ax.spines['left'].set_color('#444')

    # ── 右: 行の信頼度分布 ──
    ax = axes[1]
    ax.set_facecolor('#161b22')
    trust_order = ["high", "medium", "low",
                   "exclude_mixed_genus", "exclude_no_flag", "exclude_unknown"]
    trust_jp = ["high\n(学名+フラグ)", "medium\n(純粋属)", "low\n(やや純粋)",
                "exclude\n(混在属)", "exclude\n(フラグなし)", "exclude\n(その他)"]
    colors2 = ['#1a6bb0', '#2d8c4e', '#c0a020', '#c04040', '#882020', '#444444']
    values2 = [trust_counter.get(t, 0) for t in trust_order]
    bars = ax.bar(trust_jp, values2, color=colors2, alpha=0.85)
    for b, v in zip(bars, values2):
        pct = v / max(sum(values2), 1) * 100
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + max(values2)*0.01,
                f'{v}\n({pct:.1f}%)', ha='center', va='bottom',
                color='white', fontsize=9, weight='bold')
    ax.set_title('Row Trust Level Distribution', color='white', fontsize=12)
    ax.set_ylabel('Number of Rows', color='white')
    ax.tick_params(colors='#bbbbbb', labelsize=8)
    for sp in ['top', 'right']: ax.spines[sp].set_visible(False)
    ax.spines['bottom'].set_color('#444'); ax.spines['left'].set_color('#444')

    plt.tight_layout()
    p = out_dir / "purity_summary.png"
    plt.savefig(p, dpi=120, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    print(f"✅ 可視化:          {p}")


# ═══════════════════════════════════════════════════════════════════
#  メイン
# ═══════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="属の純粋度を判定してデータをクリーニング")
    ap.add_argument("--csv", "-c", required=True, help="fishnet_with_category.csv のパス")
    ap.add_argument("--output", "-o", default="purity_results", help="出力フォルダ")
    ap.add_argument("--threshold", "-t", type=float, default=0.9,
                    help="やや純粋とみなす閾値 (デフォルト: 0.9)")
    args = ap.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 65)
    print("STEP 1: CSV読み込み")
    print("=" * 65)
    rows, headers = load_csv(Path(args.csv))

    print("\n" + "=" * 65)
    print("STEP 2: 属の純粋度を解析")
    print("=" * 65)
    genus_data = analyze_genus_purity(rows)
    print(f"  ユニーク属数: {len(genus_data)}")

    for genus, info in genus_data.items():
        info["classification"] = classify_genus(info, threshold=args.threshold)

    # 属レベルのサマリ
    genus_trust = Counter(g["classification"]["trust_level"] for g in genus_data.values())
    print(f"\n  【属の純粋度分布】")
    for tl in ["pure", "mostly_pure", "mixed", "unknown_genus"]:
        n = genus_trust.get(tl, 0)
        print(f"    {tl:18s}: {n:4d} 属")

    # 混在属の具体例
    mixed_genera = [(g, info) for g, info in genus_data.items()
                    if info["classification"]["trust_level"] == "mixed"]
    mixed_genera.sort(key=lambda x: -len(x[1]["rows"]))
    print(f"\n  【混在属の例 (行数の多い順 top 10)】")
    for g, info in mixed_genera[:10]:
        p = info["patterns"]
        habitats = ", ".join(f"{k}:{v}" for k, v in p.most_common() if k != "unknown")
        print(f"    {g:25s} ({len(info['rows']):4d}行) → {habitats}")

    print("\n" + "=" * 65)
    print("STEP 3: 各行に信頼度を付与")
    print("=" * 65)
    enriched_rows, trust_counter = assign_trust_to_rows(rows, genus_data)

    print(f"\n  【行の信頼度分布】")
    total = len(enriched_rows)
    for tl, n in trust_counter.most_common():
        print(f"    {tl:25s}: {n:6d} 行 ({n/total*100:5.1f}%)")

    print("\n" + "=" * 65)
    print("STEP 4: 結果を保存")
    print("=" * 65)
    save_genus_report(genus_data, out_dir / "genus_purity_report.csv")
    save_trustworthy_dataset(enriched_rows, headers, out_dir)
    plot_summary(genus_data, trust_counter, out_dir)

    # 最終サマリレポート
    p = out_dir / "summary.txt"
    with open(p, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("属の純粋度判定 サマリレポート\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"総行数 : {total}\n")
        f.write(f"総属数 : {len(genus_data)}\n\n")
        f.write("【属の純粋度分布】\n")
        for tl in ["pure", "mostly_pure", "mixed", "unknown_genus"]:
            f.write(f"  {tl:18s}: {genus_trust.get(tl, 0)} 属\n")
        f.write("\n【行の信頼度分布】\n")
        for tl, n in trust_counter.most_common():
            f.write(f"  {tl:25s}: {n} 行 ({n/total*100:.1f}%)\n")
        f.write("\n【分析に使える行】\n")
        ana = sum(trust_counter.get(t, 0) for t in ("high", "medium"))
        ana_c = sum(trust_counter.get(t, 0) for t in ("high", "medium", "low"))
        f.write(f"  厳密 (high + medium)    : {ana} 行 ({ana/total*100:.1f}%)\n")
        f.write(f"  注意付 (+ low)          : {ana_c} 行 ({ana_c/total*100:.1f}%)\n")
        f.write("\n【混在属 (要除外) の例】\n")
        for g, info in mixed_genera[:20]:
            f.write(f"  {g}: {dict(info['patterns'])}\n")
    print(f"✅ サマリ:          {p}")

    print("\n🎉 完了!")
    print(f"   分析に進める行: {sum(trust_counter.get(t, 0) for t in ('high', 'medium'))} 行")


if __name__ == "__main__":
    main()
