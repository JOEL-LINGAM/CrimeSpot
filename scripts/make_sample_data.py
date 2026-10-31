"""Generate a SYNTHETIC development sample (NOT real crime data). Includes deliberately bad rows
so the cleaning rules can be exercised. Use only to test the pipeline."""
import argparse, csv, random
from datetime import datetime, timedelta
from pathlib import Path

CATS = ["THEFT", "BATTERY", "CRIMINAL DAMAGE", "ASSAULT", "BURGLARY", "ROBBERY", "NARCOTICS"]
CENTRES = [(41.88, -87.63, 0.03), (41.75, -87.62, 0.04), (41.95, -87.70, 0.03)]   # fake hotspots

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=5000)
    ap.add_argument("--out", default="data/sample/synthetic_sample.csv")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2020, 1, 1)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Date", "Primary Type", "Community Area", "Latitude", "Longitude"])
        for i in range(a.rows):
            la, lo, s = rnd.choice(CENTRES)
            ts = start + timedelta(minutes=rnd.randint(0, 60 * 24 * 365 * 3))
            row = [100000 + i, ts.strftime("%m/%d/%Y %I:%M:%S %p"), rnd.choice(CATS), rnd.randint(1, 77),
                   round(rnd.gauss(la, s), 6), round(rnd.gauss(lo, s), 6)]
            r = rnd.random()
            if r < 0.01: row[1] = ""                    # missing timestamp
            elif r < 0.02: row[1] = "not a date"        # malformed
            elif r < 0.03: row[4] = row[5] = ""         # missing coordinates
            elif r < 0.04: row[4], row[5] = 0, 0        # invalid (0,0)
            elif r < 0.05: row[4], row[5] = 30.0, -90.0 # outside study area
            elif r < 0.06: row[2] = "  "                # blank category
            elif r < 0.08: row[2] = row[2].lower()      # inconsistent case (kept, normalised)
            w.writerow(row)
            if rnd.random() < 0.02: w.writerow(row)     # exact duplicate of the same incident id
    print(f"Wrote SYNTHETIC sample to {a.out}")

if __name__ == "__main__":
    main()
