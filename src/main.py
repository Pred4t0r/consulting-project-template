"""Apple-inspired real-estate intelligence GUI.

Run with:
    streamlit run src/main.py
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT_S = 15
CURRENCY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
BEDROOM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bed|bedroom)", re.IGNORECASE)
BATH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bath|bathroom)", re.IGNORECASE)
AREA_RE = re.compile(r"([\d,]+)\s*(?:sq\.?\s?ft|square\s?feet|m2|sqm)", re.IGNORECASE)


@dataclass
class ListingData:
    url: str
    title: str
    price: float | None
    bedrooms: float | None
    bathrooms: float | None
    area_sqft: float | None
    property_type: str | None
    city: str | None
    source_domain: str


@dataclass
class KpiData:
    price_per_sqft: float | None
    estimated_noi: float | None
    estimated_cap_rate: float | None
    gross_rent_multiplier: float | None
    annual_cashflow_proxy: float | None


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.replace(",", "").strip()
    try:
        return float(stripped)
    except ValueError:
        return None


def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
    response.raise_for_status()
    return response.text


def parse_listing(url: str, html: str) -> ListingData:
    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(" ", strip=True)

    title = (
        (soup.find("meta", property="og:title") or {}).get("content")
        or (soup.title.string.strip() if soup.title and soup.title.string else "Unknown Listing")
    )

    price = extract_price(soup, full_text)
    bedrooms = extract_first_number(BEDROOM_RE, full_text)
    bathrooms = extract_first_number(BATH_RE, full_text)
    area_sqft = extract_area_sqft(full_text)
    property_type = detect_property_type(full_text)
    city = detect_city(soup, full_text)

    return ListingData(
        url=url,
        title=title,
        price=price,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        area_sqft=area_sqft,
        property_type=property_type,
        city=city,
        source_domain=urlparse(url).netloc,
    )


def extract_price(soup: BeautifulSoup, text: str) -> float | None:
    candidates = []
    for attr in ("content", "value"):
        for tag in soup.find_all(attrs={attr: True}):
            raw = str(tag.get(attr))
            for match in CURRENCY_RE.findall(raw):
                candidates.append(to_float(match))

    for match in CURRENCY_RE.findall(text):
        candidates.append(to_float(match))

    numeric = [c for c in candidates if c and c > 10_000]
    return min(numeric) if numeric else None


def extract_first_number(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    return to_float(match.group(1)) if match else None


def extract_area_sqft(text: str) -> float | None:
    match = AREA_RE.search(text)
    if not match:
        return None

    raw = to_float(match.group(1))
    if raw is None:
        return None

    unit_segment = text[max(0, match.start() - 8) : match.end() + 8].lower()
    if "m2" in unit_segment or "sqm" in unit_segment:
        return raw * 10.7639
    return raw


def detect_property_type(text: str) -> str | None:
    types = ["house", "apartment", "condo", "townhouse", "duplex", "villa", "land"]
    lowered = text.lower()
    for t in types:
        if t in lowered:
            return t.capitalize()
    return None


def detect_city(soup: BeautifulSoup, text: str) -> str | None:
    locality = soup.find("meta", attrs={"property": "og:locality"})
    if locality and locality.get("content"):
        return locality["content"]

    address_patterns = [r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s*,\s*[A-Z]{2}\b"]
    for pattern in address_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def discover_related_urls(base_url: str, html: str, max_urls: int = 5) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor["href"])
        if not href.startswith("http"):
            continue

        anchor_text = anchor.get_text(" ", strip=True).lower()
        if any(k in anchor_text for k in ["similar", "nearby", "comparable", "related", "listing"]):
            urls.append(href)

    deduped: list[str] = []
    for item in urls:
        if item not in deduped and urlparse(item).netloc == urlparse(base_url).netloc:
            deduped.append(item)
        if len(deduped) >= max_urls:
            break
    return deduped


def safe_parse_url(url: str) -> ListingData | None:
    try:
        html = fetch_html(url)
        return parse_listing(url, html)
    except Exception:
        return None


def market_assumptions(listing: ListingData) -> dict[str, float]:
    monthly_rent_proxy = 0.006 * listing.price if listing.price else 0
    vacancy_rate = 0.06
    expense_ratio = 0.35
    annual_rent = monthly_rent_proxy * 12
    effective_gross_income = annual_rent * (1 - vacancy_rate)
    noi = effective_gross_income * (1 - expense_ratio)

    return {
        "monthly_rent_proxy": monthly_rent_proxy,
        "annual_rent_proxy": annual_rent,
        "vacancy_rate": vacancy_rate,
        "expense_ratio": expense_ratio,
        "effective_gross_income": effective_gross_income,
        "noi": noi,
    }


def calculate_kpis(listing: ListingData) -> KpiData:
    assumptions = market_assumptions(listing)
    price_per_sqft = (
        listing.price / listing.area_sqft if listing.price and listing.area_sqft and listing.area_sqft > 0 else None
    )

    noi = assumptions["noi"]
    cap_rate = noi / listing.price if listing.price else None
    grm = listing.price / assumptions["annual_rent_proxy"] if listing.price and assumptions["annual_rent_proxy"] > 0 else None

    annual_cashflow_proxy = noi - (listing.price * 0.015 if listing.price else 0)

    return KpiData(
        price_per_sqft=price_per_sqft,
        estimated_noi=noi if noi > 0 else None,
        estimated_cap_rate=cap_rate,
        gross_rent_multiplier=grm,
        annual_cashflow_proxy=annual_cashflow_proxy if annual_cashflow_proxy else None,
    )


def comparable_summary(base: ListingData, comparables: Iterable[ListingData]) -> pd.DataFrame:
    records = []
    for comp in comparables:
        kpi = calculate_kpis(comp)
        records.append(
            {
                "URL": comp.url,
                "Title": comp.title,
                "Price": comp.price,
                "Bedrooms": comp.bedrooms,
                "Bathrooms": comp.bathrooms,
                "Area sqft": comp.area_sqft,
                "Price/sqft": kpi.price_per_sqft,
                "Cap Rate": kpi.estimated_cap_rate,
            }
        )

    if not records:
        return pd.DataFrame(columns=["URL", "Title", "Price"])

    df = pd.DataFrame(records)
    df.insert(0, "Benchmark vs Subject Price", df["Price"] - (base.price or 0))
    return df


def executive_decision(base: ListingData, kpi: KpiData, comps_df: pd.DataFrame) -> str:
    score = 0
    notes = []

    if kpi.estimated_cap_rate and kpi.estimated_cap_rate >= 0.05:
        score += 1
        notes.append("Cap rate is above target (5%).")
    else:
        notes.append("Cap rate is below 5% threshold.")

    if kpi.price_per_sqft and not comps_df.empty and comps_df["Price/sqft"].notna().any():
        market_avg = comps_df["Price/sqft"].dropna().mean()
        if kpi.price_per_sqft <= market_avg:
            score += 1
            notes.append("Price/sqft is at or below comparable average.")
        else:
            notes.append("Price/sqft is above comparable average.")

    if base.bedrooms and base.bedrooms >= 3:
        score += 1
        notes.append("Bedroom count supports family-rental demand.")

    verdict = "INVEST" if score >= 2 else "REVIEW"
    return f"{verdict}: " + " ".join(notes)


def build_excel(base: ListingData, base_kpi: KpiData, comps_df: pd.DataFrame, decision: str) -> bytes:
    summary_df = pd.DataFrame(
        [
            {
                "Generated At": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "URL": base.url,
                "Title": base.title,
                "City": base.city,
                "Property Type": base.property_type,
                "Price": base.price,
                "Bedrooms": base.bedrooms,
                "Bathrooms": base.bathrooms,
                "Area sqft": base.area_sqft,
                "Price/sqft": base_kpi.price_per_sqft,
                "Estimated NOI": base_kpi.estimated_noi,
                "Estimated Cap Rate": base_kpi.estimated_cap_rate,
                "Gross Rent Multiplier": base_kpi.gross_rent_multiplier,
                "Annual Cashflow Proxy": base_kpi.annual_cashflow_proxy,
                "Executive Decision": decision,
            }
        ]
    )

    assumptions = market_assumptions(base)
    assumptions_df = pd.DataFrame([assumptions])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        summary_df.to_excel(writer, sheet_name="Executive Summary", index=False)
        comps_df.to_excel(writer, sheet_name="Comparables", index=False)
        assumptions_df.to_excel(writer, sheet_name="Economic Assumptions", index=False)

        workbook = writer.book
        money_fmt = workbook.add_format({"num_format": "$#,##0.00"})
        pct_fmt = workbook.add_format({"num_format": "0.00%"})

        ws_summary = writer.sheets["Executive Summary"]
        ws_summary.set_column("A:O", 24)
        ws_summary.set_column("F:F", 14, money_fmt)
        ws_summary.set_column("J:J", 14, money_fmt)
        ws_summary.set_column("K:K", 16, money_fmt)
        ws_summary.set_column("L:L", 16, pct_fmt)

        ws_comps = writer.sheets["Comparables"]
        ws_comps.set_column("A:H", 22)

    return output.getvalue()


def apply_apple_style() -> None:
    st.markdown(
        """
        <style>
          .stApp {
            background: linear-gradient(180deg, #f5f7fb 0%, #eef2f9 100%);
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
          }
          .block-container { max-width: 980px; }
          .hero-card {
            background: rgba(255,255,255,0.85);
            border: 1px solid rgba(255,255,255,0.65);
            border-radius: 18px;
            padding: 22px;
            box-shadow: 0 12px 35px rgba(40,58,92,0.10);
            backdrop-filter: blur(8px);
          }
          .metric-box {
            background: #ffffff;
            border-radius: 14px;
            padding: 12px 14px;
            box-shadow: 0 6px 18px rgba(28, 41, 61, 0.08);
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="Estate Intelligence Studio", page_icon="🏠", layout="wide")
    apply_apple_style()

    st.markdown(
        """
        <div class="hero-card">
            <h1 style="margin:0;">🏠 Estate Intelligence Studio</h1>
            <p style="margin-top:8px; color:#30405c;">
              Paste a property URL and generate an executive Excel with listing features, comparable data, KPI,
              and a decision-ready economic summary.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    url = st.text_input("Property URL", placeholder="https://www.realestate-site.com/listing/...")
    max_comps = st.slider("Comparable listings to include", min_value=0, max_value=10, value=5)

    if st.button("Generate Executive Excel", type="primary"):
        if not url:
            st.error("Please provide a property URL.")
            return

        with st.spinner("Collecting listing and market intelligence..."):
            try:
                base_html = fetch_html(url)
                base_listing = parse_listing(url, base_html)
            except Exception as exc:
                st.error(f"Unable to parse listing URL: {exc}")
                return

            candidate_urls = discover_related_urls(url, base_html, max_urls=max_comps)
            comparable_listings = [item for item in (safe_parse_url(u) for u in candidate_urls) if item is not None]

            base_kpi = calculate_kpis(base_listing)
            comps_df = comparable_summary(base_listing, comparable_listings)
            decision = executive_decision(base_listing, base_kpi, comps_df)
            workbook_bytes = build_excel(base_listing, base_kpi, comps_df, decision)

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown('<div class="metric-box">', unsafe_allow_html=True)
            st.metric("Price", f"${base_listing.price:,.0f}" if base_listing.price else "N/A")
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown('<div class="metric-box">', unsafe_allow_html=True)
            cap = f"{(base_kpi.estimated_cap_rate * 100):.2f}%" if base_kpi.estimated_cap_rate else "N/A"
            st.metric("Estimated Cap Rate", cap)
            st.markdown("</div>", unsafe_allow_html=True)
        with c3:
            st.markdown('<div class="metric-box">', unsafe_allow_html=True)
            ppsf = f"${base_kpi.price_per_sqft:,.2f}" if base_kpi.price_per_sqft else "N/A"
            st.metric("Price / Sqft", ppsf)
            st.markdown("</div>", unsafe_allow_html=True)

        st.success(decision)
        st.dataframe(comps_df, use_container_width=True)

        st.download_button(
            label="Download Executive Excel",
            data=workbook_bytes,
            file_name="executive_property_analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
