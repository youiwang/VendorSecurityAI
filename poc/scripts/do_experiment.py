import os
import csv
import json
import time
from pathlib import Path
import re
from urllib.parse import quote_plus
import requests
from dotenv import load_dotenv

load_dotenv()

CSV_PATH = os.getenv("CSV_PATH", "VendorDeploymentCVE_20250901.csv")
AI_ENDPOINT = os.getenv("AI_ENDPOINT", "https://your-company-ai.example/api/v1/chat")
API_KEY = os.getenv("API_KEY", "")
OUT_DIR = Path("outputs/experiments")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PROMPT_VARIANTS = {
    # 1. 基準定義型 (Criteria-Defined)：給予明確的 L1-L9 定義，讓評分有一致的標準
    "criteria_defined": (
        "你是一位資深的 IT 維運與資安專家。請針對上述軟體漏洞，提供修補建議與「安裝/升級風險評估」。\n"
        "【風險等級定義 (L1~L9)】\n"
        "- L1~L3：低風險。通常為次要版本更新 (Minor patch)，幾乎無破壞性變更 (Breaking changes)，無需重啟即可套用。\n"
        "- L4~L6：中風險。可能需要重啟服務，或包含中等程度的配置變更。\n"
        "- L7~L9：高風險。屬於主版本升級 (Major upgrade)，極可能產生相容性問題或需要長時間停機。\n\n"
        "請務必以嚴格的 JSON 格式回傳，格式如下：\n"
        "{\"fix_recommendation\": \"詳細的修補指令或步驟\", \"risk_level\": \"L1\"~\"L9\", \"risk_rationale\": \"評分理由，包含是否會造成服務中斷\", \"sources\": [\"來源網址\"]}"
    ),

    # 2. 深度防禦型 (Defense-in-Depth)：強調「如果暫時無法安裝更新」的緩解措施 (Workarounds)
    "mitigation_focused": (
        "身為企業資安架構師，我們需要評估修補此 CVE 的策略。請查找 NVD 與 Vendor 官方建議。\n"
        "除了建議如何升級與安裝修補程式外，請特別考慮「若企業無法立即安裝修補程式，應如何透過修改設定或防火牆來緩解風險」。\n"
        "請評估安裝該 Patch 的風險 (L1為極安全，L9為極容易導致系統崩潰)。\n"
        "回傳 JSON 格式：\n"
        "{\"fix_recommendation\": \"官方修補建議與步驟\", \"workaround\": \"暫時性的替代緩解方案(若無則填無)\", \"risk_level\": \"L1\"~\"L9\", \"risk_rationale\": \"安裝此修補程式對系統穩定性的潛在影響\", \"sources\": []}"
    ),

    # 3. 推理鏈型 (Chain-of-Thought)：強迫 LLM 先思考再輸出 JSON，大幅降低幻覺 (Hallucination)
    "cot_analytical": (
        "你是一個嚴謹的弱點管理(Vulnerability Management)機器人。請依序進行以下思考：\n"
        "1. 確認此 CVE 的攻擊向量以及受影響的軟體版本。\n"
        "2. 判斷官方提供的修補方案（如升級到哪個版本、或修改什麼設定）。\n"
        "3. 評估套用此修補方案的「營運中斷風險 (Operational Risk)」，以 L1(最低風險) 到 L9(最高風險) 評分。\n"
        "4. 將以上思考轉化為可執行的行動建議。\n"
        "請嚴格回傳包含以下 key 的 JSON，不要輸出任何 JSON 區塊以外的文字：\n"
        "{\"thought_process\": \"你的推理過程簡述\", \"fix_recommendation\": \"具體的修補動作與處理此風險的建議\", \"risk_level\": \"L1\"~\"L9\", \"risk_rationale\": \"解釋為何給予此風險等級\", \"sources\": [\"參考資料網址\"]}"
    ),

    # 4. 開發運維一體型 (DevSecOps)：專注於自動化、指令與退版計畫 (Rollback)
    "devsecops_actionable": (
        "請以 DevSecOps 工程師的角度分析此漏洞。我們需要自動化或具體的終端機指令來修補此問題。\n"
        "請提供：\n"
        "1. 具體的更新指令 (例如 apt-get, pip install, docker pull 等) 或設定檔修改範例。\n"
        "2. 安裝風險評估 (L1: 低風險/向下相容 ~ L9: 高風險/需架構重構)。\n"
        "3. 萬一升級失敗的退版建議 (Rollback plan)。\n"
        "輸出 JSON：{\"fix_recommendation\": \"包含指令與退版建議的詳細說明\", \"risk_level\": \"L1\"~\"L9\", \"risk_rationale\": \"升級相容性與停機時間評估\", \"sources\": []}"
    )
}

DEFAULT_MODELS = [
    "CDG_gemini/gemini-3.1-flash-lite",
    "CDG_gemini/gemini-3.5-flash",
    "CDG_gemini/gemini-3.1-pro-preview",
]

