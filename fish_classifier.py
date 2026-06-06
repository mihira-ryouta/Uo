"""
fish_classifier.py
==================
FishNet データセット対応 — 魚類の生息環境分類スクリプト (完全オフライン版)

【分類カテゴリ】
  - 淡水魚  (freshwater) : 淡水域のみに生息
  - 海洋魚  (marine)     : 海水域のみに生息
  - 回遊魚  (migratory)  : 淡水↔海水を行き来する（溯河性・降河性・両側回遊）

【判定の優先順位】
  1. 既知の回遊魚リスト (学名)
  2. 既知の淡水魚リスト (学名)
  3. 既知の海洋魚リスト (学名)
  4. 属名ルール (学名の第1語)
  5. 英名キーワード一致

【使い方】
  # 直接指定
  python fish_classifier.py --names "Salmo salar" "Thunnus thynnus" "Cyprinus carpio"

  # CSVファイル (FishNet形式など)
  python fish_classifier.py --input fishnet_species.csv --column species_name

  # テキストファイル (1行1種名)
  python fish_classifier.py --input species_list.txt

  # 出力先を指定
  python fish_classifier.py --input list.txt --output my_output/
"""

import argparse
import csv
import json
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════
#  既知の種リスト (学名を小文字で収録)
# ═══════════════════════════════════════════════════════════════════

# ── 回遊魚 (migratory) ──────────────────────────────────────────
MIGRATORY_SPECIES = {
    # 溯河性 Anadromous (海→川で産卵)
    "salmo salar",                       # アトランティックサーモン
    "salmo trutta",                      # ブラウントラウト (sea-run)
    "oncorhynchus tshawytscha",          # キングサーモン
    "oncorhynchus kisutch",              # シルバーサーモン
    "oncorhynchus nerka",                # ベニザケ
    "oncorhynchus mykiss",               # レインボートラウト / スチールヘッド
    "oncorhynchus keta",                 # シロザケ
    "oncorhynchus gorbuscha",            # カラフトマス
    "oncorhynchus masou",                # サクラマス
    "oncorhynchus rhodurus",             # アマゴ
    "alosa sapidissima",                 # アメリカシャッド
    "alosa fallax",                      # トワイトシャッド
    "alosa alosa",                       # ヨーロッパシャッド
    "petromyzon marinus",                # ウミヤツメ
    "lampetra fluviatilis",              # カワヤツメ
    "acipenser sturio",                  # ヨーロッパチョウザメ
    "acipenser oxyrinchus",              # アトランティックチョウザメ
    "acipenser transmontanus",           # ホワイトチョウザメ
    "acipenser medirostris",             # グリーンスタージョン
    "acipenser mikadoi",                 # カラチョウザメ
    "huso huso",                         # ベルーガチョウザメ
    "osmerus mordax",                    # レインボースメルト
    "osmerus eperlanus",                 # ヨーロッパワカサギ
    "hypomesus nipponensis",             # ワカサギ
    "hypomesus olidus",                  # キュウリウオ
    "mallotus villosus",                 # カペリン
    "spirinchus thaleichthys",           # ロングフィンスメルト
    "tenualosa ilisha",                  # ヒルサ
    "tenualosa toli",
    "clupanodon thrissa",
    # 降河性 Catadromous (川→海で産卵)
    "anguilla japonica",                 # ニホンウナギ
    "anguilla anguilla",                 # ヨーロッパウナギ
    "anguilla rostrata",                 # アメリカウナギ
    "anguilla bicolor",                  # インドウナギ
    "anguilla marmorata",                # オオウナギ
    "anguilla australis",                # ショートフィンウナギ
    "anguilla dieffenbachii",            # ロングフィンウナギ
    "anguilla reinhardtii",              # スポットフィンウナギ
    "anguilla bengalensis",
    "anguilla celebesensis",
    "galaxias maculatus",                # イナンガ
    "galaxias argenteus",                # ジャイアントコクーン
    "galaxias fasciatus",
    "gobiomorphus cotidianus",
    # 両側回遊性 Amphidromous
    "plecoglossus altivelis",            # アユ
    "sicyopterus japonicus",             # ボウズハゼ
    "rhinogobius brunneus",              # カワヨシノボリ
    "rhinogobius flumineus",             # シマヨシノボリ
    "awaous melanocephalus",
    "stenogobius hawaiiensis",
    "lentipes concolor",
    "eleotris acanthopoma",
    "kuhlia rupestris",                  # ハナメアイナメ
    "kuhlia marginata",
    "kuhlia sandvicensis",
    "neogobius melanostomus",            # ラウンドゴビー
    "mugil cephalus",                    # ボラ (一部個体群)
}

