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