# expected keys per variant for schema adherence checks
VARIANT_EXPECTED_KEYS = {
    'criteria_defined': ['fix_recommendation', 'risk_level', 'risk_rationale', 'sources'],
    'mitigation_focused': ['fix_recommendation', 'workaround', 'risk_level', 'risk_rationale', 'sources'],
    'cot_analytical': ['thought_process', 'fix_recommendation', 'risk_level', 'risk_rationale', 'sources'],
    'devsecops_actionable': ['fix_recommendation', 'risk_level', 'risk_rationale', 'sources'],
}

# Judge model name (optional) and whether to run judge automatically
JUDGE_MODEL = os.getenv('JUDGE_MODEL', '')
JUDGE_RUN = os.getenv('JUDGE_RUN', 'false').lower() in ('1','true','yes')

def extract_cve(text):
    import re
    if not text:
        return None
    m = re.search(r"(CVE-\d{4}-\d+)", text, re.IGNORECASE)
    return m.group(1).upper() if m else None

def make_phase2_prompt_template(cve_id, row, variant_text):
    return (
        f"有一個 CVE ID：{cve_id}，軟體資訊：\n"
        f"Vendor: {row.get('Vendor')}\n"
        f"Product: {row.get('Product')}\n"
        f"Version: {row.get('Version')}\n"
        f"CPE: {row.get('CPE Match')}\n\n"
        + variant_text
    )

def send_to_ai_override(prompt, model_name, timeout=30):
    if not API_KEY:
        raise RuntimeError("API_KEY not set in environment.")
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model_name, "messages": [{"role": "user", "content": prompt}]}
    start = time.time()
    resp = requests.post(AI_ENDPOINT, json=payload, headers=headers, timeout=timeout)
    latency_ms = int((time.time() - start) * 1000)
    resp.raise_for_status()
    try:
        return resp.json(), latency_ms
    except Exception:
        return {"text": resp.text}, latency_ms

def make_judge_prompt(cve_info, tested_model_output):
    return f"""你是一個嚴格的資安稽核系統。你的任務是評估另一個 AI 模型所生成的「CVE 修補建議與風險評估」是否具備高品質與實踐價值。

【原始輸入資訊】
{cve_info}

【待評估的模型輸出】
{tested_model_output}

請依據以下四個維度進行評分（分數 1~5，5分為滿分），並給出具體的扣分或加分理由：
1. Actionability (可執行性)：修補建議是否具體明確？（例如：是否有提供具體版本號或設定指令，還是只講空話）
2. Rationale_Logic (邏輯合理性)：風險評分 (L1~L9) 的理由是否合理？是否真的與該漏洞的特性相符？
3. Safety_Accuracy (資安準確性)：是否沒有產生幻覺（例如捏造不存在的軟體版本或來源網址）？
4. Formatting (格式遵循)：是否有任何多餘的廢話？JSON 格式是否乾淨俐落？

請直接回傳以下格式的 JSON，不要包含任何其他文字：
{
    "scores": {
        "actionability": int,
        "rationale_logic": int,
        "safety_accuracy": int,
        "formatting": int
    },
    "total_score": int,
    "evaluation_comments": "針對各維度評分的總結性評論，指出最大的缺點或優點"
}"""

