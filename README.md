<p align="center"><img src="assets/banner.svg" alt="openapi-diff banner" width="100%"/></p>

# openapi-diff

[![CI](https://github.com/gravion-ux/openapi-diff/actions/workflows/ci.yml/badge.svg)](https://github.com/gravion-ux/openapi-diff/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**OpenAPI 3.x breaking-change differ with CI-friendly exit codes.**

Compare two OpenAPI JSON specs and get every change classified as **breaking**, **non-breaking**, or **info**, each with a location and a reason. Local `$ref` pointers (`#/components/...`) are resolved, so schemas are compared by their effective shape, not by reference name.

## Install

```bash
pip install -e .
```

Requires Python >= 3.11.

## Usage

```bash
openapi-diff old.json new.json
openapi-diff old.json new.json --format json
openapi-diff old.json new.json --output report.txt
openapi-diff old.json new.json --no-fail   # report only, always exit 0
python -m openapi_diff old.json new.json
```

### Exit codes

| Code | Meaning |
| ---- | ------- |
| `0`  | No breaking changes (or breaking changes found with `--no-fail`) |
| `1`  | Breaking changes found (default `--fail-on-breaking` behaviour) |
| `2`  | Usage or parse error (missing file, invalid JSON, not an OpenAPI doc) |

## What it detects

| Change | Classification |
| ------ | -------------- |
| Path removed / operation removed | breaking |
| Path added / operation added | non-breaking |
| Parameter removed | breaking |
| Required parameter added | breaking |
| Optional parameter added | non-breaking |
| Parameter became required | breaking |
| Parameter became optional | non-breaking |
| Parameter type / format changed | breaking |
| Request body became required / required body added | breaking |
| New required request property / property became required | breaking |
| Response status code removed | breaking |
| Response status code added | non-breaking |
| Response schema property removed / type changed | breaking |
| Response property no longer guaranteed (required → optional) | breaking |
| Property added (request or response, optional) | non-breaking |
| Enum value removed | breaking |
| Enum value added | info |

Schemas nested in objects and arrays are compared recursively, including schemas reached through `$ref` and shallow `allOf` composition.

## Example output

```text
$ openapi-diff old.json new.json
OpenAPI diff report
===================
Summary: 4 change(s) - 3 breaking, 1 non-breaking, 0 info

BREAKING (3):
  [BREAKING] parameter_became_required at GET /pets parameter limit (query): parameter 'limit' (query) became required
      Reason: Requests that omit this parameter are now rejected.
  [BREAKING] response_property_removed at GET /pets response 200.name: property 'name' removed
      Reason: Clients may read this property from responses.
  [BREAKING] response_status_removed at GET /pets response 404: response status 404 removed
      Reason: Clients handling this status code will no longer see it documented.

NON-BREAKING (1):
  [NON-BREAKING] path_added at /owners: path '/owners' added
      Reason: Existing clients are unaffected by an additional path.

Result: BREAKING CHANGES FOUND
$ echo $?
1
```

With `--format json` the report is machine-readable:

```json
{
  "has_breaking": true,
  "summary": {
    "total": 4,
    "breaking": 3,
    "non_breaking": 1,
    "info": 0,
    "by_kind": {
      "parameter_became_required": 1,
      "path_added": 1,
      "response_property_removed": 1,
      "response_status_removed": 1
    }
  },
  "changes": [
    {
      "kind": "parameter_became_required",
      "severity": "breaking",
      "location": "GET /pets parameter limit (query)",
      "message": "parameter 'limit' (query) became required",
      "reason": "Requests that omit this parameter are now rejected."
    }
  ]
}
```

## CI usage

Fail a pull request when a spec change breaks existing clients:

```yaml
- name: Check for breaking API changes
  run: |
    pip install -e .
    openapi-diff baseline/openapi.json openapi.json --format json --output openapi-diff.json
```

The step fails (exit `1`) exactly when breaking changes are found. Use `--no-fail` for a report-only step that never blocks the build.

## Python API

```python
from openapi_diff import compare_specs

result = compare_specs(old_spec_dict, new_spec_dict)
print(result.has_breaking)
print(result.summary)
for change in result.changes:
    print(change.severity, change.kind, change.location, change.message)
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
```

## License

MIT — see [LICENSE](LICENSE).
