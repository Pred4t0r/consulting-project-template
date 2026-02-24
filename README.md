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

## Run locally

```bash
pip install streamlit pandas requests beautifulsoup4 xlsxwriter
streamlit run src/main.py
```

Then open the local URL shown by Streamlit and paste a property URL.

## Notes

- The tool uses public page content and heuristic parsing; accuracy depends on each portal's HTML.
- Economic values are decision-support proxies, not formal appraisals.
