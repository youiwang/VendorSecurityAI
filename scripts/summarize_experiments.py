import re
import json
import csv
from pathlib import Path
import ast

EXP_DIR = Path("outputs/experiments")
OUT_CSV = EXP_DIR / "comparison_summary.csv"
OUT_HTML = EXP_DIR / "comparison_summary.html"

REQUIRED_KEYS = ["fix_recommendation", "risk_level", "risk_rationale", "sources"]

def extract_text_from_response(resp):
    # resp can be dict or string
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        # common API shapes
        if 'error' in resp:
            return None
        if 'text' in resp and isinstance(resp['text'], str):
            return resp['text']
        if 'choices' in resp and isinstance(resp['choices'], list) and resp['choices']:
            ch = resp['choices'][0]
            if isinstance(ch, dict):
                # openai-like
                if 'message' in ch and isinstance(ch['message'], dict):
                    return ch['message'].get('content') or ch.get('text')
                return ch.get('text') or ch.get('content')
        # sometimes the outer dict is already the parsed JSON
        return None
    return None

def find_json_in_text(text):
    if not text:
        return None
    # try to find a JSON object in the text
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    jtxt = m.group(0)
    try:
        return json.loads(jtxt)
    except Exception:
        # try ast literal eval after replacing smart quotes
        try:
            jtxt2 = jtxt.replace('“', '"').replace("'", '"')
            return json.loads(jtxt2)
        except Exception:
            try:
                return ast.literal_eval(jtxt)
            except Exception:
                return None

def score_item(parsed_json, raw_text):
    # keys score
    keys_found = 0
    if isinstance(parsed_json, dict):
        for k in REQUIRED_KEYS:
            if k in parsed_json:
                keys_found += 1
    # sources count
    sources_count = 0
    if isinstance(parsed_json, dict) and 'sources' in parsed_json and isinstance(parsed_json['sources'], (list, tuple)):
        sources_count = len(parsed_json['sources'])
    else:
        # fallback: count http occurrences in raw text
        if raw_text:
            sources_count = len(re.findall(r"https?://", raw_text))
    length = len(raw_text) if raw_text else 0
    # basic weighted score
    kscore = keys_found / len(REQUIRED_KEYS)
    sscore = min(1.0, sources_count / 3)
    lscore = min(1.0, length / 400)
    overall = (kscore * 0.6) + (sscore * 0.3) + (lscore * 0.1)
    return {
        'keys_found': keys_found,
        'sources_count': sources_count,
        'length': length,
        'score': round(overall * 100, 1)
    }

def extract_usage_from_response(resp):
    # Common field 'usage' in OpenAI-like responses
    if not isinstance(resp, dict):
        return None
    # direct usage
    if 'usage' in resp and isinstance(resp['usage'], dict):
        return resp['usage']
    # choices[*].usage sometimes exists
    if 'choices' in resp and isinstance(resp['choices'], list):
        for ch in resp['choices']:
            if isinstance(ch, dict) and 'usage' in ch and isinstance(ch['usage'], dict):
                return ch['usage']
    # top-level fields fallback
    fields = {}
    for k in ('total_tokens', 'prompt_tokens', 'completion_tokens'):
        if k in resp:
            fields[k] = resp[k]
    return fields or None

def extract_content_from_response(resp):
    # Try to return the main model text content
    if isinstance(resp, dict):
        # choices -> message -> content
        if 'choices' in resp and isinstance(resp['choices'], list) and resp['choices']:
            ch = resp['choices'][0]
            if isinstance(ch, dict):
                if 'message' in ch and isinstance(ch['message'], dict):
                    return ch['message'].get('content') or ch.get('text')
                return ch.get('text') or ch.get('content')
        if 'text' in resp and isinstance(resp['text'], str):
            return resp['text']
    if isinstance(resp, str):
        return resp
    return None

