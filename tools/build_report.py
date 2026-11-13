"""Build a self-contained editable and printable HTML report from docs/report.md."""
from pathlib import Path
from html import escape
import base64
import json
import re

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports'
OUT.mkdir(exist_ok=True)


def inline(s):
    s=escape(s)
    s=re.sub(r'`([^`]+)`',r'<code>\1</code>',s)
    s=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',s)
    s=re.sub(r'(https?://[^\s<]+)',r'<a href="\1">\1</a>',s)
    return s


def image(path,alt):
    file=(OUT/path).resolve()
    if not file.is_relative_to(OUT.resolve()) or not file.is_file():
        return ''
    mime='image/svg+xml' if file.suffix=='.svg' else 'image/jpeg'
    data=base64.b64encode(file.read_bytes()).decode()
    return f'<figure><img src="data:{mime};base64,{data}" alt="{escape(alt)}"><figcaption>{escape(alt)}</figcaption></figure>'


def render(lines):
    parts=[];i=0
    while i<len(lines):
        s=lines[i].strip()
        if not s:i+=1;continue
        if s.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                cells=[c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c.replace(' ','')) for c in cells):rows.append(cells)
                i+=1
            parts.append('<table><thead><tr>'+''.join('<th>'+inline(c)+'</th>' for c in rows[0])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in r)+'</tr>' for r in rows[1:])+'</tbody></table>')
            continue
        match=re.match(r'^(#{1,3}) (.*)',s)
        if match:
            level=len(match[1]);parts.append(f'<h{level}>{inline(match[2])}</h{level}>');i+=1;continue
        match=re.fullmatch(r'!\[(.*?)\]\((.*?)\)',s)
        if match:parts.append(image(match[2],match[1]));i+=1;continue
        if re.match(r'^\d+\. ',s):
            items=[]
            while i<len(lines) and re.match(r'^\d+\. ',lines[i]):
                items.append('<li>'+inline(re.sub(r'^\d+\. ','',lines[i]))+'</li>');i+=1
            parts.append('<ol>'+''.join(items)+'</ol>');continue
        para=[]
        while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','![')):
            para.append(lines[i].strip());i+=1
        parts.append('<p>'+inline(' '.join(para))+'</p>')
    return '\n'.join(parts)


style='''
*{box-sizing:border-box}body{margin:0;background:#eeeff3;color:#171717;font-family:"Times New Roman",serif;font-size:16px;line-height:1.55}.toolbar{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:12px 25px;display:flex;align-items:center;justify-content:space-between;gap:15px;font:13px "Segoe UI",sans-serif;z-index:2}.toolbar button{border:1px solid #d5d5e0;border-radius:6px;padding:8px 14px;background:#fff;cursor:pointer}.toolbar span{color:#737685}.document{max-width:920px;margin:28px auto;background:#fff;padding:65px 70px;box-shadow:0 4px 25px #2221;outline:none}h1,h2,h3{color:#000;line-height:1.3;break-after:avoid}h1{font-size:27px;text-align:center;margin:0 0 35px}h2{font-size:22px;margin:34px 0 15px}h3{font-size:18px;margin:25px 0 12px}p{margin:0 0 12px;text-align:justify;orphans:3;widows:3}table{width:100%;border-collapse:collapse;font-size:13px;line-height:1.4;margin:18px 0 25px;table-layout:fixed}th,td{border:1px solid #d9d9d9;padding:9px 10px;overflow-wrap:anywhere;vertical-align:middle}th{background:#e9edf3;color:#000;font-weight:700;text-align:left}tr{break-inside:avoid}thead{display:table-header-group}tbody tr:nth-child(even){background:#fafafa}code{font:12px Consolas,monospace;background:#f4f4f4;padding:2px 4px;overflow-wrap:anywhere}a{color:#343434;overflow-wrap:anywhere}figure{margin:28px 0;break-inside:avoid}figure img{width:100%;max-height:780px;object-fit:contain;border:1px solid #eee}figcaption{text-align:center;color:#666;font-size:13px;margin-top:7px}.protocol{font:13px "Segoe UI",sans-serif;background:#fafafa;padding:15px 0}.protocol p{text-align:left}li{margin-bottom:7px}.verified{font-size:14px} @media(max-width:700px){.document{padding:30px 22px;margin:0}.toolbar{flex-wrap:wrap}.toolbar span{display:none}table{font-size:11px}th,td{padding:6px}}@page{size:A4;margin:20mm}@media print{body{background:white;font-size:12pt;line-height:1.45}.toolbar{display:none}.document{padding:0;margin:0;box-shadow:none;max-width:none}h1{font-size:19pt}h2{font-size:16pt}h3{font-size:13pt}table{font-size:9pt}figure img{max-height:235mm}a{text-decoration:none}.document:focus{outline:none}}
'''
body=render((ROOT/'docs/report.md').read_text(encoding='utf-8').splitlines())
verification=OUT/'verification.json'
if verification.is_file():
    record=json.loads(verification.read_text(encoding='utf-8'))
    proof=f'<h2>Результат фактического запуска тестов</h2><p class="verified">Дата {escape(record["checked_at"])}. Проверок {record["tests_run"]}. Успех {"да" if record["passed"] else "нет"}. Длительность {record["duration_seconds"]} сек. СУБД SQLite.</p>'
    body=body.replace('<h2>Фактические доказательства</h2>',proof+'<h2>Фактические доказательства</h2>')
versions=OUT/'versions.json'
if versions.is_file():
    record=json.loads(versions.read_text(encoding='utf-8'))
    body+='<h2>Зафиксированные версии Git</h2>'+''.join(f'<p>{escape(k)} — <code>{escape(v)}</code></p>' for k,v in record.items())
html='''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Отчёт по практике ПМ.06</title><style>'''+style+'''</style></head><body><div class="toolbar"><strong>Отчёт ПМ.06</strong><span>Текст можно редактировать прямо на странице. Заполните поля в квадратных скобках.</span><div><button id="save">Сохранить изменения</button> <button id="print">Печать</button></div></div><main class="document" contenteditable="true" aria-label="Текст отчёта">'''+body+'''</main><script>document.querySelector('#print').onclick=()=>window.print();document.querySelector('#save').onclick=()=>{const blob=new Blob(['<!doctype html>'+document.documentElement.outerHTML],{type:'text/html;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='Отчёт_ПМ06.html';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};</script></body></html>'''
(OUT/'practice.html').write_text(html,encoding='utf-8')
print('Built reports/practice.html')
