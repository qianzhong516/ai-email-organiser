import io
import json
from unittest.mock import patch

import pytest

from classify_emails import classify_emails


# Supplies one correctly shaped record that individual tests can modify.
@pytest.fixture
def email_record():
    return {
        "id": 1,
        "subject": "Example email",
        "sender": "author@example.com",
        "date": "Sat, 24 Oct 2026 10:00:00 +1100",
        "body": "Example email content.",
        "expected": {"sender_type": None},
    }


# Writes only temporary inputs and replaces the HTTP connection so no test
# sends email content to Ollama or modifies the real datasets.
@pytest.fixture
def inputs(tmp_path):
    dataset = tmp_path / "dataset.json"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Classify the sender type.", encoding="utf-8")
    with patch("classify_emails.urllib.request.build_opener") as build_opener:
        yield dataset, prompt, build_opener


# Rejects a JSON object, scalar, or null where an array of records is required.
@pytest.mark.parametrize("dataset", [{}, None, "email", 123])
def test_dataset_must_be_an_array(inputs, dataset):
    path, prompt, opener = inputs
    path.write_text(json.dumps(dataset), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON array"):
        classify_emails(path, prompt_path=prompt)
    opener.assert_not_called()


# Rejects broken JSON before classification starts.
def test_dataset_must_be_valid_json(inputs):
    path, prompt, opener = inputs
    path.write_text('[{"id":', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        classify_emails(path, prompt_path=prompt)
    opener.assert_not_called()


# Rejects non-object array items instead of attempting to classify them.
@pytest.mark.parametrize("record", [None, [], "email", 123])
def test_each_record_must_be_an_object(inputs, record):
    path, prompt, opener = inputs
    path.write_text(json.dumps([record]), encoding="utf-8")
    with pytest.raises(ValueError, match="Each record must contain"):
        classify_emails(path, prompt_path=prompt)
    opener.assert_not_called()


# Checks that removing any required field produces an error.
@pytest.mark.parametrize("field", ["id", "subject", "sender", "date", "body", "expected"])
def test_record_requires_all_dataset_fields(inputs, email_record, field):
    path, prompt, opener = inputs
    del email_record[field]
    path.write_text(json.dumps([email_record]), encoding="utf-8")
    with pytest.raises(ValueError, match="Each record must contain"):
        classify_emails(path, prompt_path=prompt)
    opener.assert_not_called()


# Rejects missing/incorrect expected objects, including an object without sender_type.
@pytest.mark.parametrize("expected", [None, [], "tech", {}])
def test_expected_requires_sender_type(inputs, email_record, expected):
    path, prompt, opener = inputs
    email_record["expected"] = expected
    path.write_text(json.dumps([email_record]), encoding="utf-8")
    with pytest.raises(ValueError, match="Each record must contain"):
        classify_emails(path, prompt_path=prompt)
    opener.assert_not_called()


# Rejects invalid IDs, including booleans which Python otherwise treats as integers.
@pytest.mark.parametrize("record_id", [None, "1", True, 1.5, 0, -1])
def test_id_must_be_a_positive_integer(inputs, email_record, record_id):
    path, prompt, opener = inputs
    email_record["id"] = record_id
    path.write_text(json.dumps([email_record]), encoding="utf-8")
    with pytest.raises(ValueError, match="id must be a positive integer"):
        classify_emails(path, prompt_path=prompt)
    opener.assert_not_called()


# Rejects non-text email fields; empty strings remain valid for missing headers/body.
@pytest.mark.parametrize("field", ["subject", "sender", "date", "body"])
@pytest.mark.parametrize("value", [None, 123, [], {}])
def test_email_fields_must_be_strings(inputs, email_record, field, value):
    path, prompt, opener = inputs
    email_record[field] = value
    path.write_text(json.dumps([email_record]), encoding="utf-8")
    with pytest.raises(ValueError, match=f"{field} must be a string"):
        classify_emails(path, prompt_path=prompt)
    opener.assert_not_called()


# Rejects human labels outside the three sender types and the unannotated null value.
@pytest.mark.parametrize("sender_type", ["unknown", 123, True, [], {}])
def test_expected_sender_type_must_be_supported(inputs, email_record, sender_type):
    path, prompt, opener = inputs
    email_record["expected"]["sender_type"] = sender_type
    path.write_text(json.dumps([email_record]), encoding="utf-8")
    with pytest.raises(ValueError, match="expected.sender_type must be"):
        classify_emails(path, prompt_path=prompt)
    opener.assert_not_called()


# Ensures the entire array is validated before even its first valid record is sent.
def test_later_invalid_record_prevents_all_model_requests(inputs, email_record):
    path, prompt, opener = inputs
    path.write_text(json.dumps([email_record, {"id": 2}]), encoding="utf-8")
    with pytest.raises(ValueError, match="Each record must contain"):
        classify_emails(path, prompt_path=prompt)
    opener.assert_not_called()


# Accepts valid annotated and unannotated records. A fake HTTP response lets us
# check label preservation and exclusion from model input, not model accuracy.
@pytest.mark.parametrize("sender_type", [None, "tech", "recruitment", "others"])
def test_valid_dataset_preserves_labels_and_separates_prediction(inputs, email_record, sender_type):
    path, prompt, opener = inputs
    email_record["expected"]["sender_type"] = sender_type
    email_record["prediction"] = {"sender_type": "recruitment", "explanation": "Old answer."}
    for field in ("subject", "sender", "date", "body"):
        email_record[field] = ""
    source = json.dumps([email_record])
    path.write_text(source, encoding="utf-8")
    prediction = {"sender_type": "others", "explanation": "Insufficient evidence for another sender type."}
    response = {"done": True, "message": {"content": json.dumps({"prediction": prediction})}}
    opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(json.dumps(response).encode())

    result = classify_emails(path, prompt_path=prompt)

    assert result == [{**email_record, "prediction": prediction}]
    assert path.read_text(encoding="utf-8") == source
    request = opener.return_value.open.call_args.args[0]
    model_input = json.loads(json.loads(request.data)["messages"][1]["content"])
    assert model_input == {key: email_record[key] for key in ("id", "subject", "sender", "date", "body")}
