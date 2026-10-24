import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Callable
import urllib.request


# Classifies dataset records one at a time, keeping human answers separate from
# the model's predicted sender type and explanation without changing the file.
# Returns a list in the original record order:
# [
#     {
#         "id": 1,
#         "subject": "Example subject",
#         "sender": "author@example.com",
#         "date": "Sat, 24 Oct 2026 10:00:00 +1100",
#         "body": "Parsed email text...",
#         "expected": {"sender_type": null},
#         "prediction": {
#             "sender_type": "tech",
#             "explanation": "The author shares a technical tutorial."
#         }
#     }
# ]
# expected retains the human label (or null); prediction.sender_type is one of
# "tech", "recruitment", or "others". Any additional input fields are preserved.
def classify_emails(
    dataset_path: str | Path,
    *,
    prompt_path: str | Path = Path(__file__).resolve().parent / "prompting" / "sender_type.txt",
    model: str = "qwen2.5:7b",
    ollama_url: str = "http://127.0.0.1:11434",
    timeout: int = 900,
    on_result: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Classify a development or test JSON dataset using the supplied prompt.

    Sends every field except expected and any previous prediction to Ollama.
    Returns the same record order, email content, and human expected labels,
    adding prediction with sender_type (tech, recruitment, or others) and a short
    explanation. Compare expected.sender_type with prediction.sender_type for
    evaluation; explanations are for inspection, not proof of correctness.
    If supplied, on_result receives each completed record immediately, allowing
    the caller to save results incrementally. The function still returns the
    complete list. By default it does not save output, access the inbox, or apply
    email labels. Callback errors stop processing and propagate to the caller.
    Timeout is a positive integer in seconds for each Ollama request (default 900).
    """
    if type(timeout) is not int or timeout < 1:
        raise ValueError("timeout must be a positive integer in seconds")
    records = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    sender_types = ("tech", "recruitment", "others")
    if not isinstance(records, list):
        raise ValueError("The dataset must be a JSON array")
    for record in records:
        if (
            not isinstance(record, dict)
            or not {"id", "subject", "sender", "date", "body", "expected"} <= record.keys()
            or not isinstance(record["expected"], dict)
            or "sender_type" not in record["expected"]
        ):
            raise ValueError("Each record must contain id, subject, sender, date, body, and expected.sender_type")
        if type(record["id"]) is not int or record["id"] < 1:
            raise ValueError("Each record's id must be a positive integer")
        for field in ("subject", "sender", "date", "body"):
            if not isinstance(record[field], str):
                raise ValueError(f"Each record's {field} must be a string")
        if record["expected"]["sender_type"] not in (None, *sender_types):
            raise ValueError("expected.sender_type must be null, tech, recruitment, or others")

    prompt = Path(prompt_path).read_text(encoding="utf-8")
    if not prompt.strip():
        raise ValueError("The classification prompt must not be empty")
    schema = {
        "type": "object",
        "properties": {
            "prediction": {
                "type": "object",
                "properties": {
                    "sender_type": {"type": "string", "enum": list(sender_types)},
                    "explanation": {"type": "string", "minLength": 1},
                },
                "required": ["sender_type", "explanation"],
                "additionalProperties": False,
            },
        },
        "required": ["prediction"],
        "additionalProperties": False,
    }
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    predictions = []
    for record in records:
        model_input = {key: value for key, value in record.items() if key not in ("expected", "prediction")}
        payload = {
            "model": model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "seed": 42, "num_ctx": 16384, "num_predict": 160},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(model_input, ensure_ascii=False)},
            ],
        }
        request = urllib.request.Request(
            ollama_url.rstrip("/") + "/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                response_data = json.load(response)
            if not response_data.get("done") or response_data.get("done_reason") == "length":
                raise ValueError("Ollama returned an incomplete response")
            model_output = json.loads(response_data["message"]["content"])
            if not isinstance(model_output, dict) or set(model_output) != {"prediction"}:
                raise ValueError("Expected a JSON object containing only prediction")
            prediction = model_output["prediction"]
            if (
                not isinstance(prediction, dict)
                or set(prediction) != {"sender_type", "explanation"}
                or prediction["sender_type"] not in sender_types
                or not isinstance(prediction["explanation"], str)
                or not prediction["explanation"].strip()
            ):
                raise ValueError("Expected sender_type (tech, recruitment, or others) and a non-empty explanation")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise RuntimeError(f"Classification failed for email id {record['id']}: {error}") from error
        completed = {
            **record,
            "prediction": prediction,
        }
        predictions.append(completed)
        if on_result is not None:
            on_result(completed)
    return predictions


# Compares human labels from the original dataset with model predictions by id.
# Returns total/evaluated/correct/incorrect/unlabeled counts, accuracy_percent,
# and comparisons containing id, expected, prediction, and correct side by side.
def output_accuracy(results: list[dict], dataset_path: str | Path) -> dict:
    """Measure sender-type accuracy without calling Ollama or changing files.

    Uses expected.sender_type from the dataset, not the copy in results.
    Explanations are shown for review but are not part of the accuracy score.
    Null human labels are counted as unlabeled and excluded from the denominator.
    Accuracy is a percentage, or None if no labeled records can be evaluated.
    Missing, extra, duplicate, or invalid record IDs raise ValueError so partial
    results cannot silently produce an inflated accuracy score.
    """
    dataset = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    sender_types = ("tech", "recruitment", "others")

    # Index records by unique IDs so different array orders do not affect scoring.
    def index_records(records, name):
        if not isinstance(records, list):
            raise ValueError(f"{name} must be an array of records")
        indexed = {}
        for record in records:
            if not isinstance(record, dict) or type(record.get("id")) is not int or record["id"] < 1:
                raise ValueError(f"Each {name} record must have a positive integer id")
            if record["id"] in indexed:
                raise ValueError(f"Duplicate id {record['id']} in {name}")
            indexed[record["id"]] = record
        return indexed

    expected_records = index_records(dataset, "dataset")
    predicted_records = index_records(results, "results")
    if expected_records.keys() != predicted_records.keys():
        raise ValueError("Dataset and results must contain exactly the same email IDs")

    comparisons = []
    correct = 0
    evaluated = 0
    for email_id, record in expected_records.items():
        expected = record.get("expected")
        prediction = predicted_records[email_id].get("prediction")
        if (
            not isinstance(expected, dict)
            or "sender_type" not in expected
            or expected["sender_type"] not in (None, *sender_types)
        ):
            raise ValueError(f"Invalid expected.sender_type for email id {email_id}")
        if not isinstance(prediction, dict) or prediction.get("sender_type") not in sender_types:
            raise ValueError(f"Invalid prediction.sender_type for email id {email_id}")

        matched = None
        if expected["sender_type"] is not None:
            evaluated += 1
            matched = expected["sender_type"] == prediction["sender_type"]
            correct += int(matched)
        comparisons.append({
            "id": email_id,
            "expected": expected,
            "prediction": prediction,
            "correct": matched,
        })

    return {
        "total": len(dataset),
        "evaluated": evaluated,
        "correct": correct,
        "incorrect": evaluated - correct,
        "unlabeled": len(dataset) - evaluated,
        "accuracy_percent": round(correct / evaluated * 100, 2) if evaluated else None,
        "comparisons": comparisons,
    }


# Saves each completed prediction incrementally to a timestamped JSON array,
# then writes an accuracy report after the full dataset finishes.
def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Classify an email dataset and report prediction accuracy.")
    parser.add_argument("--dataset", type=Path, required=True, help="Development or test dataset JSON file")
    parser.add_argument("--prompt", type=Path, default=root / "prompting" / "sender_type.txt")
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout", type=int, default=300, help="Per-request timeout in seconds (default: 900)")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be a positive integer in seconds")

    try:
        output_folder = root / "data" / "results"
        output_folder.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        prefix = f"{args.dataset.stem}_{timestamp}"
        predictions_path = output_folder / f"{prefix}_predictions.json"
        report_path = output_folder / f"{prefix}_accuracy.json"

        with predictions_path.open("xb") as output:
            output.write(b"[\n]\n")
            output.flush()
            os.fsync(output.fileno())
            write_position = 2
            completed_count = 0
            print(f"Predictions: {predictions_path}", flush=True)

            # Appends a finished record before the closing bracket, keeping the
            # file valid JSON between updates and flushing each record to disk.
            def save_result(record):
                nonlocal write_position, completed_count
                separator = ",\n" if completed_count else ""
                content = (separator + json.dumps(record, ensure_ascii=False, indent=2)).encode("utf-8")
                output.seek(write_position)
                output.write(content)
                write_position = output.tell()
                output.write(b"\n]\n")
                output.truncate()
                output.flush()
                os.fsync(output.fileno())
                completed_count += 1
                print(
                    f"Saved {completed_count}: email id {record['id']} -> {record['prediction']['sender_type']}",
                    flush=True,
                )

            results = classify_emails(
                args.dataset,
                prompt_path=args.prompt,
                model=args.model,
                ollama_url=args.ollama_url,
                timeout=args.timeout,
                on_result=save_result,
            )

        report = output_accuracy(results, args.dataset)
        with report_path.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
        print(f"Accuracy report: {report_path}")
        if report["accuracy_percent"] is None:
            print("Accuracy: unavailable (no human-labeled records)")
        else:
            print(f"Accuracy: {report['accuracy_percent']:.2f}% ({report['correct']}/{report['evaluated']} correct)")
        print(f"Incorrect: {report['incorrect']}; unlabeled: {report['unlabeled']}; total: {report['total']}")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Stopped. Completed predictions are preserved in data/results/.\n")


if __name__ == "__main__":
    main()
