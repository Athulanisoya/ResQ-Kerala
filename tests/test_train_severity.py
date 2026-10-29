import csv
import pytest
from scripts.train_severity import train


def test_train_records_held_out_evaluation_without_replacing_shipped_model(tmp_path):
    dataset = tmp_path / "labelled.csv"
    with dataset.open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["message", "severity"])
        for severity, text in [("Low", "monitor rising water"), ("Moderate", "road blocked water"), ("High", "trapped immediate rescue")]:
            for number in range(8):
                writer.writerow([f"{text} example {number}", severity])
    output = tmp_path / "output"
    result = train(dataset, output)
    assert result["examples"] == 24
    assert result["test_examples"] == 6
    assert result["confusion_matrix_labels"] == ["Low", "Moderate", "High"]
    assert (output / "severity_pipeline.joblib").is_file()
    assert (output / "evaluation.json").is_file()


def test_train_rejects_incomplete_class_labels(tmp_path):
    dataset = tmp_path / "bad.csv"
    dataset.write_text("message,severity\nwater rising,unknown\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid"):
        train(dataset, tmp_path / "out")
