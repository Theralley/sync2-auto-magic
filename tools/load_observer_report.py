"""Inspect a published LOAD.CSV; never interprets load as CPU frequency or clock authority."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from s2am.load_observer import read_result


def summary(result):
    accounted=[i["share_upper_pct"] for i in result["self_intervals"]
               if not i["invalid"] and not i["implausible"]]
    elapsed=[r["collection_latency_qpc"]*1000/result["qpf"] for r in result["rounds"]]
    return {
        "meaning":"observed CPU-time distribution and coverage only",
        "rounds":len(result["rounds"]),
        "observed_intervals":len(result["observed_intervals"]),
        "max_collection_elapsed_ms":max(elapsed,default=None),
        "max_sampler_accounted_cpu_upper_pct":max(accounted,default=None),
        "sampler_cost_scope":"main thread accounted CPU only; indirect OS/I/O cost unmeasured",
        "partial":result["partial"],
        "qualified":False,"settled":False,"cpu_rate_qualified":False,"write_authorized":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture",type=Path)
    parser.add_argument("--raw",action="store_true",help="include all parsed records and per-thread intervals")
    args=parser.parse_args(argv)
    try:
        result=read_result(args.capture)
    except (OSError,ValueError) as error:
        print(f"Invalid capture: {error}",file=sys.stderr)
        return 1
    print(json.dumps(result if args.raw else summary(result),indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
