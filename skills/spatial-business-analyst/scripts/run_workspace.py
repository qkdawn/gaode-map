#!/usr/bin/env python3
"""Validate a persisted V4.1 spatial-business-analyst run."""
from __future__ import annotations
import argparse, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from store.analysis_run_storage import AnalysisRunStorage

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument('--root',default=''); parser.add_argument('--run-id',required=True); args=parser.parse_args()
    storage=AnalysisRunStorage(args.root or None); storage.validate('spatial-business-analyst',args.run_id); print(storage._path('spatial-business-analyst',args.run_id)); return 0
if __name__=='__main__': raise SystemExit(main())
