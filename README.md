# consulting-project-template

AI-powered real-estate decision support app with an Apple-style GUI.

## What it does

Given a real-estate listing URL, the app:
- Parses key listing features (price, beds, baths, area, title, city, type).
- Discovers related listing links on the same domain to create comparables.
- Computes KPI and economic proxies (price/sqft, NOI, cap rate, GRM, cashflow proxy).
- Produces an executive Excel file with:
  - `Executive Summary`
  - `Comparables`
  - `Economic Assumptions`

## Run locally (VS Code friendly)

### 1) Open the repo in VS Code
Open the folder that contains this `README.md` and `src/main.py`.

### 2) Create and activate a virtual environment

**Windows (PowerShell)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS/Linux**
```bash
python -m venv .venv
source .venv/bin/activate
```

### 3) Install dependencies

Recommended:
```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If your connection is slow (timeouts), retry with a larger timeout and no cache:
```bash
python -m pip install -r requirements.txt --default-timeout 120 --retries 10 --no-cache-dir
```

If your company/VPN/proxy blocks PyPI, use trusted hosts:
```bash
python -m pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

### 4) Run the app
```bash
streamlit run src/main.py
```

Then open the local URL shown by Streamlit and paste a property URL.

## Why your `ReadTimeoutError` happens

Your screenshot shows a network timeout while downloading from `files.pythonhosted.org`.
This is usually caused by:
- temporary slow internet,
- VPN/proxy/firewall restrictions,
- or pip timeout too short for your connection.

Using `python -m pip ... --default-timeout 120 --retries 10` typically resolves it.

## Notes

- The tool uses public page content and heuristic parsing; accuracy depends on each portal's HTML.
- Economic values are decision-support proxies, not formal appraisals.
