import os
import json
import re
import requests
import pandas as pd
import markdown
import html
from datetime import datetime
from dotenv import load_dotenv

def generate_report():
    # 1. Load environment variables
    load_dotenv()
    api_endpoint = os.getenv("AI_ENDPOINT")
    api_key = os.getenv("API_KEY")
    
    # Force the use of the Pro model for high-quality analytical reasoning
    model_name = os.getenv("JUDGE_MODEL", "CDG_gemini/gemini-3.1-pro-preview")

    if not api_endpoint or not api_key:
        print("Error: AI_ENDPOINT or API_KEY not found in .env")
        return

    # 2. Setup paths and load the data
    output_dir = os.path.join("outputs", "experiments")
    grouped_csv_path = os.path.join(output_dir, "grouped_summary.csv")
    reliability_csv_path = os.path.join(output_dir, "reliability_summary.csv")
    raw_csv_path = os.path.join(output_dir, "comparison_summary.csv")
    
    if not os.path.exists(grouped_csv_path) or not os.path.exists(reliability_csv_path):
        print(f"Error: Required summary CSVs not found in {output_dir}.")
        print("Please run summarize_experiments.py first.")
        return

    print("Loading data for AI analysis...")
    df_grouped = pd.read_csv(grouped_csv_path)
    df_reliability = pd.read_csv(reliability_csv_path)
    
    # Convert dataframes to Markdown tables for the AI prompt
    grouped_md = df_grouped.to_markdown(index=False)
    reliability_md = df_reliability.to_markdown(index=False)

    # 3. Construct the Prompt
    system_prompt = """You are a Principal Data Scientist evaluating Large Language Models for an automated cybersecurity ETL pipeline.
Your task is to analyze the provided experimental data and write an executive report that recommends the best model and prompt variant for production use.

The primary business task must be explicit in the report:
- Input context: CVE and software metadata from enterprise datasets, and in some cases screenshot/OCR-derived text.
- Required output per CVE: (1) remediation guidance and (2) installation risk assessment using L1-L9 with rationale.

Your report must include these exact headings (use ## for headings):
## Problem Statement
## Executive Summary
## Dataset Scope & Input Modality
## Methodology
## Quality & Cost Analysis
## Reliability Analysis
## Final Recommendation
## Limitations & Next Validation Steps

Writing requirements:
- Keep language professional, analytical, and decisive.
- Explain the recommendation using reliability-first reasoning before quality/cost trade-offs.
- Use short paragraphs and bullet points to improve top-to-bottom readability.
- Do not claim statistical significance unless statistical testing is shown in the provided data.
- Do not hallucinate data.
IMPORTANT: Do NOT output the raw data tables in your response. I will automatically append charts and tables to the end of your report."""

    user_message = f"""Here is the summarized experimental data:

### 1. Performance, Quality & Cost (Averages)
{grouped_md}

### 2. Reliability & Failure Rates
{reliability_md}

Based on this data, please write the final evaluation report with clear business-task framing and an easy top-to-bottom narrative flow."""

    # 4. Call the AI API
    print(f"Generating conclusion using {model_name}... (This may take 10-30 seconds)")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.2, 
        "max_tokens": 8192
    }

    try:
        response = requests.post(api_endpoint, headers=headers, json=payload)
        response.raise_for_status()
        
        result_json = response.json()
        
        if "choices" in result_json and len(result_json["choices"]) > 0:
            ai_content = result_json["choices"][0]["message"]["content"]
        else:
            ai_content = json.dumps(result_json, indent=2)
            print("Warning: Unexpected API response format.")

        # 5. Build the Hardcoded Appendix (Charts, Tables, and Prompts)
        print("Assembling appendices...")
        
        appendix_md = "\n\n## Appendix: Visualizations\n\n"
        
        charts = [
            ("Average Judge Score Overview", "chart_model_performance_bar_avg.png"),
            ("Judge Score Spread (Per Run)", "chart_model_performance_box_per_run.png"),
            ("Cost vs Quality (Averages)", "chart_cost_vs_quality_avg.png"),
            ("Cost vs Quality (All Runs)", "chart_cost_vs_quality_per_run.png")
        ]
        
        for title, filename in charts:
            if os.path.exists(os.path.join(output_dir, filename)):
                appendix_md += f"### {title}\n![{title}](./{filename})\n\n"
        
        # --- HARDCODED LLM JUDGE METRICS EXPLANATION (now as HTML to avoid markdown-in-HTML rendering issues) ---
        appendix_md += "<h2>Appendix: Evaluation Methodology</h2>\n"
        appendix_md += "<details><summary><strong>LLM as a Judge &amp; Metrics Guide</strong></summary>\n"
        appendix_md += "<div class=\"methodology\">\n"
        appendix_md += "<p>This evaluation utilizes an <strong>\"LLM as a Judge\"</strong> methodology. A highly capable model evaluates the outputs of the tested models to provide qualitative scoring at scale.</p>\n"
        appendix_md += "<h3>1. Judge Metrics (Scored 1-5)</h3>\n"
        appendix_md += "<ul>\n"
        appendix_md += "<li><strong>Actionability:</strong> Are the fix recommendations concrete, actionable, and specific to the CVE and software version?</li>\n"
        appendix_md += "<li><strong>Rationale Logic:</strong> Is the risk evaluation logical and well-reasoned based on the prompt's criteria?</li>\n"
        appendix_md += "<li><strong>Safety &amp; Accuracy:</strong> Does the response avoid hallucinations and maintain strict factual accuracy?</li>\n"
        appendix_md += "<li><strong>Formatting:</strong> Does the output strictly adhere to the requested JSON schema without markdown wrapping or conversational filler?</li>\n"
        appendix_md += "</ul>\n"
        appendix_md += "<h3>2. Automated System Metrics</h3>\n"
        appendix_md += "<ul>\n"
        appendix_md += "<li><strong>Schema Adherence (%):</strong> The percentage of required JSON keys successfully extracted.</li>\n"
        appendix_md += "<li><strong>JSON Parse Success:</strong> A boolean indicating if the model's output could be parsed as valid JSON.</li>\n"
        appendix_md += "<li><strong>Latency (ms) &amp; Tokens:</strong> Operational cost metrics tracking execution speed and token consumption.</li>\n"
        appendix_md += "</ul>\n"
        appendix_md += "</div></details>\n\n"

        # --- COLLAPSIBLE DATA TABLES ---
        appendix_md += "## Appendix: Data Tables\n\n"
        
        appendix_md += "<details><summary><strong>1. Reliability & Failure Rates</strong></summary>\n\n"
        appendix_md += df_reliability.to_html(index=False, escape=False) + "\n\n</details>\n\n"
        
        appendix_md += "<details><summary><strong>2. Grouped Performance Metrics</strong></summary>\n\n"
        appendix_md += df_grouped.to_html(index=False, escape=False) + "\n\n</details>\n\n"
        
        # Helper function for text sanitization in tables
        def sanitize_cell(x, max_len=120):
            s = '' if pd.isna(x) else str(x)
            s = s.replace('\r', ' ').replace('\n', ' ').replace('|', ' ')
            s = ' '.join(s.split())
            if len(s) > max_len:
                return s[:max_len] + '...'
            return s

        if os.path.exists(raw_csv_path):
            df_all = pd.read_csv(raw_csv_path)
            
            # Truncate Evaluated Pipeline Output Sample
            appendix_md += "<details><summary><strong>3. Evaluated Pipeline Output (First 10 Rows)</strong></summary>\n\n"
            df_raw_sample = df_all.head(10).copy()
            cols_to_keep = [c for c in df_raw_sample.columns if c not in ['prompt', 'response', 'response_text', 'parsed_json', 'judge_evaluation_comments']]
            df_display = df_raw_sample[cols_to_keep]

            for col in df_display.columns:
                df_display[col] = df_display[col].apply(lambda x: sanitize_cell(x, max_len=120))
            
            appendix_md += df_display.to_html(index=False, escape=False) + "\n\n</details>\n\n"

            # Append the Exact Prompts Used
            appendix_md += "<details><summary><strong>4. Prompt Variants Used</strong></summary>\n\n"
            if 'variant' in df_all.columns:
                variants = df_all['variant'].dropna().unique()
                for v in variants:
                    appendix_md += f"<h4>Variant: <code>{html.escape(str(v))}</code></h4>\n"
                    prompt_text = None
                    if 'prompt' in df_all.columns:
                        subset = df_all[df_all['variant'] == v]
                        if not subset.empty:
                            prompt_text = subset['prompt'].iloc[0]

                    if prompt_text is None and 'file' in df_all.columns:
                        sample_row = df_all[df_all['variant'] == v].iloc[0]
                        row_file = sample_row.get('file', '')
                        candidate_paths = [row_file, os.path.join(output_dir, os.path.basename(row_file))]
                        for p in candidate_paths:
                            try_path = os.path.normpath(p)
                            if os.path.exists(try_path):
                                try:
                                    with open(try_path, 'r', encoding='utf-8') as jf:
                                        j = json.load(jf)
                                        prompt_text = j.get('prompt') or j.get('input') or j.get('prompt_text')
                                        break
                                except Exception:
                                    continue

                    if prompt_text:
                        # escape HTML inside prompts and preserve whitespace in a <pre> block
                        prompt_text = str(prompt_text).replace('\r', '\n')
                        prompt_text = ' '.join(prompt_text.split())
                        appendix_md += "<pre><code>" + html.escape(prompt_text) + "</code></pre>\n\n"
                    else:
                        appendix_md += "<em>Prompt not available.</em>\n\n"
            appendix_md += "</details>\n\n"

        # --- 5. Add Input Raw Data Sample ---
        input_csv_path = "VendorDeploymentCVE_20250901.csv"
        if os.path.exists(input_csv_path):
            try:
                df_input = pd.read_csv(input_csv_path)
                appendix_md += "<details><summary><strong>5. Input Raw Data Sample (VendorDeploymentCVE_20250901)</strong></summary>\n\n"
                
                df_input_sample = df_input.head(10).copy()
                
                for col in df_input_sample.columns:
                    df_input_sample[col] = df_input_sample[col].apply(lambda x: sanitize_cell(x, max_len=120))
                
                appendix_md += df_input_sample.to_html(index=False, escape=False) + "\n\n</details>\n\n"
            except Exception as e:
                print(f"Warning: Could not process {input_csv_path}: {e}")

        # Combine AI content and Hardcoded Appendix
        full_report_md = ai_content + appendix_md

        # Ensure list markers become real markdown lists when the model omits a blank line.
        full_report_md = re.sub(r'([^\n])\n([\*\-]\s+)', r'\1\n\n\2', full_report_md)

        # 6. Generate Filenames with Date
        date_str = datetime.now().strftime("%Y%m%d")
        file_prefix = f"AI_Executive_Conclusion_{date_str}"
        
        md_path = os.path.join(output_dir, f"{file_prefix}.md")
        html_path = os.path.join(output_dir, f"{file_prefix}.html")

        # 7. Save the Markdown file
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(full_report_md)
        print(f"Success! Markdown saved to: {md_path}")

        # 8. Generate and save the Interactive HTML file
        print("Generating interactive HTML report...")
        
        # Render markdown to HTML; tables and fenced code will be present. We already used HTML for complex blocks.
        raw_html = markdown.markdown(full_report_md, extensions=['tables', 'fenced_code'])
        
        html_template = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AI Executive Conclusion</title>
            <style>
                html {{ scroll-behavior: smooth; }}
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 1100px; margin: 0 auto; padding: 2rem; background-color: #f9fafb; }}
                h1 {{ color: #111827; border-bottom: 2px solid #e5e7eb; padding-bottom: 0.5rem; }}
                .methodology p {{ margin: 0.5rem 0; color: #334155; }}
                .methodology h3 {{ margin-top: 0.75rem; color: #0f172a; }}
                .methodology ul {{ margin-left: 1.25rem; color: #334155; }}
                
                /* Main Accordion (H2) Styling */
                h2 {{ background-color: #ffffff; color: #1f2937; padding: 1rem; margin-top: 1.5rem; margin-bottom: 0; border: 1px solid #e5e7eb; border-radius: 8px; cursor: pointer; transition: background-color 0.2s; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 1px 2px rgba(0,0,0,0.05); user-select: none; }}
                h2:hover {{ background-color: #f3f4f6; }}
                h2::after {{ content: '▼'; font-size: 0.8em; color: #6b7280; transition: transform 0.3s; }}
                h2.active {{ border-bottom-left-radius: 0; border-bottom-right-radius: 0; border-bottom: none; }}
                h2.active::after {{ transform: rotate(-180deg); }}
                
                /* Accordion Content Wrapper */
                .section-content {{ display: none; padding: 1.5rem; background: #ffffff; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px; margin-bottom: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); overflow-x: auto; }}
                .section-content.active {{ display: block; }}
                
                /* Details/Summary (Sub-accordions for tables) */
                details {{ margin-bottom: 1rem; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 0.5rem 1rem; }}
                summary {{ cursor: pointer; font-weight: 600; color: #334155; padding: 0.5rem 0; outline: none; user-select: none; }}
                details[open] summary {{ border-bottom: 1px solid #e2e8f0; margin-bottom: 1rem; padding-bottom: 0.75rem; }}
                
                /* Table Fixes */
                table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; margin-bottom: 1rem; font-size: 0.9rem; table-layout: auto; }}
                th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #e5e7eb; word-wrap: break-word; overflow-wrap: break-word; max-width: 300px; white-space: normal; }}
                th {{ background-color: #f1f5f9; font-weight: 600; color: #475569; }}
                tr:hover {{ background-color: #e2e8f0; }}
                
                /* Code Blocks */
                pre {{ background-color: #0f172a; color: #e6eef8; padding: 1rem; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; font-size: 0.9rem; }}
                code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; color: #0f172a; background-color: #e2e8f0; padding: 0.12rem 0.35rem; border-radius: 4px; }}
                pre code {{ color: inherit; background-color: transparent; padding: 0; border-radius: 0; }}
                
                /* Images */
                img {{ max-width: 100%; height: auto; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-top: 1rem; margin-bottom: 2rem; border: 1px solid #e5e7eb; }}
                
                ul, ol {{ margin-left: 1.5rem; }}
                .view-controls {{ display: flex; justify-content: flex-end; margin-bottom: 0.75rem; }}
                .view-controls button {{ border: 1px solid #cbd5e1; background: #ffffff; color: #334155; border-radius: 6px; padding: 0.4rem 0.7rem; font-size: 0.85rem; cursor: pointer; }}
                .view-controls button:hover {{ background: #f8fafc; }}
            </style>
        </head>
        <body>
            <h1>LLM Evaluation Report for CVE Extraction Pipeline</h1>
            <p style="color: #6b7280; margin-top: -10px; margin-bottom: 30px;">Generated on {date_str}</p>
            <div class="view-controls">
                <button id="toggle-sections" type="button">Collapse all sections</button>
            </div>
            
            <div id="content">
                {raw_html}
            </div>

            <script>
                document.addEventListener("DOMContentLoaded", function() {{
                    const contentDiv = document.getElementById('content');
                    const elements = Array.from(contentDiv.children);
                    
                    contentDiv.innerHTML = ''; 
                    let currentWrapper = null;

                    elements.forEach(el => {{
                        if (el.tagName === 'H2') {{
                            contentDiv.appendChild(el);
                            
                            currentWrapper = document.createElement('div');
                            currentWrapper.className = 'section-content';
                            contentDiv.appendChild(currentWrapper);

                            el.addEventListener('click', function() {{
                                this.classList.toggle('active');
                                const content = this.nextElementSibling;
                                content.classList.toggle('active');
                            }});
                        }} else if (currentWrapper) {{
                            currentWrapper.appendChild(el);
                        }} else {{
                            contentDiv.appendChild(el);
                        }}
                    }});
                    
                    const allHeadings = Array.from(document.querySelectorAll('h2'));
                    const toggleButton = document.getElementById('toggle-sections');
                    let allExpanded = true;

                    const setAllSections = (open) => {{
                        allHeadings.forEach((heading) => {{
                            heading.classList.toggle('active', open);
                            const content = heading.nextElementSibling;
                            if (content) {{
                                content.classList.toggle('active', open);
                            }}
                        }});
                        allExpanded = open;
                        if (toggleButton) {{
                            toggleButton.textContent = open ? 'Collapse all sections' : 'Expand all sections';
                        }}
                    }};

                    // Open all sections by default for linear top-to-bottom reading.
                    setAllSections(true);

                    if (toggleButton) {{
                        toggleButton.addEventListener('click', () => {{
                            setAllSections(!allExpanded);
                        }});
                    }}
                }});
            </script>
        </body>
        </html>
        """

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_template)
            
        print(f"Success! Interactive HTML saved to: {html_path}")

    except Exception as e:
        print(f"API call failed: {e}")
        if 'response' in locals():
            print(response.text)

if __name__ == "__main__":
    generate_report()