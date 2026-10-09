"""Export aggregate audit counts for the public Quant.ai research panel.

The input archive stays local. This exporter copies no raw text, account state,
article identifiers, absolute paths, or credentials into the public output.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def export_summary(audit: Path) -> dict:
    def read(name: str) -> dict:
        return json.loads((audit / name).read_text(encoding="utf-8"))

    validation = read("validation.json")
    alpaca = read("alpaca/summary.json")
    futu = read("futu/summary.json")
    sec = read("sec/summary.json")["totals"]
    if validation["status"] != "passed":
        raise ValueError("The archived consistency audit has not passed.")
    news = alpaca["news"]
    sessions = len(alpaca["sessions"])
    symbols = len(alpaca["bars"])
    rth_bars = sum(row["rth_bars"] for row in alpaca["bars"].values())
    if rth_bars != validation["rth_bars"]:
        raise ValueError("Price coverage disagrees with the validated archive.")
    labels = validation["valid_exploratory_label_rows"]
    if labels != alpaca["label_status_counts"]["exploratory_label_available"]:
        raise ValueError("Exploratory label counts disagree across summaries.")
    documents = sec["document_http_success"]
    attempts = sec["document_attempts"]
    document_detail = (
        f"All {attempts} attempted primary-document downloads failed; text is not available."
        if documents == 0
        else f"{documents} of {attempts} primary-document requests succeeded; HTTP success does not establish text extraction."
    )
    return {
        "project": "Train_Financial_Sentinment_Analysis_Using_Prices",
        "audit_date": datetime.fromisoformat(alpaca["audit_completed_at"]).date().isoformat(),
        "model_status": "Not trained",
        "evaluation_status": "Not evaluated",
        "current_stage": "Data audit",
        "exploratory_labels": labels,
        "labels_are_predictions": False,
        "sources": [
            {
                "id": "news", "name": "Company news", "records": news["raw_count"],
                "status": "Historical audit",
                "detail": f"Benzinga via Alpaca: {news['with_body']} articles have body text. Event deduplication and historical arrival times remain unresolved.",
            },
            {
                "id": "futu", "name": "Futu community", "records": futu["total_rows"],
                "status": "Historical audit",
                "detail": f"{futu['global_unique_post_ids']} distinct post IDs and {futu['global_unique_texts']} distinct texts. Author and interaction fields were absent; first-snapshot receipt times were not recorded.",
            },
            {
                "id": "prices", "name": "Stock and benchmark prices", "records": rth_bars,
                "status": "Historical audit",
                "detail": f"Five-minute regular-session bars across {symbols} symbols and {sessions} trading sessions. Exploratory labels use 60-minute stock returns relative to SPY before costs.",
            },
            {
                "id": "sec", "name": "SEC filings", "records": sec["window_filings"],
                "status": "Metadata only",
                "detail": f"90-day metadata snapshot: {sec['window_key_filings']} filings are 8-K, 10-Q, or 10-K. {document_detail}",
            },
            {
                "id": "x", "name": "X", "records": None,
                "status": "Not connected",
                "detail": "No authorized structured data sample has been collected.",
            },
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", type=Path, default=ROOT / "reports/market_impact_data_audit_20261007")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/financial_sentiment_public_summary.json")
    args = parser.parse_args()
    summary = export_summary(args.audit_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Exported {len(summary['sources'])} source summaries and {summary['exploratory_labels']} exploratory labels.")


if __name__ == "__main__":
    main()
