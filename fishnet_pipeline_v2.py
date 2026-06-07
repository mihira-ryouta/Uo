"""
fishnet_pipeline_v2.py
======================
FishNet の anns/*.csv を読み込み、
淡水魚 / 海洋魚 / 回遊魚 に分類する 修正版パイプライン。

【前バージョンの問題と修正点】
  問題1: species列が属名1語のみ → Genus列を優先的に使うよう修正
  問題2: species列が空の行が54% → Genus列にフォールバック
  問題3: FishNet内蔵フラグ(freshwater/saltwater/brackish)が未活用
         → フラグ優先で分類し、フラグなしの時だけ fish_classifier を使用

【分類の優先順位 (1行ごと)】
  ① FishNet内蔵フラグ (freshwater/saltwater/brackish) が揃っていればそれを使用
  ② "Genus species" 学名で fish_classifier に問い合わせ
  ③ 属名(Genus)のみで fish_classifier に問い合わせ

【使い方】
  python fishnet_pipeline_v2.py --anns anns/train.csv
  python fishnet_pipeline_v2.py --anns anns/train.csv anns/test.csv anns/val.csv
  python fishnet_pipeline_v2.py --anns anns/train.csv --output results/
"""

import argparse
import csv
import json
import sys
from collections import defaultdict, Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from fish_classifier import classify_fish, JP_LABELS
except ImportError:
    print("❌ fish_classifier.py が見つかりません。同じフォルダに置いてください。")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
#  FishNet 科・目レベルの追加ルール
#  (fish_classifier.py に未収録の科名を補完)
# ═══════════════════════════════════════════════════════════════════

