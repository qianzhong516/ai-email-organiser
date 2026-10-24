import json
from pathlib import Path

from html_parser import HTML_parser


# Parses each saved email body and writes the results to the snapshot JSON file
# in the same order as the input. Running this function updates the snapshot.
def test_html_parser():
    tests_folder = Path(__file__).resolve().parent
    fixture = tests_folder / "fixtures" / "email_bodies.json"
    snapshot = tests_folder / "snapshots" / "email_bodies.json"

    bodies = json.loads(fixture.read_text(encoding="utf-8"))
    if not isinstance(bodies, list) or not all(isinstance(body, str) for body in bodies):
        raise ValueError("The fixture must be an array of email body strings")

    results = [HTML_parser(body) for body in bodies]
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Saved {len(results)} parsed email bodies to {snapshot}")


if __name__ == "__main__":
    test_html_parser()
