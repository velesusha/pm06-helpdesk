#!/bin/bash
set -e
cd -- "$(dirname -- "$0")"

# Prefer a project interpreter with the HTTPS dependency already installed.
task_python=''
for candidate in "${HELPDESK_PYTHON:-}" "$PWD/.venv/bin/python" "$(command -v python3 || true)"; do
  if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" -c 'import cryptography' >/dev/null 2>&1; then
    task_python="$candidate"
    break
  fi
done
if [[ -z "$task_python" ]]; then
  echo 'Нужен Python с пакетом cryptography для HTTPS.'
  echo 'Установите пакет в среду проекта: .venv/bin/python -m pip install cryptography'
  echo 'Либо используйте START-MAC.command для локального HTTP-просмотра.'
  read -r -p 'Нажмите Enter для выхода… '
  exit 1
fi

echo 'Help Desk: https://localhost:8443'
echo 'Сертификат локальный самоподписанный. Браузер может показать предупреждение.'
echo 'Логин: operator, engineer, engineer2 или admin. Пароль: Practice2026!'
echo 'Для остановки нажмите Ctrl+C в этом окне.'
"$task_python" -X utf8 app.py --seed --port 8443
