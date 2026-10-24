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
