# MLS Executive Studio

Modern standalone Streamlit application for realtors to generate a professional executive property file from:
- MLS number
- US state
- Optional Excel template provided by your team

## What it does

1. Searches public web sources for listing pages matching MLS + state.
2. Extracts relevant data points (price, beds, baths, sqft, address, broker, source URL).
3. Calculates investment-ready metrics (price/sqft, NOI proxy, cap-rate proxy, recommendation).
4. Produces an executive Excel file:
   - If template is uploaded: fills your template while preserving workbook format.
   - If no template: generates a clean default executive workbook.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run src/main.py
```

## Notes

- Accuracy depends on listing source availability and page structure.
- Output is decision support and should be reviewed by a licensed professional.