# ── 淡水魚 (freshwater) ─────────────────────────────────────────
FRESHWATER_SPECIES = {
    # コイ科
    "cyprinus carpio",                   # コイ
    "carassius auratus",                 # キンギョ
    "carassius carassius",               # フナ
    "carassius gibelio",                 # ギンブナ
    "danio rerio",                       # ゼブラフィッシュ
    "barbus barbus",                     # バーベル
    "tinca tinca",                       # テンチ
    "rutilus rutilus",                   # ローチ
    "abramis brama",                     # ブリーム
    "ctenopharyngodon idella",           # ソウギョ
    "hypophthalmichthys molitrix",       # ハクレン
    "hypophthalmichthys nobilis",        # コクレン
    "catla catla",                       # カトラ
    "labeo rohita",                      # ローフー
    "tor tor",
    "leuciscus leuciscus",
    "chrosomus erythrogaster",
    "notemigonus crysoleucas",           # ゴールデンシャイナー
    "pteronotropis hypselopterus",
    # ナマズ目
    "silurus glanis",                    # ヨーロッパナマズ
    "silurus asotus",                    # ナマズ
    "ameiurus melas",                    # ブラックブルヘッド
    "ameiurus natalis",                  # イエローブルヘッド
    "ictalurus punctatus",               # チャンネルキャットフィッシュ
    "ictalurus furcatus",                # ブルーキャットフィッシュ
    "clarias batrachus",                 # ウォーキングキャットフィッシュ
    "clarias gariepinus",                # アフリカンキャットフィッシュ
    "pangasianodon hypophthalmus",       # パンガシウス
    "pangasius pangasius",
    "hypostomus plecostomus",            # プレコ
    "pterygoplichthys pardalis",
    "corydoras paleatus",                # コリドラス
    "corydoras aeneus",
    "synodontis nigriventris",
    # スズキ目 淡水種
    "micropterus salmoides",             # オオクチバス
    "micropterus dolomieu",              # コクチバス
    "perca fluviatilis",                 # ヨーロッパパーチ
    "perca flavescens",                  # イエローパーチ
    "sander lucioperca",                 # ザンダー
    "sander vitreus",                    # ウォールアイ
    "lepomis macrochirus",               # ブルーギル
    "lepomis gibbosus",                  # パンプキンシード
    "pomoxis nigromaculatus",            # ブラッククラッピー
    "ambloplites rupestris",             # ロックバス
    # パイク・ムスキー
    "esox lucius",                       # パイク
    "esox masquinongy",                  # マスキー
    "esox niger",                        # チェーンピクレル
    # アロワナ・大型淡水魚
    "osteoglossum bicirrhosum",          # シルバーアロワナ
    "osteoglossum ferreirai",            # ブラックアロワナ
    "scleropages formosus",              # アジアアロワナ
    "scleropages jardinii",
    "arapaima gigas",                    # ピラルク
    "heterotis niloticus",               # アフリカンアロワナ
    # ガー・ボウフィン
    "lepisosteus osseus",                # ロングノーズガー
    "lepisosteus platyrhincus",          # フロリダガー
    "atractosteus spatula",              # アリゲーターガー
    "amia calva",                        # ボウフィン
    # カダヤシ・グッピー等
    "gambusia affinis",                  # カダヤシ
    "gambusia holbrooki",
    "poecilia reticulata",               # グッピー
    "poecilia latipinna",                # セルフィンモーリー
    "xiphophorus hellerii",              # ソードテール
    "xiphophorus maculatus",             # プラティ
    # 観賞魚・シクリッド等
    "betta splendens",                   # ベタ
    "pterophyllum scalare",              # エンゼルフィッシュ
    "symphysodon discus",                # ディスカス
    "astronotus ocellatus",              # オスカー
    "cichlasoma octofasciatum",          # ジャックデンプシー
    "labidochromis caeruleus",           # シクリッド
    "aulonocara nyassae",
    "pseudotropheus zebra",
    "trichogaster trichopterus",         # スリースポットグラミー
    "trichogaster lalius",               # ドワーフグラミー
    "colisa lalia",
    # ティラピア・ナイルパーチ
    "oreochromis niloticus",             # ナイルティラピア
    "oreochromis mossambicus",           # モザンビクティラピア
    "tilapia zillii",
    "sarotherodon galilaeus",
    "lates niloticus",                   # ナイルパーチ
    # ライギョ・タウナギ
    "channa argus",                      # ライギョ
    "channa striata",                    # スネークヘッド
    "channa micropeltes",                # ジャイアントスネークヘッド
    "monopterus albus",                  # タウナギ
    # ドジョウ・タナゴ等 (日本淡水魚)
    "misgurnus anguillicaudatus",        # ドジョウ
    "cobitis taenia",                    # シマドジョウ
    "rhodeus ocellatus",                 # タナゴ
    "pseudorasbora parva",               # モツゴ
    "zacco platypus",                    # オイカワ
    "zacco temminkii",                   # カワムツ
    "gnathopogon elongatus",             # タモロコ
    "pungtungia herzi",
    "acheilognathus melanogaster",       # イチモンジタナゴ
    "acheilognathus rhombeus",           # カネヒラ
    "nipponocypris temminckii",
    "squalidus chankaensis",
    "hemibarbus barbus",
    "tribolodon hakonensis",             # ウグイ (一部汽水)
    # ヤツメウナギ以外の吸盤型
    "lampetra japonica",                 # カワヤツメ
}

