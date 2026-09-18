"""Keep complete distinct timing records across bounded collection checkpoints."""
import json


def merge_jsonl(path, incoming):
    records = {}
    sources = [path.read_text() if path.exists() else '', incoming]
    for source in sources:
        for line in source.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # A bounded tail can begin inside its first record.
                continue
            key = json.dumps(record, sort_keys=True)
            records[key] = record
    ordered = sorted(records.values(), key=lambda r: r.get('timestamp', ''))
    path.write_text(''.join(json.dumps(r) + '\n' for r in ordered))
