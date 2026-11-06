"""JSON storage used by the local order desk."""

import json
from pathlib import Path


class JsonStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if self.path.exists():
            with self.path.open(encoding="utf-8") as stream:
                return json.load(stream)
        catalog_path = Path(__file__).with_name("catalog.json")
        with catalog_path.open(encoding="utf-8") as stream:
            catalog = json.load(stream)
        return {
            "schema_version": 1,
            "next_order_number": 1,
            "catalog": catalog,
            "orders": [],
        }

    def save(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2)
            stream.write("\n")