# ── 海洋魚 (marine) ─────────────────────────────────────────────
MARINE_SPECIES = {
    # マグロ・カツオ・サバ科
    "thunnus thynnus",                   # クロマグロ
    "thunnus albacares",                 # キハダ
    "thunnus obesus",                    # メバチ
    "thunnus alalunga",                  # ビンナガ
    "thunnus orientalis",                # タイセイヨウクロマグロ
    "thunnus atlanticus",
    "thunnus tonggol",
    "katsuwonus pelamis",                # カツオ
    "scomber japonicus",                 # マサバ
    "scomber scombrus",                  # タイセイヨウサバ
    "scomber colias",
    "sarda sarda",                       # ボニート
    "auxis rochei",                      # ヒラソウダ
    "auxis thazard",                     # マルソウダ
    "euthynnus affinis",                 # ヒガシタイヘイヨウガツオ
    "euthynnus alletteratus",
    # タラ科
    "gadus morhua",                      # タラ
    "gadus macrocephalus",               # スケトウダラ
    "theragra chalcogramma",             # スケソウダラ
    "pollachius virens",                 # ボラック
    "pollachius pollachius",
    "merluccius merluccius",             # メルルーサ
    "merluccius productus",
    "melanogrammus aeglefinus",          # ハドック
    "macruronus novaezelandiae",         # ホキ
    "boreogadus saida",                  # ホッキョクダラ
    "microgadus tomcod",
    # ニシン科
    "sardinops sagax",                   # マイワシ
    "sardina pilchardus",                # ヨーロッパイワシ
    "engraulis japonicus",               # カタクチイワシ
    "engraulis encrasicolus",            # ヨーロッパカタクチイワシ
    "engraulis ringens",                 # ペルーカタクチイワシ
    "sprattus sprattus",                 # スプラット
    # アジ科
    "trachurus japonicus",               # マアジ
    "trachurus trachurus",               # ホースマカレル
    "caranx sexfasciatus",               # ロウニンアジ
    "caranx ignobilis",                  # カスミアジ
    "caranx melampygus",
    "seriola quinqueradiata",            # ブリ
    "seriola dumerili",                  # カンパチ
    "seriola lalandi",                   # ヒラマサ
    "trachinotus carolinus",             # フロリダポンパノ
    "trachinotus falcatus",
    "naucrates ductor",                  # コバンザメ随伴魚
    "rachycentron canadum",              # コビア
    # タイ科
    "pagrus major",                      # マダイ
    "pagrus pagrus",
    "sparus aurata",                     # ギルトヘッドシーブリーム
    "diplodus sargus",
    "boops boops",
    "chrysophrys auratus",               # オーストラリアシーブリーム
    "acanthopagrus schlegelii",          # クロダイ
    "acanthopagrus latus",
    "acanthopagrus butcheri",
    "rhabdosargus sarba",
    # スズキ科
    "lateolabrax japonicus",             # スズキ
    "dicentrarchus labrax",              # ヨーロッパスズキ
    "epinephelus coioides",              # オレンジスポットグルーパー
    "epinephelus fuscoguttatus",         # タイガーグルーパー
    "epinephelus malabaricus",
    "epinephelus polyphekadion",
    "plectropomus leopardus",            # ヒョウモンハタ
    # ヒラメ・カレイ科
    "paralichthys olivaceus",            # ヒラメ
    "hippoglossus hippoglossus",         # ハリバット
    "hippoglossus stenolepis",           # タイヘイヨウハリバット
    "pleuronectes platessa",             # ヨーロッパカレイ
    "solea solea",                       # シタビラメ
    "microstomus kitt",
    "limanda aspera",
    "hippoglossoides elassodon",
    "verasper moseri",                   # ホシガレイ
    "verasper variegatus",               # マコガレイ
    "platichthys stellatus",             # ヌマガレイ
    # イシダイ・ニベ科
    "argyrosomus japonicus",             # ニベ / マゴチ類
    "pennahia argentata",
    "nibea mitsukurii",
    # フグ科
    "takifugu rubripes",                 # トラフグ
    "takifugu poecilonotus",             # コモンフグ
    "takifugu pardalis",
    "lagocephalus lunaris",
    # カジキ・メカジキ科
    "xiphias gladius",                   # メカジキ
    "makaira nigricans",                 # クロカジキ
    "makaira mazara",
    "tetrapturus audax",                 # マカジキ
    "tetrapturus albidus",               # シロカジキ
    "istiophorus platypterus",           # バショウカジキ
    # シイラ・マンボウ
    "coryphaena hippurus",               # シイラ
    "mola mola",                         # マンボウ
    # サンマ・トビウオ
    "cololabis saira",                   # サンマ
    "cypselurus agoo",                   # アゴ(トビウオ)
    "cheilopogon agoo",
    "hirundichthys oxycephalus",
    # ソウダガツオ・ハガツオ等
    "gymnosarda unicolor",
    "acanthocybium solandri",            # ワフー
    # アンコウ・マトウダイ
    "lophius piscatorius",               # アンコウ
    "lophius americanus",
    "zeus faber",                        # マトウダイ
    # タチウオ
    "trichiurus lepturus",               # タチウオ
    "lepidopus caudatus",
    # イワシ類
    "etrumeus teres",                    # ウルメイワシ
    # スズメダイ・ブダイ等サンゴ礁魚
    "amphiprion ocellaris",              # カクレクマノミ
    "amphiprion percula",
    "chromis viridis",
    "acanthurus lineatus",               # ニジハギ
    "zebrasoma velifer",
    "scarus ghobban",                    # ブダイ
    "chaetodon lunula",
    # サメ類
    "carcharodon carcharias",            # ホホジロザメ
    "isurus oxyrinchus",                 # アオザメ
    "prionace glauca",                   # ヨシキリザメ
    "rhincodon typus",                   # ジンベエザメ
    "squalus acanthias",                 # ドチザメ
    "scyliorhinus canicula",
    "carcharhinus limbatus",
    "carcharhinus leucas",               # オオメジロザメ
    "carcharhinus longimanus",           # ヨゴレ
    "lamna nasus",
    "cetorhinus maximus",                # ウバザメ
    # エイ類
    "dasyatis akajei",                   # アカエイ
    "myliobatis tobijei",                # トビエイ
    "manta birostris",                   # オニイトマキエイ
    "mobula mobular",
    # ソイ・メバル科
    "sebastes schlegelii",               # クロソイ
    "sebastes inermis",                  # メバル
    "sebastes melanops",
    "sebastes caurinus",
    "sebastes taczanowskii",
    # タラバ類
    "dissostichus eleginoides",          # パタゴニアトゥースフィッシュ
    "dissostichus mawsoni",
    # その他
    "lutjanus campechanus",              # レッドスナッパー
    "lutjanus argentimaculatus",
    "lutjanus fulvus",
    "halichoeres trimaculatus",
    "labroides dimidiatus",
    "thalassoma lunare",
    "bodianus rufus",
    "acanthurus coeruleus",
}

