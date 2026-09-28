from __future__ import annotations
import argparse
from processors.structural_validation_registry import create_structural_checkpoint

p=argparse.ArgumentParser(description="Pre-register a longitudinal SignalForge Zip2/structural thesis checkpoint.")
p.add_argument("--thesis",required=True); p.add_argument("--horizon-days",type=int,default=30); p.add_argument("--note",default=None)
a=p.parse_args(); row=create_structural_checkpoint(thesis_id=a.thesis,horizon_days=a.horizon_days,note=a.note)
print("SIGNALFORGE STRUCTURAL CHECKPOINT PRE-REGISTERED")
print("Checkpoint:",row["checkpoint_id"]); print("Thesis:",row["thesis_id"]); print("Due:",row["due_at"]); print("Result remains UNVALIDATED until a due, evidence-backed outcome is recorded.")
