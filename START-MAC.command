#!/bin/bash
set -e
cd -- "$(dirname -- "$0")"

task_python="${HELPDESK_PYTHON:-}"
if [[ -z "$task_python" && -x .venv/bin/python ]]; then
  task_python="$PWD/.venv/bin/python"
fi
task_python="${task_python:-$(command -v python3 || true)}"
if [[ -z "$task_python" ]] || ! "$task_python" -c 'import sqlite3, sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  echo 'Установите Python 3.9 или новее с python.org и повторите запуск.'
  read -r -p 'Нажмите Enter для выхода… ' || true
  exit 1
fi

echo 'Help Desk: http://localhost:8096'
echo 'operator, engineer, engineer2, admin / Practice2026!'
echo 'Для остановки нажмите Ctrl+C.'
exec "$task_python" -X utf8 app.py --http --port 8096 --seed
