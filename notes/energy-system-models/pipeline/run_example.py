"""Solve models and write results. Template for the note's run_* scripts.

    python pipeline/run_example.py            small instance (default)
    python pipeline/run_example.py --size full

Stage 2 of the pipeline: the expensive one. Reads `data/processed/` and
`model/`, writes `results/`. Everything the note needs must be written out here
— `build.py` may not reach back into the models for it.

Instance size is a parameter with a small default, so that a student who clones
the repository gets an answer in seconds. The note's own figures may come from
`--size full`; the published default must not.
"""

import argparse
import json
from pathlib import Path

NOTE = Path(__file__).resolve().parent.parent
PROCESSED = NOTE / "data" / "processed"
RESULTS = NOTE / "results"
CACHE = RESULTS / "cache"

SIZES = {
    # Keep "small" genuinely small: seconds, not minutes. It is the one most
    # people will ever run.
    "small": {},
    "full": {},
}


def load_inputs():
    if not PROCESSED.exists():
        raise SystemExit(
            "data/processed/ does not exist — run data/prepare.py first."
        )
    # TODO: read the processed inputs this experiment needs.
    return {}


def solve(inputs, size):
    # TODO: build and solve the model at this instance size.
    return {}


def write_results(solution, size):
    """Write everything the note needs, as plain data.

    build.py reads these files and nothing else, so any number, label or
    parameter that appears in a figure has to be written here — including the
    ones that feel like they belong to the model.
    """
    RESULTS.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    out = RESULTS / f"example_{size}.json"
    out.write_text(json.dumps(solution, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(NOTE)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", choices=sorted(SIZES), default="small")
    args = parser.parse_args()

    inputs = load_inputs()
    solution = solve(inputs, SIZES[args.size])
    write_results(solution, args.size)


if __name__ == "__main__":
    main()
