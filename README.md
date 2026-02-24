# consulting-project-template

Professional desktop real-estate analysis tool for international client reporting.

## What changed

This project now uses a **local desktop GUI** (Tkinter) instead of a web app.

Capabilities:
- Parse a property URL for key features (price, beds, baths, area, type, city).
- Discover and parse comparable links from the same listing page.
- Generate KPI/economic metrics (price/sqft, NOI proxy, cap rate, GRM).
- Export a professional Excel report (`Executive Summary`, `Comparables`, `Economic Assumptions`).
- Show a **live elapsed timer** while analysis and Excel generation are running.
- Provide fallback mode: load a saved `.html` file when a portal blocks scraping with `403 Forbidden`.

## Why you saw 403 on Idealista

Some real-estate websites block automated requests, even with browser-like headers.
When this happens, use **Load Saved HTML**:
1. Open listing in your browser.
2. Save the page as `.html`.
3. In the app, click **Load Saved HTML** and generate report from local file.

## Run locally (VS Code)

### 1) Create and activate a virtual environment

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

### 2) Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt --default-timeout 120 --retries 10 --no-cache-dir
```

### 3) Start the desktop app

```bash
python src/main.py
```

## Fast workflow for clients

1. Paste URL and choose comparables.
2. Click **Generate Excel**.
3. Watch timer and status bar while processing.
4. Click **Save Excel** when completed.

## Notes

- For blocked portals (403), use local HTML fallback mode.
- Metrics are decision-support estimates, not formal appraisals.
