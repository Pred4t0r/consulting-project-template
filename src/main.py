from __future__ import annotations

import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
TIMEOUT_S = 18


@dataclass
class PropertyRecord:
    mls_number: str
    state: str
    listing_url: str | None = None
    address: str | None = None
    city: str | None = None
    zip_code: str | None = None
    price: float | None = None
    bedrooms: float | None = None
    bathrooms: float | None = None
    living_area_sqft: float | None = None
    lot_size_sqft: float | None = None
    property_type: str | None = None
    year_built: int | None = None
    broker_name: str | None = None
    source_name: str | None = None


@dataclass
class ExecutiveMetrics:
    price_per_sqft: float | None
    rent_proxy_monthly: float | None
    estimated_noi: float | None
    estimated_cap_rate: float | None
    recommendation: str


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = re.search(r"-?[\d,.]+", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def search_listing_candidates(mls_number: str, state: str) -> list[str]:
    query = quote_plus(f"{mls_number} {state} MLS listing")
    url = f"https://duckduckgo.com/html/?q={query}"
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if href and href.startswith("http") and href not in links:
            links.append(href)
        if len(links) >= 10:
            break
    return links


def _extract_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for node in soup.find_all("script", {"type": "application/ld+json"}):
        raw = (node.string or node.text or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                docs.extend([x for x in parsed if isinstance(x, dict)])
            elif isinstance(parsed, dict):
                docs.append(parsed)
        except json.JSONDecodeError:
            continue
    return docs


def extract_from_listing(url: str, mls_number: str, state: str) -> PropertyRecord | None:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S)
        response.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    full_text = soup.get_text(" ", strip=True)
    if mls_number.lower() not in full_text.lower() and mls_number not in url:
        return None

    record = PropertyRecord(mls_number=mls_number, state=state, listing_url=url)
    docs = _extract_json_ld(soup)

    for doc in docs:
        dtype = str(doc.get("@type", "")).lower()
        if "residence" in dtype or "house" in dtype or "singlefamilyresidence" in dtype:
            record.address = (
                doc.get("name")
                or (doc.get("address") or {}).get("streetAddress")
                or record.address
            )
            adr = doc.get("address") or {}
            record.city = adr.get("addressLocality") or record.city
            record.zip_code = adr.get("postalCode") or record.zip_code
            record.bedrooms = _to_float(doc.get("numberOfRooms") or doc.get("numberOfBedrooms") or record.bedrooms)
            record.bathrooms = _to_float(doc.get("numberOfBathroomsTotal") or doc.get("numberOfBathrooms") or record.bathrooms)
            record.living_area_sqft = _to_float((doc.get("floorSize") or {}).get("value") or record.living_area_sqft)
            record.property_type = doc.get("@type") or record.property_type
            record.year_built = int(_to_float(doc.get("yearBuilt")) or 0) or record.year_built

        offers = doc.get("offers")
        if isinstance(offers, dict):
            record.price = _to_float(offers.get("price") or record.price)

        if "realestateagent" in dtype:
            record.broker_name = doc.get("name") or record.broker_name

    if not record.price:
        m = re.search(r"\$\s?([\d,]+)", full_text)
        record.price = _to_float(m.group(1)) if m else None
    if not record.bedrooms:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:bed|beds|bedroom)", full_text, re.IGNORECASE)
        record.bedrooms = _to_float(m.group(1)) if m else None
    if not record.bathrooms:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:bath|baths|bathroom)", full_text, re.IGNORECASE)
        record.bathrooms = _to_float(m.group(1)) if m else None
    if not record.living_area_sqft:
        m = re.search(r"([\d,]+)\s*(?:sq\.?\s?ft|square feet)", full_text, re.IGNORECASE)
        record.living_area_sqft = _to_float(m.group(1)) if m else None

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    record.source_name = title[:80] if title else None
    return record


def calculate_metrics(record: PropertyRecord) -> ExecutiveMetrics:
    ppsf = (record.price / record.living_area_sqft) if record.price and record.living_area_sqft else None
    rent = (record.price * 0.0065 / 12) if record.price else None
    noi = (rent * 12 * 0.92 * 0.68) if rent else None
    cap = (noi / record.price) if noi and record.price else None

    score = 0
    if cap and cap >= 0.05:
        score += 1
    if ppsf and ppsf <= 350:
        score += 1
    if record.bedrooms and record.bedrooms >= 3:
        score += 1
    recommendation = "STRONG FIT" if score >= 2 else "REVIEW MANUALLY"
    return ExecutiveMetrics(ppsf, rent, noi, cap, recommendation)


