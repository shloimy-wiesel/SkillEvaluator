"""Print the golden CLI inventory with the evidence registered by Studio slices."""

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory(node, command="root"):
    yield command, {}
    for param in node["params"]:
        yield f"{command}:{param['name']}", param
    for name, child in node.get("commands", {}).items():
        yield from inventory(child, name if command == "root" else f"{command} {name}")
    if "workflow" in node:
        yield from inventory(node["workflow"], f"{command} [workflow]")


def audit():
    studio = ROOT / "studio"
    manifest = json.loads((studio / "cli-contract.json").read_text())
    golden = (studio / manifest["source"]).read_bytes()
    if hashlib.sha256(golden).hexdigest() != manifest["surface_sha256"]:
        raise ValueError("CLI golden changed: review affected bindings and update surface_sha256.")
    rows = {key: {"status": "remaining", "contract": contract} for key, contract in inventory(json.loads(golden))}
    for file in sorted((studio / "bindings").glob("*.json")):
        for binding in json.loads(file.read_text()):
            key, status = binding["key"], binding["status"]
            if key not in rows or rows[key]["status"] != "remaining":
                raise ValueError(f"Unknown or duplicate binding: {key}")
            if status not in ("implemented", "partial") or not binding["equivalent"].strip():
                raise ValueError(f"Missing coverage explanation for {key}")
            path, name = binding["evidence"].split("::")
            source = (ROOT / path).resolve()
            if (
                not source.is_relative_to(ROOT / "tests")
                or not name.startswith("test_")
                or not any(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
                    for node in ast.parse(source.read_text()).body
                )
            ):
                raise ValueError(f"Missing behavioral test for {key}: {binding['evidence']}")
            rows[key].update(status=status, equivalent=binding["equivalent"], evidence=binding["evidence"])
    return rows


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))  # noqa: T201 -- report on stdout
