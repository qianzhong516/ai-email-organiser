### Start the app

```bash
./start.sh
```

### Run tests

```
python -m pytest
```

Run a specific test

```
python -m pytest tests/test_read_emails.py::test_read_emails -v
```

### Create datasets

100 emails for Development dataset, 250 emails for Test dataset

Fetch up to 400 emails, parse and deduplicate them, then take the first 350
unique records before shuffling into the two datasets.

Each email body is processed by `HTML_parser`. Records include
`"expected": {"sender_type": null}` for human annotation. Exclude `expected`
when constructing LLM inputs; compare it with predictions afterward.

```bash
python3 data/create_datasets.py \
  --username 'janice.zhong@proton.me' \
  --password 'YOUR_BRIDGE_PASSWORD'
```

### Classify a dataset

To classify and save both predictions and an accuracy report:

```bash
python3 classify_emails.py --dataset data/datasets/development_emails.json
```

For the test dataset, replace the path with `data/datasets/test_emails.json`.
Optional arguments are `--prompt`, `--model`, and `--ollama-url`. Each invocation
saves timestamped `*_predictions.json` and `*_accuracy.json` files under
`data/results/` and prints their paths plus the accuracy summary. Previous
results and source datasets are preserved. Null human labels are excluded from
scoring; if none are labeled, the report has no accuracy percentage.

Edit `prompting/sender_type.txt` to change the if/else rules and few-shot examples.
Example outputs include a sender type and a short explanation. The allowed
sender types are `tech`, `recruitment`, and `others`.

```python
from classify_emails import classify_emails

results = classify_emails("data/datasets/development_emails.json")
# Or: results = classify_emails("data/datasets/test_emails.json")
```

The function calls local Ollama sequentially using `qwen2.5:7b`. Optional keyword
arguments are `prompt_path`, `model`, and `ollama_url`. Each input record is sent
without its entire `expected` field or any previous `prediction`. Returned
records preserve email content and human `expected` answers, adding a separate
`prediction` object with `sender_type` and `explanation`. Compare
`expected.sender_type` with `prediction.sender_type` to evaluate accuracy; the
explanation is for inspecting mistakes. The original dataset file is not
modified, and no output is saved automatically.

### Measure prediction accuracy

```python
from classify_emails import classify_emails, output_accuracy

dataset = "data/datasets/development_emails.json"
results = classify_emails(dataset)
accuracy = output_accuracy(results, dataset)
print(accuracy["accuracy_percent"])
print(accuracy["comparisons"])
```

`output_accuracy` matches email IDs and compares the original dataset's
`expected.sender_type` with each result's `prediction.sender_type`. It returns
counts, an accuracy percentage, and side-by-side comparisons. Explanations are
not scored. Unlabeled records are counted separately; if all are unlabeled,
`accuracy_percent` is `None`. Duplicate IDs or incomplete/mismatched result sets
raise an error rather than being silently omitted from scoring. This function
does not call Ollama or modify any files.
