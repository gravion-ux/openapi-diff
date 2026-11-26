"""CLI tests: exit codes, report formats, error handling."""

import json

from test_differ import base_spec

from openapi_diff.cli import main
from openapi_diff.differ import compare_specs
from openapi_diff.report import render_json, render_text


def write_spec(tmp_path, name, spec):
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def breaking_pair(tmp_path):
    old = base_spec()
    new = base_spec()
    del new["paths"]["/pets"]["get"]["responses"]["404"]
    return write_spec(tmp_path, "old.json", old), write_spec(tmp_path, "new.json", new)


def test_exit_code_0_when_no_breaking_changes(tmp_path, capsys):
    old = write_spec(tmp_path, "old.json", base_spec())
    new = write_spec(tmp_path, "new.json", base_spec())
    assert main([old, new]) == 0
    assert "No changes detected" in capsys.readouterr().out


def test_exit_code_1_when_breaking_changes(tmp_path):
    old, new = breaking_pair(tmp_path)
    assert main([old, new]) == 1


def test_no_fail_flag_returns_0_despite_breaking(tmp_path):
    old, new = breaking_pair(tmp_path)
    assert main([old, new, "--no-fail"]) == 0


def test_fail_on_breaking_flag_returns_1(tmp_path):
    old, new = breaking_pair(tmp_path)
    assert main([old, new, "--fail-on-breaking"]) == 1


def test_exit_code_2_on_missing_file(tmp_path):
    new = write_spec(tmp_path, "new.json", base_spec())
    assert main([str(tmp_path / "missing.json"), new]) == 2


def test_exit_code_2_on_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    new = write_spec(tmp_path, "new.json", base_spec())
    assert main([str(bad), new]) == 2


def test_exit_code_2_on_non_openapi_json(tmp_path):
    bad = write_spec(tmp_path, "bad.json", {"hello": "world"})
    new = write_spec(tmp_path, "new.json", base_spec())
    assert main([bad, new]) == 2


def test_json_report_shape(tmp_path, capsys):
    old, new = breaking_pair(tmp_path)
    assert main([old, new, "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["has_breaking"] is True
    assert set(payload["summary"]) == {"total", "breaking", "non_breaking", "info", "by_kind"}
    assert payload["summary"]["breaking"] >= 1
    assert payload["changes"]
    for change in payload["changes"]:
        assert set(change) == {"kind", "severity", "location", "message", "reason"}


def test_output_file(tmp_path, capsys):
    old, new = breaking_pair(tmp_path)
    out = tmp_path / "report.txt"
    assert main([old, new, "--output", str(out)]) == 1
    assert capsys.readouterr().out == ""
    assert "BREAKING" in out.read_text(encoding="utf-8")


def test_render_helpers():
    old = base_spec()
    new = base_spec()
    new["paths"] = {}
    result = compare_specs(old, new)
    text = render_text(result)
    assert "path_removed" in text
    assert "BREAKING CHANGES FOUND" in text
    payload = json.loads(render_json(result))
    assert payload["has_breaking"] is True
    assert payload["summary"]["by_kind"]["path_removed"] == 1
