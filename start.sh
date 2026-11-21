#!/usr/bin/env bash
# 一键启动（真实数据演示）
#
#   ./start.sh           使用 data/ 下的真实年报库直接启动
#   ./start.sh --demo    在独立 DATA_DIR 里导入合成回归语料后再启动（仅用于抽取器回归）
#
# 不再默认执行 `app.cli seed`：合成语料会污染跨源互证。
set -e
cd "$(dirname "$0")/backend"
PY=../.venv/Scripts/python.exe
[ -x "$PY" ] || PY=../.venv/bin/python

if [ "$1" = "--demo" ]; then
  export DATA_DIR="$(cd .. && pwd)/data/regression"
  echo "[demo] 合成回归语料 → $DATA_DIR"
  "$PY" -m app.cli seed --pack beer-demo
fi

exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
