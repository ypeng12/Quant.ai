# backend/data/archive_local_trades.py
"""
Safely performs date-partitioned trade history archival:
1. Groups historical trades prior to keep_days by date (e.g. trades_2026-07-30.json).
2. Saves daily partition files into backend/data/datasets/daily_archives/.
3. Synchronizes daily files directly to HuggingFace Dataset repo (Ypeng12/quant-ai-trade-history).
4. Maintains backend/data/datasets/trade_history_archive.json for fast local API merging.
"""

import os
import json
import datetime
import pytz
from typing import Dict, List

def run_date_partitioned_archival(keep_days: int = 2, push_to_hf: bool = True) -> Dict:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    active_file = os.path.join(base_dir, "trade_history.json")
    datasets_dir = os.path.join(base_dir, "data", "datasets")
    daily_archives_dir = os.path.join(datasets_dir, "daily_archives")
    master_archive_file = os.path.join(datasets_dir, "trade_history_archive.json")
    
    os.makedirs(daily_archives_dir, exist_ok=True)
    
    if not os.path.exists(active_file):
        print(f"⚠️ Active file not found: {active_file}")
        return {"success": False, "reason": "active_file_not_found"}
        
    with open(active_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        active_trades = data.get("trade_history", [])
        
    est = pytz.timezone('America/New_York')
    now_est = datetime.datetime.now(est)
    valid_dates = {(now_est - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(keep_days)}
    
    all_dates = sorted(list({(t.get("date") or (t.get("time", "")[:10] if t.get("time") else "")).strip() for t in active_trades if t.get("date") or t.get("time")}))
    if all_dates:
        keep_dates = set(all_dates[-keep_days:])
        valid_dates.update(keep_dates)
        
    recent_trades = []
    older_trades = []
    
    for t in active_trades:
        d = (t.get("date") or (t.get("time", "")[:10] if t.get("time") else "")).strip()
        if d in valid_dates:
            recent_trades.append(t)
        else:
            older_trades.append(t)
            
    print(f"[*] Total active trades before partition: {len(active_trades)}")
    print(f"[*] Keeping {len(recent_trades)} recent trades in active trade_history.json for dates: {sorted(list(valid_dates))}")
    print(f"[*] Partitioning {len(older_trades)} older trades into daily date-based files...")
    
    # Group older trades by date
    date_grouped: Dict[str, List[dict]] = {}
    for ot in older_trades:
        d = (ot.get("date") or (ot.get("time", "")[:10] if ot.get("time") else "")).strip()
        if not d:
            d = "unknown_date"
        date_grouped.setdefault(d, []).append(ot)
        
    partition_files = []
    for d, t_list in date_grouped.items():
        daily_file = os.path.join(daily_archives_dir, f"trades_{d}.json")
        t_list.sort(key=lambda x: x.get("time", ""))
        
        # Merge if daily file already exists
        if os.path.exists(daily_file):
            try:
                with open(daily_file, "r", encoding="utf-8") as f:
                    existing_t = json.load(f).get("trade_history", [])
                    existing_ids = {t.get("order_id") or f"{t.get('ticker')}-{t.get('time')}" for t in existing_t}
                    for item in t_list:
                        uid = item.get("order_id") or f"{item.get('ticker')}-{item.get('time')}"
                        if uid not in existing_ids:
                            existing_t.append(item)
                    t_list = sorted(existing_t, key=lambda x: x.get("time", ""))
            except Exception as e:
                print(f"⚠️ Error reading daily file {daily_file}: {e}")
                
        with open(daily_file, "w", encoding="utf-8") as f:
            json.dump({"date": d, "count": len(t_list), "trade_history": t_list}, f, ensure_ascii=False, indent=2)
            
        partition_files.append((d, daily_file, len(t_list)))
        print(f"   └─ Saved daily partition: trades_{d}.json ({len(t_list)} trades)")
        
    # Update master archive file for fast local lookup
    master_archived_trades = []
    if os.path.exists(master_archive_file):
        try:
            with open(master_archive_file, "r", encoding="utf-8") as f:
                master_archived_trades = json.load(f).get("trade_history", [])
        except Exception:
            pass
            
    existing_uids = {t.get("order_id") or f"{t.get('ticker')}-{t.get('time')}" for t in master_archived_trades}
    for ot in older_trades:
        uid = ot.get("order_id") or f"{ot.get('ticker')}-{ot.get('time')}"
        if uid not in existing_uids:
            master_archived_trades.append(ot)
            existing_uids.add(uid)
            
    master_archived_trades.sort(key=lambda x: x.get("time", ""))
    with open(master_archive_file, "w", encoding="utf-8") as f:
        json.dump({"trade_history": master_archived_trades}, f, ensure_ascii=False, indent=2)
        
    # Update active trade_history.json
    recent_trades.sort(key=lambda x: x.get("time", ""))
    with open(active_file, "w", encoding="utf-8") as f:
        json.dump({"trade_history": recent_trades}, f, ensure_ascii=False, indent=2)
        
    # Optional sync to HuggingFace Dataset
    hf_pushed = 0
    if push_to_hf and older_trades:
        try:
            from huggingface_hub import HfApi
            token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_HUB_TOKEN")
            repo_id = "Ypeng12/quant-ai-trade-history"
            api = HfApi(token=token) if token else HfApi()
            api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
            
            for d, daily_file, _ in partition_files:
                api.upload_file(
                    path_or_fileobj=daily_file,
                    path_in_repo=f"daily_archives/trades_{d}.json",
                    repo_id=repo_id,
                    repo_type="dataset"
                )
                hf_pushed += 1
            print(f"🚀 Successfully pushed {hf_pushed} daily partition files to HF Dataset ({repo_id})!")
        except Exception as e_hf:
            print(f"⚠️ HuggingFace Dataset sync note: {e_hf}")

    return {
        "success": True,
        "active_remaining": len(recent_trades),
        "total_archived": len(master_archived_trades),
        "partitions_created": len(partition_files),
        "hf_pushed": hf_pushed
    }

if __name__ == "__main__":
    run_date_partitioned_archival(keep_days=2, push_to_hf=True)