# ── 英名キーワード ──────────────────────────────────────────────

MIGRATORY_KEYWORDS = [
    "salmon", "steelhead", "sea trout", "sea-run",
    "rainbow trout", "brown trout", "brook trout",
    " eel", "anguilla",
    "ayu", "sweetfish",
    "lamprey", "petromyzon",
    "sturgeon", "acipenser",
    "shad", "alewife",
    "smelt", "osmerus",
    "hilsa",
    "amphidromous",
    "anadromous", "catadromous",
]

FRESHWATER_KEYWORDS = [
    "carp", "goldfish", "crucian", "roach", "bream", "tench",
    "catfish", "bullhead", "bass", "pike", "walleye", "perch",
    "tilapia", "cichlid", "guppy", "betta", "arowana",
    "zebrafish", "danio", "barbel",
    "gar ", "bowfin", "piranha",
    "freshwater", "river ", "lake ",
    "loach", "dojo",
    "sweetfish",
]

MARINE_KEYWORDS = [
    "tuna", "mackerel", "sardine", "anchovy", "herring",
    "cod", "haddock", "pollock", "hake",
    "snapper", "grouper", "sea bass", "seabream",
    "flounder", "halibut", "sole", "plaice",
    "shark", " ray", "skate",
    "swordfish", "marlin", "sailfish", "wahoo",
    "mahi", "dorado",
    "jack ", "pompano", "amberjack", "yellowtail",
    "ocean", "marine ", "pelagic", "reef",
    "pufferfish", "fugu", "blowfish",
    "rockfish", "scorpionfish",
    "clownfish", "damselfish", "parrotfish",
    "trevally", "cobia",
    "saury", "flyingfish",
]

