"""Professional desktop real-estate analyzer (local GUI).

Run:
    python src/main.py
"""

from __future__ import annotations

import io
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from typing import Iterable
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8,it;q=0.7",
    "Connection": "keep-alive",
}
TIMEOUT_S = 20
CURRENCY_RE = re.compile(r"(?:€|\$|£)\s?([\d.,]+)")
BEDROOM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:bed|bedroom|habita)", re.IGNORECASE)
BATH_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:bath|baño|bagno)", re.IGNORECASE)
AREA_RE = re.compile(r"([\d.,]+)\s*(?:sq\.?\s?ft|square\s?feet|m2|sqm|m²)", re.IGNORECASE)


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


@dataclass
class KpiData:
    price_per_sqft: float | None
    estimated_noi: float | None
    estimated_cap_rate: float | None
    gross_rent_multiplier: float | None


def to_float(value: str | None) -> float | None:
    if not value:
        return None
    value = value.replace(".", "").replace(",", ".") if value.count(",") == 1 and value.count(".") > 1 else value
    value = value.replace(",", "").strip()
    try:
        return float(value)
    except ValueError:
        return None


def fetch_html(url: str, session: requests.Session) -> str:
    response = session.get(url, timeout=TIMEOUT_S, headers={**HEADERS, "Referer": "https://www.google.com/"})
    if response.status_code == 403:
        raise RuntimeError(
            "403 Forbidden: this portal blocks automated requests. "
            "Use 'Load saved HTML' after saving the listing page from your browser."
        )
    response.raise_for_status()
    return response.text


def parse_listing(url: str, html: str) -> ListingData:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    title = (
        (soup.find("meta", property="og:title") or {}).get("content")
        or (soup.title.string.strip() if soup.title and soup.title.string else "Listing")
    )
    return ListingData(
        url=url,
        title=title,
        price=extract_price(soup, text),
        bedrooms=extract_first(BEDROOM_RE, text),
        bathrooms=extract_first(BATH_RE, text),
        area_sqft=extract_area_sqft(text),
        property_type=extract_property_type(text),
        city=extract_city(text),
    )


def extract_price(soup: BeautifulSoup, text: str) -> float | None:
    vals: list[float] = []
    for tag in soup.find_all(attrs={"content": True}):
        for m in CURRENCY_RE.findall(str(tag.get("content"))):
            f = to_float(m)
            if f:
                vals.append(f)
    for m in CURRENCY_RE.findall(text):
        f = to_float(m)
        if f:
            vals.append(f)
    vals = [v for v in vals if v > 20_000]
    return min(vals) if vals else None


def extract_first(pattern: re.Pattern[str], text: str) -> float | None:
    m = pattern.search(text)
    return to_float(m.group(1)) if m else None


def extract_area_sqft(text: str) -> float | None:
    m = AREA_RE.search(text)
    if not m:
        return None
    area = to_float(m.group(1))
    if not area:
        return None
    segment = text[max(0, m.start() - 6): m.end() + 6].lower()
    if "m2" in segment or "sqm" in segment or "m²" in segment:
        return area * 10.7639
    return area


def extract_property_type(text: str) -> str | None:
    types = ["house", "apartment", "condo", "villa", "townhouse", "duplex", "studio"]
    lt = text.lower()
    for t in types:
        if t in lt:
            return t.title()
    return None


def extract_city(text: str) -> str | None:
    m = re.search(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s*,\s*[A-Z]{2}\b", text)
    return m.group(1) if m else None


def discover_related_urls(base_url: str, html: str, max_urls: int) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        txt = a.get_text(" ", strip=True).lower()
        if href.startswith("http") and any(k in txt for k in ["similar", "nearby", "comparable", "related", "listing"]):
            if urlparse(href).netloc == urlparse(base_url).netloc and href not in found:
                found.append(href)
        if len(found) >= max_urls:
            break
    return found


def market_assumptions(price: float | None) -> dict[str, float]:
    p = price or 0.0
    monthly_rent = p * 0.006
    annual_rent = monthly_rent * 12
    vacancy = 0.06
    expense_ratio = 0.35
    noi = annual_rent * (1 - vacancy) * (1 - expense_ratio)
    return {
        "monthly_rent_proxy": monthly_rent,
        "annual_rent_proxy": annual_rent,
        "vacancy_rate": vacancy,
        "expense_ratio": expense_ratio,
        "estimated_noi": noi,
    }


def calculate_kpi(listing: ListingData) -> KpiData:
    a = market_assumptions(listing.price)
    ppsf = listing.price / listing.area_sqft if listing.price and listing.area_sqft else None
    noi = a["estimated_noi"] if listing.price else None
    cap = (noi / listing.price) if listing.price and noi else None
    grm = (listing.price / a["annual_rent_proxy"]) if listing.price and a["annual_rent_proxy"] else None
    return KpiData(ppsf, noi, cap, grm)


def build_excel(base: ListingData, base_kpi: KpiData, comps: list[ListingData]) -> bytes:
    comp_rows = []
    for c in comps:
        k = calculate_kpi(c)
        comp_rows.append(
            {
                "URL": c.url,
                "Title": c.title,
                "Price": c.price,
                "Bedrooms": c.bedrooms,
                "Bathrooms": c.bathrooms,
                "Area sqft": c.area_sqft,
                "Price/sqft": k.price_per_sqft,
                "Cap Rate": k.estimated_cap_rate,
            }
        )
    comps_df = pd.DataFrame(comp_rows)

    summary_df = pd.DataFrame([
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
            "GRM": base_kpi.gross_rent_multiplier,
        }
    ])

    assumptions_df = pd.DataFrame([market_assumptions(base.price)])

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        summary_df.to_excel(w, "Executive Summary", index=False)
        comps_df.to_excel(w, "Comparables", index=False)
        assumptions_df.to_excel(w, "Economic Assumptions", index=False)
    return out.getvalue()


class EstateApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Estate Intelligence Desktop")
        self.root.geometry("1080x700")
        self.root.configure(bg="#f2f5fb")

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TLabel", background="#f2f5fb", font=("Segoe UI", 11))
        self.style.configure("Title.TLabel", font=("Segoe UI Semibold", 24), foreground="#14213d")
        self.style.configure("Header.TLabel", font=("Segoe UI Semibold", 12), foreground="#24324a")
        self.style.configure("TButton", font=("Segoe UI Semibold", 10), padding=8)

        self.url_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.timer_var = tk.StringVar(value="Elapsed: 0.0s")
        self.max_comps_var = tk.IntVar(value=5)
        self.last_excel: bytes | None = None
        self._start_time = 0.0
        self._running = False

        self._build_ui()

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Estate Intelligence Desktop", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Professional property analysis for international client reporting.").pack(anchor="w", pady=(2, 16))

        form = ttk.Frame(frame)
        form.pack(fill="x")
        ttk.Label(form, text="Property URL", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.url_var, width=95).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 12))

        ttk.Label(form, text="Comparable listings").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(form, from_=0, to=15, textvariable=self.max_comps_var, width=8).grid(row=2, column=1, sticky="w")

        btns = ttk.Frame(form)
        btns.grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 12))
        ttk.Button(btns, text="Generate Excel", command=self.generate).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Load Saved HTML", command=self.generate_from_file).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Save Excel", command=self.save_excel).pack(side="left")

        status = ttk.Frame(frame)
        status.pack(fill="x", pady=(0, 12))
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        ttk.Label(status, textvariable=self.timer_var).pack(side="right")

        self.tree = ttk.Treeview(frame, columns=("price", "beds", "baths", "sqft", "cap"), show="headings", height=14)
        for col, label in [
            ("price", "Price"), ("beds", "Beds"), ("baths", "Baths"), ("sqft", "Area sqft"), ("cap", "Cap Rate")
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=120, anchor="center")
        self.tree.pack(fill="both", expand=True)

    def _tick_timer(self):
        if not self._running:
            return
        elapsed = time.perf_counter() - self._start_time
        self.timer_var.set(f"Elapsed: {elapsed:.1f}s")
        self.root.after(100, self._tick_timer)

    def generate(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please provide a property URL.")
            return
        self._run_worker(lambda: self._process_url(url))

    def generate_from_file(self):
        path = filedialog.askopenfilename(filetypes=[("HTML files", "*.html;*.htm")])
        if not path:
            return
        self._run_worker(lambda: self._process_html_file(path))

    def _run_worker(self, fn):
        self._running = True
        self._start_time = time.perf_counter()
        self.status_var.set("Processing...")
        self._tick_timer()

        def worker():
            try:
                result = fn()
                self.root.after(0, lambda: self._on_success(result))
            except Exception as e:
                self.root.after(0, lambda: self._on_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _process_url(self, url: str):
        with requests.Session() as session:
            html = fetch_html(url, session)
            base = parse_listing(url, html)
            related = discover_related_urls(url, html, self.max_comps_var.get())

            def parse_one(u: str):
                try:
                    return parse_listing(u, fetch_html(u, session))
                except Exception:
                    return None

            with ThreadPoolExecutor(max_workers=6) as ex:
                comps = [c for c in ex.map(parse_one, related) if c]

        kpi = calculate_kpi(base)
        excel = build_excel(base, kpi, comps)
        return base, kpi, comps, excel

    def _process_html_file(self, path: str):
        html = Path(path).read_text(encoding="utf-8", errors="ignore")
        base = parse_listing(f"file://{Path(path).name}", html)
        kpi = calculate_kpi(base)
        excel = build_excel(base, kpi, [])
        return base, kpi, [], excel

    def _on_success(self, result):
        self._running = False
        base, kpi, comps, excel = result
        self.last_excel = excel
        elapsed = time.perf_counter() - self._start_time
        self.status_var.set(f"Done in {elapsed:.2f}s | {base.title}")
        self.timer_var.set(f"Elapsed: {elapsed:.1f}s")

        for row in self.tree.get_children():
            self.tree.delete(row)
        for c in comps:
            ck = calculate_kpi(c)
            self.tree.insert(
                "", "end",
                values=(
                    f"{c.price:,.0f}" if c.price else "N/A",
                    c.bedrooms or "N/A",
                    c.bathrooms or "N/A",
                    f"{c.area_sqft:,.0f}" if c.area_sqft else "N/A",
                    f"{(ck.estimated_cap_rate or 0)*100:.2f}%" if ck.estimated_cap_rate else "N/A",
                ),
            )

        messagebox.showinfo(
            "Analysis complete",
            f"Property parsed successfully.\nPrice: {base.price or 'N/A'}\nCap rate: {(kpi.estimated_cap_rate or 0)*100:.2f}%",
        )

    def _on_error(self, err: str):
        self._running = False
        self.status_var.set("Error")
        messagebox.showerror("Processing error", err)

    def save_excel(self):
        if not self.last_excel:
            messagebox.showwarning("No file", "Generate analysis first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        Path(path).write_bytes(self.last_excel)
        messagebox.showinfo("Saved", f"Excel exported to:\n{path}")


def main():
    root = tk.Tk()
    app = EstateApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
