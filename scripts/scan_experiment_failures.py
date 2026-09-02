import json
from pathlib import Path
p=Path('outputs/experiments')
files=sorted(p.glob('row_*.json'))
errs=[]
for f in files:
    try:
        j=json.loads(f.read_text(encoding='utf-8'))
    except Exception as e:
        print('BAD JSON',f.name,e)
        errs.append((f,'bad_json',str(e)))
        continue
    resp=j.get('response')
    metrics=j.get('metrics') or {}
    parse_ok=metrics.get('json_parse_success')
    latency=metrics.get('latency_ms')
    judge=j.get('judge')
    has_error=False
    error_note=None
    if isinstance(resp, dict) and resp.get('error'):
        has_error=True
        error_note=resp.get('error')
    rt=j.get('response_text') or ''
    if any(s in str(rt) for s in ('Read timed out','Connection aborted','timed out','Timeout')):
        has_error=True
        error_note=rt
    if has_error or not parse_ok:
        errs.append((f, 'error' if has_error else 'parse_fail', error_note or parse_ok))

print('Found',len(errs),'problematic files')
for e in errs:
    print(e[0].name, e[1], str(e[2])[:300])
