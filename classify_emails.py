import json
from pathlib import Path
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
) -> list[dict]:
    """Classify a development or test JSON dataset using the supplied prompt.

    Sends every field except expected and any previous prediction to Ollama.
    Returns the same record order, email content, and human expected labels,
    adding prediction with sender_type (tech, recruitment, or others) and a short
    explanation. Compare expected.sender_type with prediction.sender_type for
    evaluation; explanations are for inspection, not proof of correctness.
    This function does not save output, access the inbox, or apply email labels.
    """
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
            with opener.open(request, timeout=300) as response:
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
        predictions.append({
            **record,
            "prediction": prediction,
        })
    return predictions
