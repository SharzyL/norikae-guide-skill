#!/usr/bin/env bash
# Demo script — corner cases and mixed transport modes.
set -euo pipefail

PY="uv run python scripts/fetch_norikae_routes.py"

run() {
    echo "=========================================="
    echo "$1"
    echo "=========================================="
    echo "\$ $PY ${*:2}"
    echo
    $PY "${@:2}"
}

run "1. 基本検索 (東京 → 名古屋)" 東京 名古屋

echo
run "2. バス・徒歩混在 + 途中駅表示 (東京 → 伊勢崎)" \
    東京 伊勢崎 --first \
    --no-shinkansen --no-highway-bus --no-airline \
    --show-middle

echo
run "3. 飛行機混在 + 2ページ目 (東京 → 大阪、新幹線なし)" \
    東京 大阪 --no-shinkansen --sort-by time --page 2

echo
run "4. 多区間運賃・経由駅 (北大野 → 深戸、九頭竜湖経由)" \
    北大野 九頭竜湖 深戸 --first --sort-by transfer

echo
run "5. 有料特急 + グリーン席・現金 (新宿 → 箱根湯本)" \
    新宿 箱根湯本 --sort-by fare --ticket cash --seat-preference green

echo
run "6. フェリー混在 (島原 → 熊本)" \
    島原 熊本 --first

echo
run "7. 終電 + 在来線のみ (渋谷 → 横浜)" \
    渋谷 横浜 --last --no-shinkansen --no-express

echo
run "8. 時刻・日付指定 + 指定席 (サフィール踊り子)" \
     品川 熱海 --departure 11:08 --date 2026/07/01 --no-shinkansen