# ── 属名ルール (学名の第1語) ────────────────────────────────────
TAXON_RULES = {
    # 回遊魚
    "oncorhynchus": "migratory",
    "salmo":        "migratory",
    "salvelinus":   "migratory",
    "anguilla":     "migratory",
    "petromyzon":   "migratory",
    "lampetra":     "migratory",
    "acipenser":    "migratory",
    "huso":         "migratory",
    "plecoglossus": "migratory",
    "osmerus":      "migratory",
    "hypomesus":    "migratory",
    "alosa":        "migratory",
    "tenualosa":    "migratory",
    "galaxias":     "migratory",
    "sicyopterus":  "migratory",
    "kuhlia":       "migratory",
    "mallotus":     "migratory",
    "spirinchus":   "migratory",
    # 淡水魚
    "cyprinus":         "freshwater",
    "carassius":        "freshwater",
    "micropterus":      "freshwater",
    "esox":             "freshwater",
    "perca":            "freshwater",
    "sander":           "freshwater",
    "lepomis":          "freshwater",
    "ictalurus":        "freshwater",
    "silurus":          "freshwater",
    "clarias":          "freshwater",
    "pangasianodon":    "freshwater",
    "pangasius":        "freshwater",
    "osteoglossum":     "freshwater",
    "scleropages":      "freshwater",
    "arapaima":         "freshwater",
    "lepisosteus":      "freshwater",
    "atractosteus":     "freshwater",
    "poecilia":         "freshwater",
    "xiphophorus":      "freshwater",
    "gambusia":         "freshwater",
    "betta":            "freshwater",
    "pterophyllum":     "freshwater",
    "symphysodon":      "freshwater",
    "oreochromis":      "freshwater",
    "tilapia":          "freshwater",
    "ctenopharyngodon": "freshwater",
    "hypophthalmichthys":"freshwater",
    "channa":           "freshwater",
    "misgurnus":        "freshwater",
    "rhodeus":          "freshwater",
    "zacco":            "freshwater",
    "pseudorasbora":    "freshwater",
    "cobitis":          "freshwater",
    "danio":            "freshwater",
    "lates":            "freshwater",
    "corydoras":        "freshwater",
    "astronotus":       "freshwater",
    "trichogaster":     "freshwater",
    "barbus":           "freshwater",
    "acheilognathus":   "freshwater",
    "labeo":            "freshwater",
    "amia":             "freshwater",
    # 海洋魚
    "thunnus":          "marine",
    "katsuwonus":       "marine",
    "scomber":          "marine",
    "gadus":            "marine",
    "merluccius":       "marine",
    "melanogrammus":    "marine",
    "pollachius":       "marine",
    "sardinops":        "marine",
    "sardina":          "marine",
    "engraulis":        "marine",
    "trachurus":        "marine",
    "seriola":          "marine",
    "pagrus":           "marine",
    "sparus":           "marine",
    "dicentrarchus":    "marine",
    "lateolabrax":      "marine",
    "epinephelus":      "marine",
    "paralichthys":     "marine",
    "hippoglossus":     "marine",
    "takifugu":         "marine",
    "xiphias":          "marine",
    "makaira":          "marine",
    "tetrapturus":      "marine",
    "coryphaena":       "marine",
    "lutjanus":         "marine",
    "sebastes":         "marine",
    "trichiurus":       "marine",
    "argyrosomus":      "marine",
    "dissostichus":     "marine",
    "isurus":           "marine",
    "carcharodon":      "marine",
    "prionace":         "marine",
    "rhincodon":        "marine",
    "carcharhinus":     "marine",
    "acanthopagrus":    "marine",
    "caranx":           "marine",
    "auxis":            "marine",
    "euthynnus":        "marine",
    "sarda":            "marine",
    "sprattus":         "marine",
    "mola":             "marine",
    "lophius":          "marine",
    "zeus":             "marine",
    "amphiprion":       "marine",
    "scarus":           "marine",
    "acanthurus":       "marine",
    "dasyatis":         "marine",
    "manta":            "marine",
    "mobula":           "marine",
    "plectropomus":     "marine",
    "rachycentron":     "marine",
    "acanthocybium":    "marine",
}