def render_default_workbook(record: PropertyRecord, metrics: ExecutiveMetrics) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Executive File"
    ws["A1"] = "Professional Executive Property File"
    ws["A1"].font = Font(size=16, bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor="1E3A5F")

    rows = [
        ("Generated At", datetime.utcnow().isoformat(timespec="seconds") + "Z"),
        ("MLS Number", record.mls_number),
        ("State", record.state),
        ("Address", record.address),
        ("City", record.city),
        ("ZIP", record.zip_code),
        ("List Price", record.price),
        ("Beds", record.bedrooms),
        ("Baths", record.bathrooms),
        ("Living Area (sqft)", record.living_area_sqft),
        ("Lot Size (sqft)", record.lot_size_sqft),
        ("Property Type", record.property_type),
        ("Year Built", record.year_built),
        ("Broker", record.broker_name),
        ("Source", record.listing_url),
        ("Price / sqft", metrics.price_per_sqft),
        ("Estimated NOI", metrics.estimated_noi),
        ("Estimated Cap Rate", metrics.estimated_cap_rate),
        ("Recommendation", metrics.recommendation),
    ]
    for idx, (k, v) in enumerate(rows, start=3):
        ws[f"A{idx}"] = k
        ws[f"A{idx}"].font = Font(bold=True)
        ws[f"B{idx}"] = v
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 60

    stream = io.BytesIO()
    wb.save(stream)
    return stream.getvalue()


def apply_to_template(template_bytes: bytes, record: PropertyRecord, metrics: ExecutiveMetrics) -> bytes:
    wb = load_workbook(io.BytesIO(template_bytes))
    payload = {**asdict(record), **asdict(metrics), "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z"}

    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=1, max_row=40):
            for cell in row:
                if not isinstance(cell.value, str):
                    continue
                normalized = re.sub(r"[^a-z0-9]", "", cell.value.lower())
                for key, val in payload.items():
                    key_norm = re.sub(r"[^a-z0-9]", "", key.lower())
                    if key_norm and key_norm in normalized:
                        ws.cell(row=cell.row, column=cell.column + 1, value=val)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def build_ui() -> None:
    st.set_page_config(page_title="MLS Executive Studio", page_icon="🏢", layout="wide")
    st.markdown(
        """
        <style>
          .stApp { background: linear-gradient(180deg,#eaf0f7 0%,#f7f9fc 100%); }
          .hero { background:#113355; color:white; padding:20px; border-radius:14px; }
          .sub { color:#d6e3f5; margin-top:8px; }
        </style>
        <div class="hero">
          <h2 style="margin:0;">MLS Executive Studio</h2>
          <p class="sub">SmartMLS-inspired workflow: MLS + State in, decision-ready executive Excel out.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        mls_number = st.text_input("MLS Number", placeholder="e.g., 24003521")
    with c2:
        state = st.selectbox("State", ["CT", "NY", "NJ", "MA", "FL", "CA", "TX", "Other"])

    template_file = st.file_uploader("Upload Excel Template (optional)", type=["xlsx"])

    if st.button("Generate Executive File", type="primary"):
        if not mls_number.strip():
            st.error("MLS number is required.")
            return

        with st.spinner("Searching listing sources and extracting verified fields..."):
            candidates = search_listing_candidates(mls_number.strip(), state)
            parsed = [extract_from_listing(url, mls_number.strip(), state) for url in candidates]
            parsed = [p for p in parsed if p is not None]

        if not parsed:
            st.error("No listing source with matching MLS number was found. Try another state or MLS format.")
            return

        record = parsed[0]
        metrics = calculate_metrics(record)

        st.success(f"Found source: {record.listing_url}")
        st.dataframe(pd.DataFrame([asdict(record) | asdict(metrics)]), use_container_width=True)

        if template_file is not None:
            result = apply_to_template(template_file.read(), record, metrics)
            filename = f"executive_file_{mls_number}_{state}_template.xlsx"
        else:
            result = render_default_workbook(record, metrics)
            filename = f"executive_file_{mls_number}_{state}.xlsx"

        st.download_button(
            "Download Executive Excel",
            data=result,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    build_ui()
