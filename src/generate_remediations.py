import os
import csv
import json
import time
import re
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

CSV_PATH = Path("data/raw/admyncec0904.csv")
PROMPT_PATH = Path("src/prompts/criteria_defined.txt")
OUT_DIR = Path("outputs/prod")
OUT_DIR.mkdir(parents=True, exist_ok=True)

AI_ENDPOINT = os.getenv("AI_ENDPOINT", "https://your-company-ai.example/api/v1/chat")
API_KEY = os.getenv("API_KEY", "")
MODEL_NAME = "CDG_gemini/gemini-3.5-flash"

def get_newest_cve(text):
    if not text:
        return None
    # Find all CVEs
    cves = re.findall(r"CVE-(\d{4})-(\d+)", text, re.IGNORECASE)
    if not cves:
        return None
    # Sort by year descending, then sequence number descending
    cves.sort(key=lambda x: (int(x[0]), int(x[1])), reverse=True)
    return f"CVE-{cves[0][0]}-{cves[0][1]}".upper()

def make_prompt(cve_id, row, prompt_template):
    return (
        f"有一個 CVE ID：{cve_id}，軟體資訊：\n"
        f"Vendor: {row.get('Vendor', '')}\n"
        f"Product: {row.get('Software Name', '')}\n"
        f"Version: {row.get('Version', '')}\n\n"
        + prompt_template
    )

def send_to_ai(prompt, model_name, timeout=30):
    if not API_KEY:
        print("Warning: API_KEY not set in environment. Using dummy response for testing.")
        # Return a dummy response if no API key is set, useful for testing the script structure
        return {"choices": [{"message": {"content": '{"fix_recommendation": "Dummy fix", "risk_level": "L1", "risk_rationale": "Dummy rationale", "sources": []}'}}]}, 100
        
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

def extract_json_from_response(resp_raw):
    resp_text = ''
    if isinstance(resp_raw, dict):
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
            try:
                resp_text = json.dumps(resp_raw, ensure_ascii=False)
            except Exception:
                resp_text = str(resp_raw)
    elif isinstance(resp_raw, str):
        resp_text = resp_raw

    m = re.search(r"\{[\s\S]*\}", resp_text)
    if m:
        jtxt = m.group(0)
        try:
            return json.loads(jtxt)
        except Exception:
            try:
                return json.loads(jtxt.replace("'", '"'))
            except Exception:
                pass
    return None

def main():
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    out_csv_path = OUT_DIR / "admyncec0904_remediated.csv"
    
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames) + ["remediation", "risk_level"]
        
        with open(out_csv_path, "w", newline='', encoding='utf-8') as out_f:
            writer = csv.DictWriter(out_f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            
            for i, row in enumerate(reader, start=1):
                cves_text = row.get('Cves', '')
                newest_cve = get_newest_cve(cves_text)
                
                out_row = row.copy()
                out_row["remediation"] = ""
                out_row["risk_level"] = ""
                
                if not newest_cve:
                    print(f"Row {i}: No CVE found, skipping.")
                    writer.writerow(out_row)
                    continue
                    
                print(f"Row {i}: Processing {newest_cve} for {row.get('Software Name')}...")
                prompt = make_prompt(newest_cve, row, prompt_template)
                
                try:
                    resp_raw, latency_ms = send_to_ai(prompt, MODEL_NAME)
                    parsed_json = extract_json_from_response(resp_raw)
                    
                    if parsed_json:
                        out_row["remediation"] = parsed_json.get("fix_recommendation", "")
                        out_row["risk_level"] = parsed_json.get("risk_level", "")
                        
                    # Save individual JSON for debugging/auditing
                    out_file = OUT_DIR / f"row_{i}_{newest_cve}.json"
                    with open(out_file, "w", encoding="utf-8") as json_f:
                        json.dump({
                            "row_index": i,
                            "target_cve": newest_cve,
                            "latency_ms": latency_ms,
                            "ai_response": parsed_json if parsed_json else resp_raw
                        }, json_f, ensure_ascii=False, indent=2)
                        
                except Exception as e:
                    print(f"Row {i}: Error processing - {e}")
                    
                writer.writerow(out_row)
                out_f.flush()
                
                # Sleep to avoid rate limits
                time.sleep(1.0)
                
    print(f"Finished processing. Results saved to {out_csv_path}")

if __name__ == "__main__":
    main()