# ═══════════════════════════════════════════════════════════════════
#  分類ロジック
# ═══════════════════════════════════════════════════════════════════

JP_LABELS = {
    "freshwater": "淡水魚",
    "marine":     "海洋魚",
    "migratory":  "回遊魚",
    "unknown":    "不明",
}


def _norm(name: str) -> str:
    return name.strip().lower()


def _kw(name_lower: str, keywords: list) -> bool:
    return any(kw in name_lower for kw in keywords)


def classify_fish(species_name: str) -> dict:
    """
    1種の魚を分類する。

    Returns
    -------
    dict:
        species     : 入力名
        category    : "freshwater" | "marine" | "migratory" | "unknown"
        category_jp : 日本語ラベル
        source      : 判定根拠
    """
    nl = _norm(species_name)

    # 1. 完全一致リスト
    if nl in MIGRATORY_SPECIES:
        src = "known_migratory"
    elif nl in FRESHWATER_SPECIES:
        src = "known_freshwater"
    elif nl in MARINE_SPECIES:
        src = "known_marine"
    else:
        src = None

    if src:
        cat = src.replace("known_", "")
        return {"species": species_name, "category": cat,
                "category_jp": JP_LABELS[cat], "source": src}

    # 2. 属名ルール
    genus = nl.split()[0] if nl.split() else ""
    if genus in TAXON_RULES:
        cat = TAXON_RULES[genus]
        return {"species": species_name, "category": cat,
                "category_jp": JP_LABELS[cat], "source": f"taxon:{genus}"}

    # 3. 英名キーワード (回遊 > 淡水 > 海洋 の順で優先)
    if _kw(nl, MIGRATORY_KEYWORDS):
        cat = "migratory"
    elif _kw(nl, FRESHWATER_KEYWORDS):
        cat = "freshwater"
    elif _kw(nl, MARINE_KEYWORDS):
        cat = "marine"
    else:
        cat = "unknown"

    src = f"keyword_{cat}" if cat != "unknown" else "unresolved"
    return {"species": species_name, "category": cat,
            "category_jp": JP_LABELS[cat], "source": src}


