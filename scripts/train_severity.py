"""Train and evaluate an experimental severity model from a labelled CSV.

This tool never overwrites the running model unless its output path is explicitly
selected. Evaluation scores do not establish suitability for emergency use.
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

LABELS = {"low": "Low", "medium": "Moderate", "moderate": "Moderate", "high": "High"}


def train(dataset: Path, output_dir: Path, *, seed: int = 42) -> dict:
    with dataset.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not {"message", "severity"}.issubset(reader.fieldnames or []):
            raise ValueError("Dataset must have message and severity columns.")
        texts, labels = [], []
        for line, row in enumerate(reader, 2):
            message = (row.get("message") or "").strip()
            label = LABELS.get((row.get("severity") or "").strip().lower())
            if not message or label is None:
                raise ValueError(f"Invalid message or severity on row {line}.")
            texts.append(message)
            labels.append(label)
    counts = Counter(labels)
    if set(counts) != {"Low", "Moderate", "High"} or min(counts.values()) < 5:
        raise ValueError("At least five labelled examples per class are required.")
    x_train, x_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.25, random_state=seed, stratify=labels,
    )
    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1, 2))),
        ("classifier", LogisticRegression(max_iter=1000, random_state=seed)),
    ])
    pipeline.fit(x_train, y_train)
    predicted = pipeline.predict(x_test)
    ordered = ["Low", "Moderate", "High"]
    results = {
        "dataset": str(dataset), "seed": seed, "examples": len(texts),
        "class_counts": dict(counts), "test_examples": len(x_test),
        "classification_report": classification_report(y_test, predicted, labels=ordered, output_dict=True, zero_division=0),
        "confusion_matrix_labels": ordered,
        "confusion_matrix": confusion_matrix(y_test, predicted, labels=ordered).tolist(),
        "warning": "Experimental scores are not validation for emergency decisions. Human review is required.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, output_dir / "severity_pipeline.joblib")
    (output_dir / "evaluation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    report = train(args.dataset, args.output_dir, seed=args.seed)
    print(f"Trained experimental model; held-out examples: {report['test_examples']}. See evaluation.json.")


if __name__ == "__main__":
    main()
