"""Publish numeric features from the recovered historical development experiment.

No headlines, vocabulary, article URLs, broker identifiers or credentials are
exported. This permits offline model fitting, not raw-corpus reconstruction.
"""
import argparse
import hashlib
import json
from pathlib import Path


def export(evaluation, capture, output):
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import StandardScaler
    evaluation, capture, output = map(Path, (evaluation, capture, output))
    if output.exists():
        raise ValueError("Do not overwrite a published feature packet")
    read = lambda p: json.loads(p.read_text())
    split, protocol = read(evaluation / "split.json"), read(capture / "protocol.json")
    report, expected = read(evaluation / "report.json"), read(evaluation / "predictions.json")
    options = {**protocol["tfidf"], "ngram_range": tuple(protocol["tfidf"]["ngram_range"])}
    vectorizer = TfidfVectorizer(**options)
    text_train = vectorizer.fit_transform([r["text"] for r in split["train"]])
    text_test = vectorizer.transform([r["text"] for r in split["test"]])
    scaler = StandardScaler().fit([r["price_features"] for r in split["train"]])
    packet = {"schema_version": 1, "data_kind": "observed_retrospective_derived_features",
              "company": protocol["symbol"], "test_start": protocol["test_start"],
              "horizon_sessions": protocol["horizon_sessions"], "ridge_alpha": protocol["ridge_alpha"],
              "text_columns": text_train.shape[1], "price_columns": 2,
              "transforms_fit_on": "training only", "historical_availability_verified": False,
              "source": "FNSPID pinned prefix plus split-adjusted Alpaca daily opening prices",
              "source_revision": protocol["revision"], "source_capture_sha256": hashlib.sha256((capture / "manifest.json").read_bytes()).hexdigest(),
              "evaluation_sha256": hashlib.sha256((evaluation / "report.json").read_bytes()).hexdigest(),
              "sample_contract": "same paired rows and pre-2019 outcome maturity purge as run_historical.py",
              "preprocessing_reproduced_by_default_notebook": False,
              "limitations": protocol["limitations"], "partitions": {}, "expected_metrics": report["metrics"]}
    for part, sparse in [("train", text_train), ("test", text_test)]:
        sparse = sparse.tocoo()
        price = scaler.transform([r["price_features"] for r in split[part]])
        packet["partitions"][part] = {"text_coo": {"row": sparse.row.tolist(), "column": sparse.col.tolist(), "value": sparse.data.tolist()},
            "price_features": price.tolist(), "targets": [r["excess_return"] for r in split[part]],
            "samples": [{k: r[k] for k in ("sample_id", "entry_at", "exit_at")} for r in split[part]]}
    packet["expected_predictions"] = {name: [r["predictions"][name] for r in expected] for name in report["metrics"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, separators=(",", ":"), allow_nan=False) + "\n")
    return {"train": text_train.shape[0], "test": text_test.shape[0], "columns": text_train.shape[1], "bytes": output.stat().st_size}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evaluation", required=True)
    p.add_argument("--capture", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    print(json.dumps(export(args.evaluation, args.capture, args.output)))