FAMILY_RULES = {
    # 海洋魚 の科
    "labridae":         "marine",   # ベラ科
    "serranidae":       "marine",   # ハタ科
    "sciaenidae":       "marine",   # ニベ科
    "blenniidae":       "marine",   # イソギンポ科
    "syngnathidae":     "marine",   # タツノオトシゴ科
    "ophichthidae":     "marine",   # ウミヘビ科
    "apogonidae":       "marine",   # テンジクダイ科
    "cottidae":         "marine",   # カジカ科 (一部淡水もいるが大多数が海洋)
    "gobiesocidae":     "marine",   # ヤセアマダイ科
    "sparidae":         "marine",   # タイ科
    "pomacentridae":    "marine",   # スズメダイ科
    "balistidae":       "marine",   # モンガラカワハギ科
    "muraenidae":       "marine",   # ウツボ科
    "holocentridae":    "marine",   # イットウダイ科
    "haemulidae":       "marine",   # イサキ科
    "mullidae":         "marine",   # ヒメジ科
    "acanthuridae":     "marine",   # ニザダイ科
    "tetraodontidae":   "marine",   # フグ科
    "diodontidae":      "marine",   # ハリセンボン科
    "monacanthidae":    "marine",   # カワハギ科
    "scorpaenidae":     "marine",   # フサカサゴ科
    "triglidae":        "marine",   # ホウボウ科
    "carangidae":       "marine",   # アジ科
    "lutjanidae":       "marine",   # フエダイ科
    "lethrinidae":      "marine",   # フエフキダイ科
    "nemipteridae":     "marine",   # イトヨリダイ科
    "kyphosidae":       "marine",   # イスズミ科
    "pomacanthidae":    "marine",   # キンチャクダイ科
    "chaetodontidae":   "marine",   # チョウチョウウオ科
    "zanclidae":        "marine",   # ツノダシ科
    "siganidae":        "marine",   # アイゴ科
    "sphyraenidae":     "marine",   # カマス科
    "trichiuridae":     "marine",   # タチウオ科
    "istiophoridae":    "marine",   # マカジキ科
    "xiphiidae":        "marine",   # メカジキ科
    "coryphaenidae":    "marine",   # シイラ科
    "rachycentridae":   "marine",   # コビア科
    "echeneidae":       "marine",   # コバンザメ科
    "bramidae":         "marine",   # イボダイ科
    "centrolophidae":   "marine",   # クロタチカマス科
    "nomeidae":         "marine",   # マナガツオ科
    "stromateidae":     "marine",   # マナガツオ科
    "pomatomidae":      "marine",   # ブルーフィッシュ科
    "lobotidae":        "marine",   # コトヒキ科
    "gerreidae":        "marine",   # クロサギ科
    "priacanthidae":    "marine",   # ネンブツダイ科
    "malacanthidae":    "marine",   # キス科
    "uranoscopidae":    "marine",   # ミシマオコゼ科
    "trachinidae":      "marine",   # クモウオ科
    "pinguipedidae":    "marine",   # トラギス科
    "callionymidae":    "marine",   # ネズッポ科
    "gobiidae":         "marine",   # ハゼ科 (大多数が海洋・汽水)
    "eleotridae":       "marine",   # ドンコ科 (大多数が海洋)
    "mugilidae":        "marine",   # ボラ科
    "sphyrnidae":       "marine",   # シュモクザメ科
    "carcharhinidae":   "marine",   # メジロザメ科
    "triakidae":        "marine",   # ドチザメ科
    "scyliorhinidae":   "marine",   # ネコザメ科
    "lamnidae":         "marine",   # ネズミザメ科
    "alopiidae":        "marine",   # オナガザメ科
    "rhincodontidae":   "marine",   # ジンベエザメ科
    "dasyatidae":       "marine",   # アカエイ科
    "myliobatidae":     "marine",   # トビエイ科
    "rajidae":          "marine",   # ガンギエイ科
    "torpedinidae":     "marine",   # シビレエイ科
    "pleuronectidae":   "marine",   # カレイ科
    "bothidae":         "marine",   # ヒダリメカレイ科
    "cynoglossidae":    "marine",   # ウシノシタ科
    "soleidae":         "marine",   # シタビラメ科
    "gadidae":          "marine",   # タラ科
    "macrouridae":      "marine",   # ソコダラ科
    "merlucciidae":     "marine",   # メルルーサ科
    "phycidae":         "marine",   # タラ科
    "clupeidae":        "marine",   # ニシン科 (大多数が海洋)
    "engraulidae":      "marine",   # カタクチイワシ科
    "sternoptychidae":  "marine",   # ハダカイワシ科
    "myctophidae":      "marine",   # ハダカイワシ科
    "lophiidae":        "marine",   # アンコウ科
    "antennariidae":    "marine",   # カエルアンコウ科
    "ogcocephalidae":   "marine",   # コウモリウオ科
    "berycidae":        "marine",   # キンメダイ科
    "zeidae":           "marine",   # マトウダイ科
    "oreosomatidae":    "marine",
    "caproidae":        "marine",
    "gasterosteidae":   "marine",   # トゲウオ科 (一部淡水もいるが大多数が海洋)
    "fistulariidae":    "marine",   # ヤガラ科
    "centriscidae":     "marine",   # カミソリウオ科
    "aulostomidae":     "marine",   # ヘラヤガラ科
    # 淡水魚 の科
    "cichlidae":        "freshwater",  # シクリッド科
    "cyprinidae":       "freshwater",  # コイ科
    "characidae":       "freshwater",  # カラシン科
    "loricariidae":     "freshwater",  # プレコ科
    "leuciscidae":      "freshwater",  # ウグイ科
    "danionidae":       "freshwater",  # ダニオ科
    "rivulidae":        "freshwater",  # リブルス科
    "xenocyprididae":   "freshwater",  # コイ科亜科
    "callichthyidae":   "freshwater",  # コリドラス科
    "astroblepidae":    "freshwater",
    "pimelodidae":      "freshwater",  # ナマズ科
    "heptapteridae":    "freshwater",
    "ictaluridae":      "freshwater",  # アイスランドナマズ科
    "mochokidae":       "freshwater",
    "bagridae":         "freshwater",  # ギギ科
    "siluridae":        "freshwater",  # ナマズ科
    "clariidae":        "freshwater",  # ウォーキングキャットフィッシュ科
    "pangasiidae":      "freshwater",  # パンガシウス科
    "schilbeidae":      "freshwater",
    "amblycipitidae":   "freshwater",
    "osteoglossidae":   "freshwater",  # アロワナ科
    "mormyridae":       "freshwater",  # ゾウギョ科
    "gymnotidae":       "freshwater",  # デンキウナギ科
    "sternopygidae":    "freshwater",
    "apteronotidae":    "freshwater",
    "hypopomidae":      "freshwater",
    "rhamphichthyidae": "freshwater",
    "esocidae":         "freshwater",  # パイク科
    "umbridae":         "freshwater",
    "cobitidae":        "freshwater",  # ドジョウ科
    "nemacheilidae":    "freshwater",  # カワドジョウ科
    "balitoridae":      "freshwater",
    "gastromyzontidae": "freshwater",
    "gobionidae":       "freshwater",
    "acheilognathidae": "freshwater",  # タナゴ科
    "tincidae":         "freshwater",
    "alburnidae":       "freshwater",
    "poeciliidae":      "freshwater",  # グッピー科
    "fundulidae":       "freshwater",
    "cyprinodontidae":  "freshwater",  # カダヤシ科
    "goodeidae":        "freshwater",
    "anablepidae":      "freshwater",
    "procatopodidae":   "freshwater",
    "nothobranchiidae": "freshwater",
    "aplocheilidae":    "freshwater",
    "valenciidae":      "freshwater",
    "adrianichthyidae": "freshwater",  # メダカ科
    "osphronemidae":    "freshwater",  # グラミー科
    "anabantidae":      "freshwater",  # アナバス科
    "channidae":        "freshwater",  # ライギョ科
    "percidae":         "freshwater",  # パーチ科
    "centrarchidae":    "freshwater",  # サンフィッシュ科
    "elassomatidae":    "freshwater",
    "lepomidae":        "freshwater",
    "amiidae":          "freshwater",  # ボウフィン科
    "lepisosteidae":    "freshwater",  # ガー科
    "polypteridae":     "freshwater",  # ポリプテルス科
    "protopteridae":    "freshwater",  # アフリカハイギョ科
    "lepidosirenidae":  "freshwater",
    "neoceratodontidae":"freshwater",
    "ceratodontidae":   "freshwater",
    "mastacembelidae":  "freshwater",  # トゲウナギ科
    "synbranchidae":    "freshwater",  # タウナギ科
    "notopteridae":     "freshwater",  # ナイフフィッシュ科
    "hiodontidae":      "freshwater",
    "catostomidae":     "freshwater",  # コイ科亜科
    "gyrinocheilidae":  "freshwater",
    "psilorhynchidae":  "freshwater",
    "vaimosidae":       "freshwater",
    # 回遊魚 の科
    "salmonidae":       "migratory",   # サケ科
    "acipenseridae":    "migratory",   # チョウザメ科
    "anguillidae":      "migratory",   # ウナギ科
    "petromyzontidae":  "migratory",   # ヤツメウナギ科
    "osmeridae":        "migratory",   # シシャモ科
    "plecoglossidae":   "migratory",   # アユ科
    "galaxiidae":       "migratory",   # ギャラクシー科
}

