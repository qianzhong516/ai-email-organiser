from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from classify_emails import output_accuracy


# Builds synthetic labeled records; no real email content is used in these tests.
@pytest.fixture
def dataset():
    return [
        {
            "id": index,
            "subject": f"Example {index}",
            "sender": "author@example.com",
            "date": "",
            "body": "Example content.",
            "expected": {"sender_type": label},
        }
        for index, label in enumerate(("tech", "recruitment", "others"), start=1)
    ]


# Saves mock datasets only inside pytest's temporary directory.
@pytest.fixture
def write_dataset(tmp_path):
    # Returns the path to a temporary JSON file containing the supplied records.
    def write(records):
        path = tmp_path / "dataset.json"
        path.write_text(json.dumps(records), encoding="utf-8")
        return path

    return write


# Fails immediately if scoring unexpectedly tries to create an Ollama connection.
@pytest.fixture(autouse=True)
def no_model_calls():
    with patch("classify_emails.urllib.request.build_opener", side_effect=AssertionError("Scoring must not call Ollama")):
        yield


# Builds mock classifier results with independent predictions and explanations.
def make_results(dataset, labels):
    return [
        {
            **deepcopy(record),
            "prediction": {"sender_type": label, "explanation": "Mock explanation."},
        }
        for record, label in zip(dataset, labels)
    ]


# Checks perfect, entirely incorrect, and mixed predictions, including rounding.
@pytest.mark.parametrize(
    "labels,correct,accuracy",
    [
        (["tech", "recruitment", "others"], 3, 100.0),
        (["others", "tech", "tech"], 0, 0.0),
        (["tech", "others", "others"], 2, 66.67),
    ],
)
def test_accuracy_counts_and_percentage(dataset, write_dataset, labels, correct, accuracy):
    results = make_results(dataset, labels)
    report = output_accuracy(results, write_dataset(dataset))

    assert report["total"] == report["evaluated"] == 3
    assert report["correct"] == correct
    assert report["incorrect"] == 3 - correct
    assert report["unlabeled"] == 0
    assert report["accuracy_percent"] == accuracy
    assert report["comparisons"] == [
        {
            "id": record["id"],
            "expected": record["expected"],
            "prediction": result["prediction"],
            "correct": record["expected"]["sender_type"] == result["prediction"]["sender_type"],
        }
        for record, result in zip(dataset, results)
    ]


# Excludes unannotated emails from the denominator while retaining their comparisons.
def test_unlabeled_records_are_not_scored(dataset, write_dataset):
    dataset[0]["expected"]["sender_type"] = None
    report = output_accuracy(make_results(dataset, ["tech", "tech", "others"]), write_dataset(dataset))

    assert report["total"] == 3
    assert report["evaluated"] == 2
    assert report["correct"] == report["incorrect"] == report["unlabeled"] == 1
    assert report["accuracy_percent"] == 50.0
    assert report["comparisons"][0]["correct"] is None


# Returns no accuracy, rather than a misleading zero or 100%, when no labels exist.
def test_all_unlabeled_records_have_no_accuracy(dataset, write_dataset):
    for record in dataset:
        record["expected"]["sender_type"] = None
    report = output_accuracy(make_results(dataset, ["tech", "recruitment", "others"]), write_dataset(dataset))

    assert report["total"] == report["unlabeled"] == 3
    assert report["evaluated"] == report["correct"] == report["incorrect"] == 0
    assert report["accuracy_percent"] is None
    assert all(comparison["correct"] is None for comparison in report["comparisons"])


# Handles two empty arrays without dividing by zero.
def test_empty_dataset_has_no_accuracy(write_dataset):
    assert output_accuracy([], write_dataset([])) == {
        "total": 0, "evaluated": 0, "correct": 0, "incorrect": 0,
        "unlabeled": 0, "accuracy_percent": None, "comparisons": [],
    }


# Matches by ID even when result order differs, preserving dataset order in the report.
def test_results_are_matched_by_id(dataset, write_dataset):
    results = make_results(dataset, ["tech", "recruitment", "others"])[::-1]
    report = output_accuracy(results, write_dataset(dataset))

    assert report["accuracy_percent"] == 100.0
    assert [comparison["id"] for comparison in report["comparisons"]] == [1, 2, 3]


