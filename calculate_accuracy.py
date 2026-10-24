import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from classify_emails import output_accuracy


# Compares saved predictions with human labels and saves a timestamped accuracy
# report under data/results without making any requests to Ollama.
def main():
    parser = argparse.ArgumentParser(description="Calculate accuracy from saved predictions and a reference dataset.")
    parser.add_argument("--input", type=Path, required=True, help="Predictions JSON file")
    parser.add_argument("--reference", type=Path, required=True, help="Dataset JSON file containing expected labels")
    args = parser.parse_args()

    try:
        results = json.loads(args.input.read_text(encoding="utf-8"))
        report = output_accuracy(results, args.reference)
        output_folder = Path(__file__).resolve().parent / "data" / "results"
        output_folder.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        report_path = output_folder / f"{args.input.stem}_{timestamp}_accuracy.json"
        with report_path.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")

        print(f"Accuracy report: {report_path}")
        if report["accuracy_percent"] is None:
            print("Accuracy: unavailable (no human-labeled records)")
        else:
            print(f"Accuracy: {report['accuracy_percent']:.2f}% ({report['correct']}/{report['evaluated']} correct)")
        print(f"Incorrect: {report['incorrect']}; unlabeled: {report['unlabeled']}; total: {report['total']}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