ORDER_RULES = {
    # 回遊魚
    "salmoniformes":    "migratory",
    "acipenseriformes": "migratory",
    "anguilliformes":   "migratory",  # ウナギ目（大半が回遊・海洋）
    "petromyzontiformes":"migratory",
    # 海洋魚
    "scombriformes":    "marine",
    "gadiformes":       "marine",
    "clupeiformes":     "marine",
    "tetraodontiformes":"marine",
    "scorpaeniformes":  "marine",
    "pleuronectiformes":"marine",
    "lophiiformes":     "marine",
    "beryciformes":     "marine",
    "zeiformes":        "marine",
    "aulopiformes":     "marine",
    "myctophiformes":   "marine",
    "carcharhiniformes":"marine",
    "lamniformes":      "marine",
    "orectolobiformes": "marine",
    "rajiformes":       "marine",
    "torpediniformes":  "marine",
    "myliobatiformes":  "marine",
    # 淡水魚
    "cypriniformes":    "freshwater",
    "siluriformes":     "freshwater",
    "characiformes":    "freshwater",
    "gymnotiformes":    "freshwater",
    "osteoglossiformes":"freshwater",
    "lepisosteiformes": "freshwater",
    "amiiformes":       "freshwater",
    "polypteriformes":  "freshwater",
    "ceratodontiformes":"freshwater",
    "lepidosireniformes":"freshwater",
}


