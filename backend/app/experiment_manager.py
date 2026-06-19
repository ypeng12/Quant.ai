# backend/app/experiment_manager.py
"""
Experiment Manager — Saves and manages backtest experiments in an SQLite database.
"""

import os
import sqlite3
import json
from datetime import datetime

# Database path relative to this file
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experiments.db")

def get_connection():
    """
    Get a connection to the SQLite database.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Initialize the experiments table.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            ticker TEXT NOT NULL,
            interval TEXT NOT NULL,
            strategy_mode TEXT NOT NULL,
            config_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            equity_curve_json TEXT NOT NULL,
            drawdown_curve_json TEXT NOT NULL,
            regime_breakdown_json TEXT NOT NULL,
            ai_report TEXT
        )
    """)
    conn.commit()
    conn.close()

# Auto-initialize DB on import
init_db()

def save_experiment(name, ticker, interval, strategy_mode, config, metrics, equity_curve, drawdown_curve, regime_breakdown, ai_report=None):
    """
    Save a new backtest experiment to the database.
    """
    conn = get_connection()
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO experiments (
            name, timestamp, ticker, interval, strategy_mode, 
            config_json, metrics_json, equity_curve_json, 
            drawdown_curve_json, regime_breakdown_json, ai_report
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        timestamp,
        ticker.upper(),
        interval,
        strategy_mode,
        json.dumps(config),
        json.dumps(metrics),
        json.dumps(equity_curve),
        json.dumps(drawdown_curve),
        json.dumps(regime_breakdown),
        ai_report
    ))
    
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id

def list_experiments():
    """
    List all saved experiments (returns summary information for list view).
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, timestamp, ticker, interval, strategy_mode, metrics_json, config_json
        FROM experiments
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "name": r["name"],
            "timestamp": r["timestamp"],
            "ticker": r["ticker"],
            "interval": r["interval"],
            "strategy_mode": r["strategy_mode"],
            "metrics": json.loads(r["metrics_json"]),
            "config": json.loads(r["config_json"])
        })
    return results

def get_experiment(exp_id):
    """
    Retrieve full details of a specific experiment.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM experiments WHERE id = ?
    """, (exp_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
        
    return {
        "id": row["id"],
        "name": row["name"],
        "timestamp": row["timestamp"],
        "ticker": row["ticker"],
        "interval": row["interval"],
        "strategy_mode": row["strategy_mode"],
        "config": json.loads(row["config_json"]),
        "metrics": json.loads(row["metrics_json"]),
        "equity_curve": json.loads(row["equity_curve_json"]),
        "drawdown_curve": json.loads(row["drawdown_curve_json"]),
        "regime_breakdown": json.loads(row["regime_breakdown_json"]),
        "ai_report": row["ai_report"]
    }

def delete_experiment(exp_id):
    """
    Delete a specific experiment.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM experiments WHERE id = ?", (exp_id,))
    conn.commit()
    deleted_rows = cursor.rowcount
    conn.close()
    return deleted_rows > 0

def compare_experiments(exp_ids):
    """
    Compare multiple experiments by retrieving their config & metrics.
    """
    if not exp_ids:
        return []
        
    conn = get_connection()
    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(exp_ids))
    query = f"""
        SELECT id, name, timestamp, ticker, interval, strategy_mode, metrics_json, config_json, equity_curve_json
        FROM experiments
        WHERE id IN ({placeholders})
    """
    cursor.execute(query, tuple(exp_ids))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "name": r["name"],
            "timestamp": r["timestamp"],
            "ticker": r["ticker"],
            "interval": r["interval"],
            "strategy_mode": r["strategy_mode"],
            "metrics": json.loads(r["metrics_json"]),
            "config": json.loads(r["config_json"]),
            "equity_curve": json.loads(r["equity_curve_json"])
        })
    return results