def classify_list(species_list: list, verbose: bool = True) -> list:
    """複数種をまとめて分類する。"""
    results = []
    total = len(species_list)
    for i, name in enumerate(species_list, 1):
        name = name.strip()
        if not name:
            continue
        r = classify_fish(name)
        if verbose:
            print(f"[{i:>4}/{total}] {r['category_jp']:4s}  {name}  ({r['source']})")
        results.append(r)
    return results


def get_by_category(results: list, category: str) -> list:
    """特定カテゴリの結果だけ返す。
    category: 'freshwater' | 'marine' | 'migratory' | 'unknown'
    """
    return [r for r in results if r["category"] == category]


# ═══════════════════════════════════════════════════════════════════
#  入出力ユーティリティ
# ═══════════════════════════════════════════════════════════════════

def load_from_csv(path: str, column: str) -> list:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row[column] for row in reader if row.get(column)]


def load_from_txt(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def save_results(results: list, out_dir: str = "."):
    out = Path(out_dir)
    out.mkdir(exist_ok=True)

    # CSV
    csv_path = out / "fish_classification.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["species", "category", "category_jp", "source"])
        w.writeheader()
        w.writerows(results)
    print(f"\n✅ CSV保存: {csv_path}")

    # JSON
    json_path = out / "fish_classification_detail.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON保存: {json_path}")

    # カテゴリ別CSV
    for cat, jp in JP_LABELS.items():
        subset = get_by_category(results, cat)
        if not subset:
            continue
        p = out / f"fish_{cat}.csv"
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["species", "category", "category_jp", "source"])
            w.writeheader()
            w.writerows(subset)
        print(f"✅ {jp}CSV: {p}  ({len(subset)}種)")

    # サマリ表示
    print("\n" + "=" * 60)
    print("【分類結果サマリ】")
    print("=" * 60)
    for cat, jp in JP_LABELS.items():
        sp_list = get_by_category(results, cat)
        print(f"\n{jp} ({cat}) ─── {len(sp_list)} 種")
        for r in sp_list[:15]:
            print(f"  • {r['species']}")
        if len(sp_list) > 15:
            print(f"  … 他 {len(sp_list) - 15} 種")

    return csv_path, json_path


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="魚類を 淡水魚 / 海洋魚 / 回遊魚 に分類します (完全オフライン)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", "-i", help="入力ファイル (.csv or .txt)")
    group.add_argument("--names", "-n", nargs="+", metavar="SPECIES",
                       help="種名を直接指定")
    parser.add_argument("--column", "-c", default="species_name",
                        help="CSVの列名 (default: species_name)")
    parser.add_argument("--output", "-o", default="output",
                        help="出力ディレクトリ (default: output/)")
    args = parser.parse_args()

    if args.names:
        species_list = args.names
    elif args.input.lower().endswith(".csv"):
        species_list = load_from_csv(args.input, args.column)
    else:
        species_list = load_from_txt(args.input)

    print(f"対象種数: {len(species_list)}")
    print("-" * 60)

    results = classify_list(species_list)
    save_results(results, out_dir=args.output)


if __name__ == "__main__":
    main()
