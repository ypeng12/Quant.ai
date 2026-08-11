# backend/data/sync_full_history_to_hf.py
"""
Uploads 100% full, unpruned trade_history.json (25,810+ entries) and daily date partitions
to HuggingFace Dataset repository (Ypeng12/quant-ai-trade-history).
"""

import os
import json
from typing import Dict, List

def sync_full_history_to_hf():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_file = os.path.join(base_dir, "trade_history.json")
    daily_dir = os.path.join(base_dir, "data", "datasets", "daily_archives")
    os.makedirs(daily_dir, exist_ok=True)

    if not os.path.exists(full_file):
        print(f"❌ File not found: {full_file}")
        return

    with open(full_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        all_trades = data.get("trade_history", [])

    print(f"[*] Loaded full trade history: {len(all_trades)} total entries.")

    # Partition by date
    date_grouped: Dict[str, List[dict]] = {}
    for t in all_trades:
        d = (t.get("date") or (t.get("time", "")[:10] if t.get("time") else "")).strip()
        if not d:
            d = "unknown"
        date_grouped.setdefault(d, []).append(t)

    daily_files = []
    for d, t_list in sorted(date_grouped.items()):
        daily_file = os.path.join(daily_dir, f"trades_{d}.json")
        t_list.sort(key=lambda x: x.get("time", ""))
        with open(daily_file, "w", encoding="utf-8") as f:
            json.dump({"date": d, "count": len(t_list), "trade_history": t_list}, f, ensure_ascii=False, indent=2)
        daily_files.append((d, daily_file, len(t_list)))
        print(f"   ├─ Generated daily partition: trades_{d}.json ({len(t_list)} trades)")

    # Upload to HuggingFace Dataset
    try:
        from huggingface_hub import HfApi
        token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_HUB_TOKEN")
        repo_id = "Ypeng12/quant-ai-trade-history"
        api = HfApi(token=token) if token else HfApi()
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)

        # Upload full master files and train split files for HF Dataset Viewer (default/train)
        print(f"[*] Uploading master trade history and train split files to HF Dataset ({repo_id})...")
        train_json_path = os.path.join(base_dir, "data", "datasets", "train.json")
        train_csv_path = os.path.join(base_dir, "data", "datasets", "train.csv")
        train_jsonl_path = os.path.join(base_dir, "data", "datasets", "train.jsonl")
        
        # Write train.json as flat list of trades or dict for HF viewer
        with open(train_json_path, "w", encoding="utf-8") as f:
            json.dump(all_trades, f, ensure_ascii=False, indent=2)

        with open(train_jsonl_path, "w", encoding="utf-8") as f:
            for item in all_trades:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        try:
            import pandas as pd
            df_trades = pd.DataFrame(all_trades)
            df_trades.to_csv(train_csv_path, index=False, encoding="utf-8")
            api.upload_file(path_or_fileobj=train_csv_path, path_in_repo="train.csv", repo_id=repo_id, repo_type="dataset")
            api.upload_file(path_or_fileobj=train_csv_path, path_in_repo="data/train.csv", repo_id=repo_id, repo_type="dataset")

            # Export Parquet format for instant HuggingFace Viewer rendering
            parquet_path = os.path.join(base_dir, "data", "datasets", "train-00000-of-00001.parquet")
            df_trades.to_parquet(parquet_path, index=False)
            api.upload_file(path_or_fileobj=parquet_path, path_in_repo="data/train-00000-of-00001.parquet", repo_id=repo_id, repo_type="dataset")
            print(f"   ├─ Uploaded Parquet split for instant HF Viewer rendering: data/train-00000-of-00001.parquet")
        except Exception as csv_err:
            print(f"   ⚠️ Could not generate train.csv/parquet: {csv_err}")

        api.upload_file(path_or_fileobj=train_json_path, path_in_repo="train.json", repo_id=repo_id, repo_type="dataset")
        api.upload_file(path_or_fileobj=train_jsonl_path, path_in_repo="train.jsonl", repo_id=repo_id, repo_type="dataset")
        api.upload_file(path_or_fileobj=full_file, path_in_repo="trade_history.json", repo_id=repo_id, repo_type="dataset")
        api.upload_file(path_or_fileobj=full_file, path_in_repo="historical_trades_archive.json", repo_id=repo_id, repo_type="dataset")

        # Upload daily partition files
        pushed_count = 0
        for d, df_path, _ in daily_files:
            api.upload_file(
                path_or_fileobj=df_path,
                path_in_repo=f"daily_archives/trades_{d}.json",
                repo_id=repo_id,
                repo_type="dataset"
            )
            pushed_count += 1
            print(f"   ├─ Uploaded daily archive to HF: daily_archives/trades_{d}.json")

        # Also sync to HuggingFace Space (Ypeng12/quant-ai)
        space_id = "Ypeng12/quant-ai"
        print(f"[*] Uploading trade history and archives to HF Space ({space_id})...")
        try:
            api.upload_file(path_or_fileobj=full_file, path_in_repo="backend/trade_history.json", repo_id=space_id, repo_type="space")
            for d, df_path, _ in daily_files:
                api.upload_file(path_or_fileobj=df_path, path_in_repo=f"backend/data/datasets/daily_archives/trades_{d}.json", repo_id=space_id, repo_type="space")
            print(f"✅ Successfully synced trade history to HF Space ({space_id})!")
        except Exception as space_err:
            print(f"   ⚠️ Could not sync to HF Space ({space_id}): {space_err}")

        print(f"✅ Successfully synced full dataset to HF Dataset ({repo_id}) & HF Space ({space_id})!")
    except Exception as e:
        print(f"⚠️ Error uploading to HuggingFace Dataset: {e}")

if __name__ == "__main__":
    sync_full_history_to_hf()
