#!/usr/bin/env python3
"""Read-only, small-sample SEC availability audit for the 610 project.

Uses the Python standard library. No credentials or trading endpoints are used.
Each resource is requested once, sequentially, with at least 0.5 seconds between
requests; 403 responses are preserved and are not retried or bypassed.
SEC_USER_AGENT may provide a real operator identity/contact; none is invented.
"""

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path


OFFICIAL_DOCS = [
    "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
    "https://www.sec.gov/about/developer-resources",
]
# Known identifiers are independently verified against the returned submissions
# ticker list; they do not substitute for verification if the request fails.
KNOWN_CIKS = {"NVDA": 1045810, "TSLA": 1318605, "PLTR": 1321655, "SNDK": 2023554}


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "div", "br", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def text(self):
        return "\n".join(" ".join(line.split()) for line in "".join(self.parts).splitlines() if line.strip())


class Fetcher:
    def __init__(self, root):
        self.root = root
        self.records = []
        self.last_request = 0.0
        self.user_agent = os.environ.get(
            "SEC_USER_AGENT", "QuantAI610Research/0.1 (small-sample availability audit)"
        )

    def get(self, url, filename):
        wait = 0.5 - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        fetched_at = now()
        started = time.monotonic()
        request = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.5",
        })
        status, body, headers, error = None, b"", {}, None
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                headers = dict(response.headers)
                body = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            headers = dict(exc.headers)
            body = exc.read()
            error = str(exc)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = str(exc)
        self.last_request = time.monotonic()
        path = self.root / "raw" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        record = {
            "url": url, "status": status, "retrieved_at_utc": fetched_at,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": headers.get("Content-Type"),
            "response_date": headers.get("Date"),
            "raw_file": str(path), "error": error,
        }
        self.records.append(record)
        parsed = None
        if status == 200:
            try:
                parsed = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        return record, parsed, body