# ═══════════════════════════════════════════════════════════════════
#  分類ロジック（優先順位付き）
# ═══════════════════════════════════════════════════════════════════

def classify_row(row: dict) -> dict:
    """
    1行を分類する。優先順位：
      ① FishNet内蔵フラグ (freshwater/saltwater/brackish)
      ② 科名ルール (Family)
      ③ 目名ルール (Order)
      ④ fish_classifier（学名 or 属名）
    """
    # ── ① FishNet 内蔵フラグ ──────────────────────────────────
    fw = str(row.get("freshwater", "")).strip() == "1"
    sw = str(row.get("saltwater",  "")).strip() == "1"
    bk = str(row.get("brackish",   "")).strip() == "1"

    flags_present = fw or sw or bk
    if flags_present:
        if fw and sw:
            cat, src = "migratory",  "fishnet_flag:fw+sw"
        elif fw and not sw:
            cat, src = "freshwater", "fishnet_flag:fw"
        elif sw and not fw:
            cat, src = "marine",     "fishnet_flag:sw"
        elif bk:
            cat, src = "marine",     "fishnet_flag:bk"
        else:
            cat, src = "unknown",    "fishnet_flag:none"
        return _make(row, cat, src)

    # ── ② 科名ルール ──────────────────────────────────────────
    family = row.get("Family", row.get("family", "")).strip().lower()
    if family in FAMILY_RULES:
        return _make(row, FAMILY_RULES[family], f"family_rule:{family}")

    # ── ③ 目名ルール ──────────────────────────────────────────
    order = row.get("Order", row.get("order", row.get("NewOrder", ""))).strip().lower()
    # FishNet の Order列は "Perciformes/Serranoidei" のようにスラッシュで区切られる場合がある
    order_base = order.split("/")[0].strip()
    if order_base in ORDER_RULES:
        return _make(row, ORDER_RULES[order_base], f"order_rule:{order_base}")

    # ── ④ fish_classifier ─────────────────────────────────────
    genus   = row.get("Genus",   row.get("genus",   "")).strip()
    species = row.get("Species", row.get("species", "")).strip()

    # 学名が "Genus species" 形式かチェック
    sp_col = row.get("species", "").strip()
    if sp_col and " " in sp_col:
        query = sp_col                        # 既に "Genus species" 形式
    elif genus and species and " " not in species:
        query = f"{genus} {species}"          # Genus + 種小名 を結合
    elif genus:
        query = genus                          # 属名のみ
    elif sp_col:
        query = sp_col                         # 種列に何か入っている
    else:
        return _make(row, "unknown", "no_name")

    r = classify_fish(query)
    return _make(row, r["category"], r["source"])


def _make(row: dict, category: str, source: str) -> dict:
    return {
        "species"      : (row.get("species") or
                          f"{row.get('Genus','')} {row.get('Species','')}".strip()),
        "genus"        : row.get("Genus", row.get("genus", "")),
        "family"       : row.get("Family", row.get("family", "")),
        "order"        : row.get("Order",  row.get("order",  row.get("NewOrder", ""))),
        "category"     : category,
        "category_jp"  : JP_LABELS.get(category, "不明"),
        "source"       : source,
        # 元のFishNetフラグも残す
        "fw_flag"      : row.get("freshwater", ""),
        "sw_flag"      : row.get("saltwater",  ""),
        "bk_flag"      : row.get("brackish",   ""),
        # 元画像パス
        "image"        : row.get("image", row.get("image_path", "")),
    }