# Uses source-file human labels even if the classifier results contain changed labels.
def test_source_dataset_is_the_reference(dataset, write_dataset):
    results = make_results(dataset, ["others", "others", "others"])
    for result in results:
        result["expected"]["sender_type"] = "others"
    report = output_accuracy(results, write_dataset(dataset))

    assert report["correct"] == 1
    assert report["accuracy_percent"] == 33.33
    assert report["comparisons"][0]["expected"]["sender_type"] == "tech"


# Scores sender types only, and does not mutate predictions or the source JSON.
def test_explanations_are_not_scored_and_inputs_are_unchanged(dataset, write_dataset):
    results = make_results(dataset, ["tech", "recruitment", "others"])
    for record in dataset:
        record["expected"]["explanation"] = "A different human explanation."
    original_results = deepcopy(results)
    path = write_dataset(dataset)
    original_file = path.read_bytes()

    report = output_accuracy(results, path)

    assert report["accuracy_percent"] == 100.0
    assert results == original_results
    assert path.read_bytes() == original_file


# Rejects missing, extra, or substituted email IDs rather than scoring a partial set.
@pytest.mark.parametrize("ids", [[1, 2], [1, 2, 3, 4], [1, 2, 4]])
def test_mismatched_id_sets_raise_error(dataset, write_dataset, ids):
    results = [{"id": email_id, "prediction": {"sender_type": "tech"}} for email_id in ids]
    with pytest.raises(ValueError, match="exactly the same email IDs"):
        output_accuracy(results, write_dataset(dataset))


# Rejects repeated IDs in either input, even if both collections contain the same IDs.
@pytest.mark.parametrize("side", ["dataset", "results"])
def test_duplicate_ids_raise_error(dataset, write_dataset, side):
    results = make_results(dataset, ["tech", "recruitment", "others"])
    (dataset if side == "dataset" else results).append(deepcopy((dataset if side == "dataset" else results)[0]))
    with pytest.raises(ValueError, match=f"Duplicate id 1 in {side}"):
        output_accuracy(results, write_dataset(dataset))


# Requires arrays for both the source dataset and classifier results.
@pytest.mark.parametrize("side", ["dataset", "results"])
@pytest.mark.parametrize("invalid", [None, {}, "records"])
def test_inputs_must_be_arrays(dataset, write_dataset, side, invalid):
    results = make_results(dataset, ["tech", "recruitment", "others"])
    path = write_dataset(invalid if side == "dataset" else dataset)
    with pytest.raises(ValueError, match=f"{side} must be an array"):
        output_accuracy(invalid if side == "results" else results, path)


# Requires positive integer IDs on every record in either collection.
@pytest.mark.parametrize("side", ["dataset", "results"])
@pytest.mark.parametrize("invalid", [None, {}, {"id": True}, {"id": "1"}, {"id": 0}, {"id": -1}])
def test_invalid_records_and_ids_raise_error(dataset, write_dataset, side, invalid):
    results = make_results(dataset, ["tech", "recruitment", "others"])
    (dataset if side == "dataset" else results)[0] = invalid
    with pytest.raises(ValueError, match=f"Each {side} record must have a positive integer id"):
        output_accuracy(results, write_dataset(dataset))


# Rejects malformed human labels while allowing null only for unannotated records.
@pytest.mark.parametrize("expected", [None, {}, "tech", {"sender_type": "invalid"}, {"sender_type": []}])
def test_invalid_expected_fields_raise_error(dataset, write_dataset, expected):
    results = make_results(dataset, ["tech", "recruitment", "others"])
    dataset[0]["expected"] = expected
    with pytest.raises(ValueError, match="Invalid expected.sender_type for email id 1"):
        output_accuracy(results, write_dataset(dataset))


# Rejects missing or invalid predictions instead of skipping them during scoring.
@pytest.mark.parametrize("prediction", [None, {}, "tech", {"sender_type": None}, {"sender_type": "invalid"}, {"sender_type": []}])
def test_invalid_predictions_raise_error(dataset, write_dataset, prediction):
    results = make_results(dataset, ["tech", "recruitment", "others"])
    results[0]["prediction"] = prediction
    with pytest.raises(ValueError, match="Invalid prediction.sender_type for email id 1"):
        output_accuracy(results, write_dataset(dataset))


# Rejects malformed JSON without modifying the original file.
def test_invalid_json_raises_error(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('[{"id":', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        output_accuracy([], path)
    assert path.read_text(encoding="utf-8") == '[{"id":'
