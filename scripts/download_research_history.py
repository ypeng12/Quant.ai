#!/usr/bin/env python3
"""Download actual historical data with explicit feed and provenance."""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.market_data.history import download_history
from app.research.universe import LIQUID_US_IEX_30
from requests import RequestException

def main():
    p=argparse.ArgumentParser(description=__doc__)
    universe=p.add_mutually_exclusive_group(required=True)
    universe.add_argument('--symbols',nargs='+')
    universe.add_argument('--universe30',action='store_true')
    p.add_argument('--start',required=True);p.add_argument('--end',required=True)
    p.add_argument('--feed',choices=['iex','sip'],default='iex')
    p.add_argument('--kind',choices=['quotes','trades','bars'],required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--max-pages',type=int,default=0)
    p.add_argument('--env-file',type=Path,help='Existing local .env path; secrets are never passed on the command line')
    a=p.parse_args()
    if a.env_file: os.environ['ALPACA_ENV_FILE']=str(a.env_file.expanduser().resolve())
    try: print(download_history(LIQUID_US_IEX_30 if a.universe30 else a.symbols,a.start,a.end,a.feed,a.kind,a.output,max_pages=a.max_pages)['status'])
    except (ValueError, OSError) as e: p.exit(1,str(e)+'\n')
    except RequestException as e: p.exit(1,'Historical network request failed: '+type(e).__name__+'\n')
if __name__=='__main__':main()
