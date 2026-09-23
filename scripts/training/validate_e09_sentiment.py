"""
Module: validate_e09_sentiment.py
Description: Real-data validation for Engine 09 (Sentiment Intelligence) --
    not a threshold-fitting "calibration" run (POSITIVE_THRESHOLD=0.15/
    NEGATIVE_THRESHOLD=-0.15 are the engine's own shipped defaults, unchanged
    here), but the first real check of E09's sentiment classification
    against a REAL labeled ground-truth dataset (user-supplied,
    data/database/Stock-Market Sentiment Dataset.zip -- 5,791 real stock-
    market social-media posts, each hand-labeled Positive(1)/Negative(-1)).
    Per Rule 3.3's "calibration must be validated, not just fit" spirit:
    this is the validation half for an engine whose thresholds were never
    fit against real data in the first place -- if accuracy comes out poor,
    that's an honest finding to report, not something to silently paper
    over by adjusting thresholds until this one sample looks good.

    Runs a real random sample (SAMPLE_SIZE below), not the full 5,791 --
    FinBERT inference is CPU-bound and this machine is concurrently running
    a separate long book-ingestion job; a modest, clearly-labeled sample
    keeps this honest (real numbers, real confidence interval) without
    materially competing for CPU. Re-run with a larger SAMPLE_SIZE any time
    more headroom is available -- nothing here is sized to this one dataset
    specifically.
Author: Shantanu Waykar
Version: 1.0.0
"""

import csv
import json
import logging
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e09_sentiment.engine import SentimentIntelligenceEngine  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "database" / "_extracted" / "stock_data.csv"
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e09_sentiment" / "validation_report.json"

SAMPLE_SIZE = 500
RANDOM_SEED = 42  # fixed for reproducibility -- same sample every re-run unless SAMPLE_SIZE/data changes

# E09's SentimentResult.label is "positive"/"negative"/"neutral"; this
# dataset only has two classes (no neutral ground truth), so "neutral"
# predictions are scored as a MISS against whichever real label the row
# has -- not dropped, not scored as correct by default. An honest
# treatment of the mismatch in label granularity, not swept under the rug.
GROUND_TRUTH_TO_LABEL = {"1": "positive", "-1": "negative"}


def load_dataset() -> list[tuple[str, str]]:
    rows = []
    with open(DATA_PATH, encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            if len(row) < 2:
                continue
            text, label = row[0], row[-1].strip()
            if label in GROUND_TRUTH_TO_LABEL and text.strip():
                rows.append((text, GROUND_TRUTH_TO_LABEL[label]))
    return rows


def main() -> None:
    print(f"Loading real labeled dataset from {DATA_PATH}...")
    all_rows = load_dataset()
    print(f"Loaded {len(all_rows)} real labeled rows (Positive/Negative).")

    rng = random.Random(RANDOM_SEED)
    sample = rng.sample(all_rows, min(SAMPLE_SIZE, len(all_rows)))
    print(f"Validating on a random sample of {len(sample)} (seed={RANDOM_SEED}).")

    engine = SentimentIntelligenceEngine()
    engine.initialize()

    correct = 0
    confusion = {"positive": {"positive": 0, "negative": 0, "neutral": 0},
                 "negative": {"positive": 0, "negative": 0, "neutral": 0}}
    errors = 0
    predictions = []

    for i, (text, true_label) in enumerate(sample, start=1):
        result = engine.analyze_text(text)
        if not result.success or result.data is None:
            errors += 1
            continue
        pred_label = result.data.label
        confusion[true_label][pred_label] += 1
        if pred_label == true_label:
            correct += 1
        predictions.append({"text": text[:120], "true": true_label, "predicted": pred_label, "score": result.data.compound_score})
        if i % 50 == 0:
            print(f"  {i}/{len(sample)} scored, running accuracy: {correct/i:.1%}")

    n_scored = len(sample) - errors
    accuracy = correct / n_scored if n_scored else 0.0

    def precision_recall(label: str) -> tuple[float, float]:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in confusion if other != label)
        fn = sum(v for k, v in confusion[label].items() if k != label)
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        return precision, recall

    pos_p, pos_r = precision_recall("positive")
    neg_p, neg_r = precision_recall("negative")

    print(f"\n=== REAL validation result (n={n_scored}, {errors} scoring errors) ===")
    print(f"Overall accuracy: {accuracy:.1%}")
    print(f"Positive: precision={pos_p:.1%} recall={pos_r:.1%}" if pos_p is not None else "Positive: n/a")
    print(f"Negative: precision={neg_p:.1%} recall={neg_r:.1%}" if neg_p is not None else "Negative: n/a")
    print(f"Confusion matrix: {confusion}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATA_PATH),
        "total_dataset_rows": len(all_rows),
        "sample_size": len(sample),
        "random_seed": RANDOM_SEED,
        "n_scored": n_scored,
        "n_scoring_errors": errors,
        "accuracy": round(accuracy, 4),
        "positive_precision": pos_p, "positive_recall": pos_r,
        "negative_precision": neg_p, "negative_recall": neg_r,
        "confusion_matrix": confusion,
        "sample_predictions": predictions[:30],  # a few examples, not the whole sample -- report stays a reasonable size
    }, indent=2))
    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
