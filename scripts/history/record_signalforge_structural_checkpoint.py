from __future__ import annotations
import argparse
from processors.structural_validation_registry import complete_structural_checkpoint

p=argparse.ArgumentParser(description="Record a due, pre-registered SignalForge structural checkpoint outcome.")
p.add_argument("--checkpoint",required=True); p.add_argument("--result",required=True,choices=["strengthened","persisted","weakened","invalidated"]); p.add_argument("--evidence-ref",action="append",required=True); p.add_argument("--note",required=True)
a=p.parse_args(); row=complete_structural_checkpoint(checkpoint_id=a.checkpoint,result=a.result,evidence_refs=a.evidence_ref,note=a.note)
print("SIGNALFORGE STRUCTURAL CHECKPOINT RECORDED")
print("Checkpoint:",row["checkpoint_id"]); print("Result:",row["result"]); print("This updates calibration only; Radar C01-C14 truth was not changed.")