def normalize(recent, cik, ticker, fetched_at):
    count = len(recent.get("accessionNumber", []))
    rows = []
    for i in range(count):
        row = {key: values[i] if i < len(values) else None for key, values in recent.items()}
        accession = row.get("accessionNumber", "")
        primary = row.get("primaryDocument", "")
        directory = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
        row.update({
            "ticker": ticker, "cik": str(cik).zfill(10),
            "document_url": f"{directory}/{primary}" if primary else None,
            "filing_index_url": f"{directory}/{accession}-index.html",
            "audit_retrieved_at_utc": fetched_at,
            "historical_first_seen_at": None,
        })
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default="2026-10-07")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--output", type=Path,
                        default=Path("reports/market_impact_data_audit_20261007/sec"))
    args = parser.parse_args()
    end = date.fromisoformat(args.as_of)
    start = end - timedelta(days=args.days - 1)
    root = args.output.resolve()
    if root.exists() and any(root.iterdir()):
        parser.error('Audit directory is not empty; use a new --output directory.')
    fetcher = Fetcher(root)
    ticker_record, ticker_data, _ = fetcher.get(
        "https://www.sec.gov/files/company_tickers.json", "company_tickers.response")
    ticker_map = {}
    if isinstance(ticker_data, dict):
        ticker_map = {item["ticker"]: item["cik_str"] for item in ticker_data.values()
                      if isinstance(item, dict) and "ticker" in item and "cik_str" in item}

    companies = []
    for ticker, known_cik in KNOWN_CIKS.items():
        cik = ticker_map.get(ticker, known_cik)
        record, data, _ = fetcher.get(
            f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json",
            f"{ticker}_submissions.response")
        company = {"ticker": ticker, "cik": str(cik).zfill(10),
                   "identifier_source": "official_ticker_map" if ticker in ticker_map else "known_cik_pending_response_verification",
                   "metadata_request": record, "metadata_success": False}
        if not isinstance(data, dict) or "filings" not in data:
            companies.append(company)
            continue
        company["metadata_success"] = True
        company["company_name"] = data.get("name")
        company["response_tickers"] = data.get("tickers")
        company["ticker_verified"] = ticker in (data.get("tickers") or [])
        if ticker not in ticker_map and company["ticker_verified"]:
            company["identifier_source"] = "known_cik_verified_against_official_submissions_tickers"
        rows = normalize(data["filings"].get("recent", {}), cik, ticker,
                         record["retrieved_at_utc"])
        in_window = [row for row in rows if row.get("filingDate") and
                     start.isoformat() <= row["filingDate"] <= end.isoformat()]
        key_rows = [row for row in in_window if row.get("form") in ("8-K", "10-Q", "10-K")]
        dates = [row["filingDate"] for row in rows if row.get("filingDate")]
        normalized_path = root / "normalized" / f"{ticker}_recent_filings.json"
        write_json(normalized_path, rows)
        write_json(root / "normalized" / f"{ticker}_window_filings.json", in_window)
        company.update({
            "recent_array_count": len(rows),
            "recent_array_date_range": [min(dates), max(dates)] if dates else None,
            "older_archive_files_available": data["filings"].get("files", []),
            "window_count": len(in_window),
            "window_observed_filing_date_range": [min(row["filingDate"] for row in in_window), max(row["filingDate"] for row in in_window)] if in_window else None,
            "window_unique_accession_count": len({row.get("accessionNumber") for row in in_window}),
            "window_form_counts": dict(sorted(Counter(row.get("form") for row in in_window).items())),
            "window_key_filing_count": len(key_rows),
            "window_field_nonempty_counts": {
                field: sum(bool(row.get(field)) for row in in_window)
                for field in ("filingDate", "acceptanceDateTime", "reportDate", "primaryDocument", "document_url")},
            "key_filing_field_nonempty_counts": {
                field: sum(bool(row.get(field)) for row in key_rows)
                for field in ("filingDate", "acceptanceDateTime", "reportDate", "primaryDocument", "document_url")},
            "normalized_file": str(normalized_path),
            "latest_key_filing": max(key_rows, key=lambda row: row.get("acceptanceDateTime") or row["filingDate"]) if key_rows else None,
        })
        if key_rows:
            filing = company["latest_key_filing"]
            doc_record, _, body = fetcher.get(filing["document_url"], f"{ticker}_latest_key_filing.response")
            company["document_request"] = doc_record
            company["document_http_success"] = doc_record["status"] == 200
            if doc_record["status"] == 200:
                extractor = VisibleText()
                extractor.feed(body.decode("utf-8", errors="replace"))
                text = extractor.text()
                text_path = root / "normalized" / f"{ticker}_latest_key_filing.txt"
                text_path.write_text(text)
                company["document_visible_text_chars"] = len(text)
                company["document_approximate_words"] = len(text.split())
                company["document_text_path"] = str(text_path)
                company["document_text_preview"] = text[:1200]
        companies.append(company)

    summary = {
        "audit_finished_at_utc": now(), "as_of_date": end.isoformat(),
        "window_start_inclusive": start.isoformat(), "window_end_inclusive": end.isoformat(),
        "window_days": args.days, "symbols": list(KNOWN_CIKS),
        "ticker_map_request": ticker_record, "companies": companies,
        "totals": {
            "metadata_success": sum(c["metadata_success"] for c in companies),
            "verified_ticker_count": sum(c.get("ticker_verified", False) for c in companies),
            "window_filings": sum(c.get("window_count", 0) for c in companies),
            "window_key_filings": sum(c.get("window_key_filing_count", 0) for c in companies),
            "window_key_form_counts": {form: sum(c.get("window_form_counts", {}).get(form, 0) for c in companies) for form in ("8-K", "10-Q", "10-K")},
            "document_attempts": sum("document_request" in c for c in companies),
            "document_http_success": sum(c.get("document_http_success", False) for c in companies),
        },
        "request_policy": {"sequential": True, "minimum_pause_seconds": 0.5,
                           "retry_count": 0, "auth_required": False,
                           "user_agent_source": "SEC_USER_AGENT" if os.environ.get("SEC_USER_AGENT") else "truthful_research_identifier_without_invented_contact"},
        "limitations": [
            "The as-of day is still in progress at collection time; the audit is a snapshot, not a finalized end-of-day census.",
            "Counts are exact forms 8-K/10-Q/10-K, excluding amendments; all-form counts include ownership and administrative filings, not distinct price-relevant events.",
            "This fetch captures the current submissions JSON. audit_retrieved_at_utc is the audit observation time, not the historical first time Quant.ai could see a filing.",
            "acceptanceDateTime and filingDate describe SEC submission metadata; reportDate is the reporting/event period, not availability time.",
            "API metadata success does not prove archive document access or successful text/event extraction.",
            "Only one latest key primary document is attempted per company; earnings releases can reside in separate exhibits that this small trial does not fetch.",
            "HTML-to-text is an initial extraction only; inline XBRL, tables, duplicated facts, boilerplate and amendments need further parsing and human checks.",
            "SEC submissions do not supply contemporaneous analyst consensus estimates; this audit cannot establish earnings surprise.",
            "No market-return join, NLP classifier validation, alpha claim or trading action is performed.",
        ],
        "official_documentation": OFFICIAL_DOCS,
    }
    write_json(root / "requests.json", fetcher.records)
    write_json(root / "summary.json", summary)
    print(json.dumps({"output": str(root), "totals": summary["totals"],
                      "companies": [{k: c.get(k) for k in ("ticker", "metadata_success", "ticker_verified", "window_count", "window_form_counts", "document_http_success", "document_visible_text_chars")} for c in companies]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
