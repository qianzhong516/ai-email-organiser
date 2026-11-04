### Hardware requirements

CPU: > 3 cores
Memory: >= 7GB, < 12GB

A snapshot of `docker stats`:

```
CONTAINER ID   NAME                                  CPU %     MEM USAGE / LIMIT     MEM %     NET I/O         BLOCK I/O        PIDS
70cb8027b55e   email-organiser-ollama-1              297.84%   6.52GiB / 11.67GiB    55.89%    463kB / 108kB   0B / 4.1kB       37
0274f99bc760   email-organiser-protonmail-bridge-1   0.00%     132.5MiB / 11.67GiB   1.11%     480kB / 161kB   140MB / 1.27MB   21
```

### Start the app

Before the first start, copy `.env.example` to `.env` and replace
`POSTGRES_PASSWORD` with a strong password. If `.env` already exists, add the
PostgreSQL settings to it instead. `.env` is excluded from Git.

```bash
./start.sh
```

### PostgreSQL

To start only the database and wait for it to accept connections:

```bash
docker compose up -d --wait postgres
```

PostgreSQL 18 initializes the database and user configured in `.env`.
It is available to local scripts at `127.0.0.1` on `POSTGRES_PORT` (`5432` in
`.env.example`) and other Compose services at `postgres:5432`. Data is persisted
in the `postgres_data` named volume. The separate host port avoids conflicting
with an existing local PostgreSQL installation.

Database, user, and password initialization settings apply only when the data
volume is empty. Changing `.env` later does not change an existing database's
credentials.

Install the database dependencies in your active virtual environment and create
the application tables:

```bash
python -m pip install -r requirements.txt
python init_db.py
```

`init_db.py` reads `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` from
`.env`, with existing environment variables taking precedence. Optional
`POSTGRES_HOST` and `POSTGRES_PORT` default to `127.0.0.1` and `5432` if omitted.
For a client in another Compose service, override its connection settings to
`POSTGRES_HOST=postgres` and `POSTGRES_PORT=5432` (the container's internal port).

The SQLAlchemy models are defined in `models.py`:

| Table         | Contents                                                                                                                                        |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `emails`      | Account, mailbox, UIDVALIDITY, UID, optional Message-ID, subject, sender, original Date header, decoded body, and fetch timestamp.              |
| `email_tasks` | Email foreign key, status (`pending`, `processing`, `completed`, `failed`), last error, and creation/start/completion timestamps.               |
| `results`     | Email and task foreign keys, predicted sender type, explanation, model, prompt SHA-256 hash, execution time in seconds, and creation timestamp. |

An email's account/mailbox/UIDVALIDITY/UID combination is unique. Each task has
at most one result; a result's email must match its task's email. New tasks may
classify an existing email again. The `date` column preserves the original Date
header as text, while processing timestamps use timezone-aware database types.

The initializer creates missing tables and leaves existing tables and rows
untouched. It does not migrate existing schemas; use migrations for future
schema changes. The collector stores emails and pending tasks; classification
from the database queue is a separate step.

### Run the collector

Set `BRIDGE_USERNAME` and `BRIDGE_PASSWORD` in `.env` alongside the PostgreSQL
settings, then run:

```bash
python collector_worker.py
```

The collector runs immediately, then waits 600 seconds between cycles. It
collects up to 50 new unread emails per cycle. Stored mailbox identities are
skipped before fetching bodies and before applying the limit. The reader leaves
messages unread and returns decoded bodies without HTML processing.

For each email, the collector runs `HTML_parser` as a separate processing step,
then saves the parsed email and its pending task in one database transaction.
It commits before fetching the next message. Repeated collection does not create
duplicate emails or tasks. Cycle failures are logged before waiting for the next
cycle. Stop with Ctrl+C. No CLI options are defined.

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
Optional arguments are `--prompt`, `--model`, `--ollama-url`, and `--timeout`.
The per-email request timeout defaults to 900 seconds (15 minutes). For example:

```bash
python3 classify_emails.py --dataset data/datasets/development_emails.json --timeout 1800
```

Each invocation
saves timestamped `*_predictions.json` and `*_accuracy.json` files under
`data/results/`. Each prediction is written and flushed to disk as soon as its
email finishes, with a progress line printed in the terminal. The predictions
file remains a JSON array and is readable between record updates. Completed
records are preserved if a later model request fails or you press Ctrl+C.
The accuracy report is generated only after the full dataset finishes;
partial output is not scored as a complete run. The CLI prints the output paths
and the final accuracy summary. Previous
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
modified. Calling `classify_emails()` directly does not save output unless you
provide an `on_result` callback; the CLI uses that callback to save incrementally.

### Measure prediction accuracy

To score an existing predictions file without calling Ollama:

```bash
python3 calculate_accuracy.py --input data/results/example_predictions.json --reference data/datasets/development_emails.json
```

The command writes a timestamped accuracy report under `data/results` and prints
the score. Both files must contain exactly the same email IDs. Human labels come
from the reference file's `expected.sender_type`; null labels are excluded from
the accuracy calculation.

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

### Learnings

- Use datasets and wilson interval to determine the result accuracy range
- Use separate datasets (development and testing) to avoid bias.
- Define function/module boundaries for AI and only use it to fill in the function logic, instead of telling it one purpose and leave it inventing things all over the place.
- Set resources limits on the AI model to prevent it consuming all of the computing resources.
- Cached prompt size enables the AI model to cache the same part of the prompts, reducing requests latency. However, if it accumlates too much, it may memory kill the container based on the assigned memory capacity. Set Cached prompt size to a reasonable number according to your application use case.