def run_experiments(models=None, start_row=1, end_row=None, sleep_between=1.0, judge_model=None, judge_run=None):
    models = models or DEFAULT_MODELS
    results_summary = []
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            # skip until start_row
            if i < start_row:
                continue
            # stop if we've passed the end_row
            if end_row is not None and i > end_row:
                break
            cve = extract_cve(row.get('Cve Id', '') or '')
            if not cve:
                print(f"Row {i}: no CVE found, skipping")
                continue
            for model in models:
                for variant_name, variant_text in PROMPT_VARIANTS.items():
                    prompt = make_phase2_prompt_template(cve, row, variant_text)
                    print(f"Row {i} | Model {model} | Variant {variant_name}: sending request...")
                    try:
                        resp_raw, latency_ms = send_to_ai_override(prompt, model)
                    except Exception as e:
                        resp_raw = {"error": str(e)}
                        latency_ms = None

                    # extract text from model response for parsing
                    resp_text = ''
                    parsed_json = None
                    json_parse_success = False
                    parse_error = None
                    if isinstance(resp_raw, dict):
                        # try common shapes
                        if 'choices' in resp_raw and isinstance(resp_raw['choices'], list) and resp_raw['choices']:
                            ch = resp_raw['choices'][0]
                            if isinstance(ch, dict):
                                if 'message' in ch and isinstance(ch['message'], dict):
                                    resp_text = ch['message'].get('content') or ch.get('text') or ''
                                else:
                                    resp_text = ch.get('text') or ch.get('content') or ''
                        elif 'text' in resp_raw and isinstance(resp_raw['text'], str):
                            resp_text = resp_raw['text']
                        else:
                            # fallback to stringified dict
                            try:
                                resp_text = json.dumps(resp_raw, ensure_ascii=False)
                            except Exception:
                                resp_text = str(resp_raw)
                    elif isinstance(resp_raw, str):
                        resp_text = resp_raw

                    # attempt to find JSON in text
                    m = re.search(r"\{[\s\S]*\}", resp_text)
                    if m:
                        jtxt = m.group(0)
                        try:
                            parsed_json = json.loads(jtxt)
                            json_parse_success = True
                        except Exception as ex:
                            # try replacing single quotes
                            try:
                                parsed_json = json.loads(jtxt.replace("'", '"'))
                                json_parse_success = True
                            except Exception as ex2:
                                parse_error = str(ex2)
                                parsed_json = None
                    # schema adherence
                    expected_keys = VARIANT_EXPECTED_KEYS.get(variant_name, ['fix_recommendation','risk_level','risk_rationale','sources'])
                    keys_found = 0
                    if isinstance(parsed_json, dict):
                        for k in expected_keys:
                            if k in parsed_json:
                                keys_found += 1
                    schema_adherence_pct = int((keys_found / len(expected_keys)) * 100) if expected_keys else 0
                    # value validation: risk_level format
                    risk_valid = None
                    if isinstance(parsed_json, dict) and 'risk_level' in parsed_json:
                        risk_valid = bool(re.match(r'^L[1-9]$', str(parsed_json.get('risk_level'))))

                    metrics = {
                        'latency_ms': latency_ms,
                        'json_parse_success': bool(json_parse_success),
                        'parse_error': parse_error,
                        'schema_adherence_pct': schema_adherence_pct,
                        'risk_level_valid': risk_valid,
                    }

                    # optionally run judge model on the tested_model_output
                    judge_result = None
                    # prefer explicit args, fallback to env vars
                    use_judge = (judge_run if judge_run is not None else JUDGE_RUN)
                    judge_model_to_use = judge_model if judge_model is not None else JUDGE_MODEL
                    if use_judge and judge_model_to_use:
                        try:
                            judge_prompt = make_judge_prompt(f"CVE: {cve} | Vendor: {row.get('Vendor')} | Product: {row.get('Product')} | Version: {row.get('Version')}", resp_text or parsed_json)
                            jresp, jlat = send_to_ai_override(judge_prompt, judge_model_to_use)
                            judge_result = {'response': jresp, 'latency_ms': jlat, 'model': judge_model_to_use}
                        except Exception as je:
                            judge_result = {'error': str(je), 'model': judge_model_to_use}

                    out_path = OUT_DIR / f"row_{i}__{model.replace('/', '_')}__{variant_name}.json"
                    with out_path.open('w', encoding='utf-8') as of:
                        json.dump({
                            'prompt': prompt,
                            'response': resp_raw,
                            'response_text': resp_text,
                            'parsed_json': parsed_json,
                            'metrics': metrics,
                            'judge': judge_result,
                            'judge_model': judge_model_to_use if judge_result else None,
                        }, of, ensure_ascii=False, indent=2)
                    summary = {
                        "row": i,
                        "model": model,
                        "variant": variant_name,
                        "out_file": str(out_path),
                    }
                    results_summary.append(summary)
                    time.sleep(sleep_between)
    # write a small CSV summary for quick scanning
    summary_path = OUT_DIR / "summary.csv"
    with summary_path.open('w', encoding='utf-8') as sf:
        sf.write('row,model,variant,out_file\n')
        for s in results_summary:
            sf.write(f"{s['row']},{s['model']},{s['variant']},{s['out_file']}\n")
    print(f"Experiments complete, outputs in {OUT_DIR}")

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--rows', type=int, default=None, help='(legacy) How many CSV rows to run from the top')
    p.add_argument('--start', type=int, default=1, help='Start row index (1-based) to run')
    p.add_argument('--end', type=int, default=None, help='End row index (1-based) to run (inclusive)')
    p.add_argument('--sleep', type=float, default=1.0, help='Seconds between requests')
    p.add_argument('--models', nargs='*', help='Optional list of models to test')
    p.add_argument('--judge-model', type=str, default=None, help='Optional judge model to evaluate outputs')
    p.add_argument('--judge-run', action='store_true', help='If set, run the judge model for each tested output')
    args = p.parse_args()
    # determine start/end honoring legacy --rows
    start = args.start
    end = args.end
    if end is None and args.rows is not None:
        # legacy behavior: rows=N -> run rows 1..N
        start = 1 if args.start is None else args.start
        end = args.rows

    run_experiments(models=args.models, start_row=start, end_row=end, sleep_between=args.sleep, judge_model=args.judge_model, judge_run=args.judge_run)