def summarize():
    import os
    TOP_N = int(os.getenv('TOP_N', '1'))
    rows = []
    for p in sorted(EXP_DIR.glob('*.json')):
        try:
            j = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            rows.append({'file': str(p), 'error': 'invalid_json'})
            continue
        prompt = j.get('prompt')
        resp = j.get('response')
        error = ''
        raw_text = None
        parsed_json = None
        if isinstance(resp, dict) and 'error' in resp:
            error = resp.get('error')
        # try to extract text
        raw_text = extract_text_from_response(resp) or ''
        # if raw_text empty, maybe resp itself is the JSON we want
        if not raw_text and isinstance(resp, dict):
            parsed_json = resp
        else:
            parsed_json = find_json_in_text(raw_text)
        sc = score_item(parsed_json, raw_text)
        # tokens and content
        usage = extract_usage_from_response(resp) or {}
        content = extract_content_from_response(resp) or ''
        # metrics from experiment runner
        metrics = j.get('metrics', {}) or {}
        latency_ms = metrics.get('latency_ms')
        json_parse_success = metrics.get('json_parse_success')
        parse_error_field = metrics.get('parse_error')
        schema_adherence_pct_field = metrics.get('schema_adherence_pct')
        risk_level_valid_field = metrics.get('risk_level_valid')
        # judge parsing (if present in the output file)
        judge_scores = {
            'judge_actionability': None,
            'judge_rationale_logic': None,
            'judge_safety_accuracy': None,
            'judge_formatting': None,
            'judge_total_score': None,
            'judge_comments': None,
            'judge_latency_ms': None,
        }
        judge = j.get('judge')
        judge_model_field = j.get('judge_model') or None
        if isinstance(judge, dict) and judge.get('response'):
            jresp = judge.get('response')
            # extract textual content from judge response
            jtext = extract_content_from_response(jresp) or ''
            # try find JSON in judge text
            jparsed = find_json_in_text(jtext)
            if isinstance(jparsed, dict):
                scores = jparsed.get('scores') or {}
                judge_scores['judge_actionability'] = scores.get('actionability')
                judge_scores['judge_rationale_logic'] = scores.get('rationale_logic')
                judge_scores['judge_safety_accuracy'] = scores.get('safety_accuracy')
                judge_scores['judge_formatting'] = scores.get('formatting')
                judge_scores['judge_total_score'] = jparsed.get('total_score')
                judge_scores['judge_comments'] = jparsed.get('evaluation_comments')
            # latency if provided
            if 'latency_ms' in judge:
                judge_scores['judge_latency_ms'] = judge.get('latency_ms')
            # model name if provided
            if 'model' in judge:
                judge_model_field = judge.get('model')
        # derive model and variant from filename
        fn = p.name
        parts = fn.split('__')
        model = ''
        if len(parts) > 1:
            token = parts[1]
            # if the token already contains a '/', assume it's correct
            if '/' in token:
                model = token
            else:
                # token is produced by replacing '/' with '_' when writing files.
                # We want to restore the single namespace separator '/' without
                # converting other underscores (e.g., in org names like CDG_gemini).
                segs = token.split('_')
                # find first segment that looks like a model-name (contains a hyphen)
                idx = next((i for i, s in enumerate(segs) if '-' in s), None)
                if idx is not None and idx > 0:
                    model = '_'.join(segs[:idx]) + '/' + '_'.join(segs[idx:])
                else:
                    # fallback: do not change underscores to slashes
                    model = token
        variant = parts[2].rsplit('.', 1)[0] if len(parts) > 2 else ''
        try:
            file_rel = str(p.resolve().relative_to(Path.cwd().resolve()))
        except Exception:
            file_rel = str(p)
        rows.append({
            'file': file_rel,
            'model': model,
            'variant': variant,
            'error': error,
            'keys_found': sc['keys_found'],
            'sources_count': sc['sources_count'],
            'length': sc['length'],
            'score': sc['score'],
            'content': content[:1000],
            'judge_model': judge_model_field,
            'latency_ms': latency_ms,
            'json_parse_success': json_parse_success,
            'parse_error': parse_error_field,
            'schema_adherence_pct': schema_adherence_pct_field,
            'risk_level_valid': risk_level_valid_field,
            'total_tokens': usage.get('total_tokens') if isinstance(usage, dict) else None,
            'prompt_tokens': usage.get('prompt_tokens') if isinstance(usage, dict) else None,
            'completion_tokens': usage.get('completion_tokens') if isinstance(usage, dict) else None,
            **judge_scores,
        })
    # compute top-N by automatic score and judge total score
    top_by_score = sorted([r for r in rows], key=lambda x: (x.get('score') or 0), reverse=True)[:TOP_N]
    top_by_score_files = {r['file'] for r in top_by_score}
    # judge total may be None; select top by judge_total_score if present
    judge_present = [r for r in rows if r.get('judge_total_score') is not None]
    top_by_judge_files = set()
    if judge_present:
        top_by_judge = sorted(judge_present, key=lambda x: (x.get('judge_total_score') or 0), reverse=True)[:TOP_N]
        top_by_judge_files = {r['file'] for r in top_by_judge}

    # write CSV
    with OUT_CSV.open('w', encoding='utf-8', newline='') as cf:
        fieldnames = ['file','model','variant','error','keys_found','sources_count','length','score','content','judge_model','latency_ms','json_parse_success','parse_error','schema_adherence_pct','risk_level_valid','total_tokens','prompt_tokens','completion_tokens',
                  'judge_actionability','judge_rationale_logic','judge_safety_accuracy','judge_formatting','judge_total_score','judge_comments','judge_latency_ms']
        w = csv.DictWriter(cf, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    # write simple HTML table with links
    # determine unique judge models used and whether any judge runs occurred
    judge_models_used = sorted({r.get('judge_model') for r in rows if r.get('judge_model')})
    any_judge = len(judge_models_used) > 0

    with OUT_HTML.open('w', encoding='utf-8') as hf:
        hf.write('<html><head><meta charset="utf-8"><style>')
        hf.write('.top-score{background-color:#d4f7d4;} .top-judge{background-color:#d4e6ff;} table{border-collapse:collapse;} td,th{padding:6px;border:1px solid #ccc;}')
        hf.write('</style>')
        # include DataTables CSS/JS for sortable, multi-column tables
        hf.write('<link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">')
        hf.write('<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>')
        hf.write('<script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>')
        hf.write('</head><body><h2>Experiment Comparison</h2>')
        # summary about judge usage
        hf.write('<div><strong>Judge Run Enabled:</strong> ' + ('Yes' if any_judge else 'No') + '</div>')
        hf.write('<div><strong>Judge Models Used:</strong> ' + (', '.join(judge_models_used) if any_judge else '-') + '</div><br/>')
        # write table with thead/tbody and id for DataTables
        hf.write('<table id="exp-table" class="display">')
        hf.write('<thead>')
        hf.write('<tr><th>File</th><th>Model</th><th>Variant</th><th>Error</th><th>Keys Found</th><th>Sources</th><th>Length</th><th>Score</th><th>Judge Model</th><th>Latency(ms)</th><th>ParseOK</th><th>Schema%</th><th>RiskValid</th><th>Tokens</th><th>Judge Score</th></tr>')
        hf.write('</thead><tbody>')
        for r in rows:
            file_link = r['file']
            classes = []
            if file_link in top_by_score_files:
                classes.append('top-score')
            if file_link in top_by_judge_files:
                classes.append('top-judge')
            class_attr = f" class=\"{' '.join(classes)}\"" if classes else ''
            hf.write(f"<tr{class_attr}>")
            hf.write(f"<td><a href=\"{file_link}\">{file_link}</a></td>")
            hf.write(f"<td>{r['model']}</td>")
            hf.write(f"<td>{r['variant']}</td>")
            hf.write(f"<td>{r['error']}</td>")
            hf.write(f"<td>{r['keys_found']}</td>")
            hf.write(f"<td>{r['sources_count']}</td>")
            hf.write(f"<td>{r['length']}</td>")
            hf.write(f"<td>{r['score']}</td>")
            hf.write(f"<td>{r.get('judge_model','-')}</td>")
            hf.write(f"<td>{r.get('latency_ms','-')}</td>")
            hf.write(f"<td>{r.get('json_parse_success','-')}</td>")
            hf.write(f"<td>{r.get('schema_adherence_pct','-')}</td>")
            hf.write(f"<td>{r.get('risk_level_valid','-')}</td>")
            tok_summary = f"total:{r.get('total_tokens','-')} p:{r.get('prompt_tokens','-')} c:{r.get('completion_tokens','-')}"
            hf.write(f"<td>{tok_summary}</td>")
            judge_cell = r.get('judge_total_score') or '-'
            hf.write(f"<td>{judge_cell}</td>")
            hf.write('</tr>')
        hf.write('</tbody></table>')
        # initialize DataTables with multi-column ordering enabled
        hf.write('<script>$(document).ready(function(){$("#exp-table").DataTable({orderMulti:true,pageLength:25,columnDefs:[{targets:0,orderable:false}]});});</script>')
        # color legend
        hf.write('<br/><div><strong>Color Legend:</strong></div>')
        hf.write('<div style="margin-top:6px;">')
        hf.write('<div style="display:inline-block;padding:6px;margin-right:8px;background-color:#d4f7d4;border:1px solid #ccc;">Auto Top-N (highest automatic score)</div>')
        hf.write('<div style="display:inline-block;padding:6px;margin-right:8px;background-color:#d4e6ff;border:1px solid #ccc;">Judge Top-N (highest judge score)</div>')
        hf.write('<div style="display:inline-block;padding:6px;margin-right:8px;">- indicates missing value</div>')
        hf.write('</div>')
        hf.write('</body></html>')
    print(f"Wrote {OUT_CSV} and {OUT_HTML}")

if __name__ == '__main__':
    summarize()
