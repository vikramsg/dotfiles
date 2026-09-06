# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "jsonschema==4.25.1",
# ]
# ///

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


def main() -> None:
    schema_path, instance_path = map(Path, sys.argv[1:3])
    schema = json.loads(schema_path.read_text())
    instance = json.loads(instance_path.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(instance)


if __name__ == "__main__":
    main()