# ═══════════════════════════════════════════════════════════════════
#  CSV 読み込み・保存
# ═══════════════════════════════════════════════════════════════════

def load_csvs(paths: list) -> tuple:
    all_rows, headers = [], []
    for p in paths:
        p = Path(p)
        if not p.exists():
            print(f"❌ ファイルが見つかりません: {p}")
            sys.exit(1)
        with open(p, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            h = reader.fieldnames or []
            rows = list(reader)
        print(f"  📄 {p.name}: {len(rows)} 行")
        all_rows.extend(rows)
        if not headers:
            headers = h
    print(f"  合計: {len(all_rows)} 行\n")
    return all_rows, headers


def save_results(results: list, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    fields = ["species", "genus", "family", "order",
              "category", "category_jp", "source",
              "fw_flag", "sw_flag", "bk_flag", "image"]

    # 全件CSV
    p = out_dir / "fish_classification.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(results)
    print(f"✅ 全件CSV:    {p}  ({len(results)} 行)")

    # カテゴリ別CSV
    for cat, jp in JP_LABELS.items():
        subset = [r for r in results if r["category"] == cat]
        if not subset:
            continue
        p = out_dir / f"fish_{cat}.csv"
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader(); w.writerows(subset)
        print(f"✅ {jp:4s}CSV:  {p}  ({len(subset)} 行)")

    # JSON
    p = out_dir / "fish_classification_detail.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"✅ 詳細JSON:   {p}")

    # サマリ表示
    total = len(results)
    cnt   = Counter(r["category"] for r in results)
    src_cnt = Counter(r["source"].split(":")[0] for r in results)

    print("\n" + "=" * 65)
    print("【分類結果サマリ】")
    print("=" * 65)
    print(f"  総行数: {total}")
    print()
    for cat, jp in JP_LABELS.items():
        n   = cnt.get(cat, 0)
        pct = n / max(total, 1) * 100
        bar = "█" * int(pct * 0.4)
        print(f"  {jp:4s} ({cat:11s}): {n:6d} 行  {pct:5.1f}%  {bar}")

    print()
    print("  【判定根拠の内訳】")
    for src, n in src_cnt.most_common():
        pct = n / max(total, 1) * 100
        print(f"    {src:30s}: {n:6d} 行  {pct:5.1f}%")

    # サマリテキスト保存
    p = out_dir / "summary.txt"
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"総行数: {total}\n")
        for cat, jp in JP_LABELS.items():
            n = cnt.get(cat, 0)
            f.write(f"{jp} ({cat}): {n} 行  {n/max(total,1)*100:.1f}%\n")
        f.write("\n判定根拠:\n")
        for src, n in src_cnt.most_common():
            f.write(f"  {src}: {n}\n")
    print(f"\n✅ サマリ:     {p}")


# ═══════════════════════════════════════════════════════════════════
#  メイン
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="FishNet CSV を分類します (v2: フラグ優先・科名ルール追加)"
    )
    parser.add_argument("--anns", "-a", nargs="+",
                        default=["anns/train.csv"],
                        help="アノテーションCSVのパス")
    parser.add_argument("--output", "-o", default="fishnet_results_v2",
                        help="出力フォルダ (デフォルト: fishnet_results_v2/)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="行ごとの出力を抑制")
    args = parser.parse_args()

    print("=" * 65)
    print("STEP 1: CSV読み込み")
    print("=" * 65)
    rows, headers = load_csvs(args.anns)

    print("=" * 65)
    print("STEP 2: 分類")
    print("=" * 65)
    results = []
    total = len(rows)
    for i, row in enumerate(rows, 1):
        r = classify_row(row)
        results.append(r)
        if not args.quiet and i % 1000 == 0:
            print(f"  {i:>6}/{total} 処理済み...")

    print(f"  完了: {total} 行")

    print("\n" + "=" * 65)
    print("STEP 3: 保存")
    print("=" * 65)
    save_results(results, Path(args.output))

    print("\n🎉 完了!")


if __name__ == "__main__":
    main()
