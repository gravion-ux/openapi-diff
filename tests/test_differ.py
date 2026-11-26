"""Tests for openapi_diff.differ using inline fixture spec dicts."""

import copy

import pytest

from openapi_diff.differ import compare_specs, deref, resolve_ref


def base_spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Pet API", "version": "1.0.0"},
        "paths": {
            "/pets": {
                "get": {
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "format": "int32"},
                        },
                        {
                            "name": "status",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["available", "pending", "sold"],
                            },
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            },
                        },
                        "404": {"description": "not found"},
                    },
                },
                "post": {
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "tag": {"type": "string"},
                                    },
                                    "required": ["name"],
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "created"}},
                },
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "format": "int64"},
                        "name": {"type": "string"},
                        "state": {
                            "type": "string",
                            "enum": ["available", "pending", "sold"],
                        },
                    },
                    "required": ["id", "name"],
                }
            }
        },
    }


def kinds(result):
    return [c.kind for c in result.changes]


def get_op(spec, method="get", path="/pets"):
    return spec["paths"][path][method]


def test_identical_specs_have_no_changes():
    spec = base_spec()
    result = compare_specs(spec, copy.deepcopy(spec))
    assert result.changes == []
    assert result.has_breaking is False
    assert result.summary["total"] == 0


def test_removed_path_is_breaking():
    old = base_spec()
    new = base_spec()
    new["paths"] = {}
    result = compare_specs(old, new)
    assert "path_removed" in kinds(result)
    assert result.has_breaking is True


def test_added_path_is_non_breaking():
    old = base_spec()
    new = base_spec()
    new["paths"]["/owners"] = {"get": {"responses": {"200": {"description": "ok"}}}}
    result = compare_specs(old, new)
    assert "path_added" in kinds(result)
    assert result.has_breaking is False


def test_removed_operation_is_breaking_and_added_is_not():
    old = base_spec()
    new = base_spec()
    del new["paths"]["/pets"]["post"]
    new["paths"]["/pets"]["delete"] = {"responses": {"204": {"description": "gone"}}}
    result = compare_specs(old, new)
    assert "operation_removed" in kinds(result)
    assert "operation_added" in kinds(result)
    assert result.has_breaking is True


def test_parameter_removed_and_optional_added():
    old = base_spec()
    new = base_spec()
    params = get_op(new)["parameters"]
    params[:] = [p for p in params if p["name"] != "status"]
    params.append(
        {"name": "offset", "in": "query", "required": False, "schema": {"type": "integer"}}
    )
    result = compare_specs(old, new)
    assert "parameter_removed" in kinds(result)
    assert "parameter_added" in kinds(result)


def test_required_parameter_added_is_breaking():
    old = base_spec()
    new = base_spec()
    get_op(new)["parameters"].append(
        {"name": "tenant", "in": "header", "required": True, "schema": {"type": "string"}}
    )
    result = compare_specs(old, new)
    assert "required_parameter_added" in kinds(result)
    assert result.has_breaking is True


def test_parameter_became_required_is_breaking():
    old = base_spec()
    new = base_spec()
    get_op(new)["parameters"][0]["required"] = True
    result = compare_specs(old, new)
    assert "parameter_became_required" in kinds(result)
    assert result.has_breaking is True


def test_parameter_became_optional_is_non_breaking():
    old = base_spec()
    get_op(old)["parameters"][0]["required"] = True
    new = base_spec()
    result = compare_specs(old, new)
    assert "parameter_became_optional" in kinds(result)
    assert result.has_breaking is False


def test_parameter_type_change_is_breaking():
    old = base_spec()
    new = base_spec()
    get_op(new)["parameters"][0]["schema"] = {"type": "string"}
    result = compare_specs(old, new)
    assert "parameter_type_changed" in kinds(result)
    assert result.has_breaking is True


def test_parameter_format_change_is_breaking():
    old = base_spec()
    new = base_spec()
    get_op(new)["parameters"][0]["schema"]["format"] = "int64"
    result = compare_specs(old, new)
    assert "schema_format_changed" in kinds(result)
    assert result.has_breaking is True


def test_enum_value_removed_from_parameter_is_breaking():
    old = base_spec()
    new = base_spec()
    get_op(new)["parameters"][1]["schema"]["enum"] = ["available", "sold"]
    result = compare_specs(old, new)
    assert "enum_value_removed" in kinds(result)
    assert result.has_breaking is True


def test_enum_constraint_added_to_parameter_is_breaking():
    old = base_spec()
    del get_op(old)["parameters"][1]["schema"]["enum"]
    new = base_spec()
    result = compare_specs(old, new)
    change = next(c for c in result.changes if c.kind == "enum_constraint_added")
    assert change.severity == "breaking"
    assert result.has_breaking is True


def test_enum_constraint_added_to_response_is_info():
    old = base_spec()
    del old["components"]["schemas"]["Pet"]["properties"]["state"]["enum"]
    new = base_spec()
    result = compare_specs(old, new)
    change = next(c for c in result.changes if c.kind == "enum_constraint_added")
    assert change.severity == "info"
    assert result.has_breaking is False


def test_request_body_became_required_is_breaking():
    old = base_spec()
    new = base_spec()
    get_op(new, "post")["requestBody"]["required"] = True
    result = compare_specs(old, new)
    assert "request_body_became_required" in kinds(result)
    assert result.has_breaking is True


def test_new_required_request_property_is_breaking():
    old = base_spec()
    new = base_spec()
    schema = get_op(new, "post")["requestBody"]["content"]["application/json"]["schema"]
    schema["properties"]["chip_id"] = {"type": "string"}
    schema["required"] = ["name", "chip_id"]
    result = compare_specs(old, new)
    assert "request_required_property_added" in kinds(result)
    assert result.has_breaking is True


def test_request_property_became_required_is_breaking():
    old = base_spec()
    new = base_spec()
    schema = get_op(new, "post")["requestBody"]["content"]["application/json"]["schema"]
    schema["required"] = ["name", "tag"]
    result = compare_specs(old, new)
    assert "request_property_became_required" in kinds(result)


def test_optional_request_property_added_is_non_breaking():
    old = base_spec()
    new = base_spec()
    schema = get_op(new, "post")["requestBody"]["content"]["application/json"]["schema"]
    schema["properties"]["nickname"] = {"type": "string"}
    result = compare_specs(old, new)
    assert "request_property_added" in kinds(result)
    assert result.has_breaking is False


def test_response_status_removed_is_breaking():
    old = base_spec()
    new = base_spec()
    del get_op(new)["responses"]["404"]
    result = compare_specs(old, new)
    assert "response_status_removed" in kinds(result)
    assert result.has_breaking is True


def test_response_property_removed_via_ref_is_breaking():
    old = base_spec()
    new = base_spec()
    del new["components"]["schemas"]["Pet"]["properties"]["name"]
    result = compare_specs(old, new)
    assert "response_property_removed" in kinds(result)
    assert result.has_breaking is True


def test_response_property_type_change_via_ref_is_breaking():
    old = base_spec()
    new = base_spec()
    new["components"]["schemas"]["Pet"]["properties"]["id"] = {"type": "string"}
    result = compare_specs(old, new)
    assert "schema_type_changed" in kinds(result)
    assert result.has_breaking is True


def test_response_property_added_is_non_breaking():
    old = base_spec()
    new = base_spec()
    new["components"]["schemas"]["Pet"]["properties"]["age"] = {"type": "integer"}
    result = compare_specs(old, new)
    assert "response_property_added" in kinds(result)
    assert result.has_breaking is False


def test_response_enum_value_removed_is_breaking():
    old = base_spec()
    new = base_spec()
    new["components"]["schemas"]["Pet"]["properties"]["state"]["enum"] = ["available"]
    result = compare_specs(old, new)
    assert "enum_value_removed" in kinds(result)
    assert result.has_breaking is True


def test_ref_resolution_helpers():
    spec = base_spec()
    pet = resolve_ref(spec, "#/components/schemas/Pet")
    assert pet["properties"]["id"]["type"] == "integer"
    assert deref(spec, {"$ref": "#/components/schemas/Pet"}) == pet
    assert resolve_ref(spec, "#/components/schemas/Missing") == {}
    assert resolve_ref(spec, "https://example.com/pet.json") == {}


def test_ref_named_differently_but_same_shape_has_no_changes():
    old = base_spec()
    new = base_spec()
    pet = new["components"]["schemas"].pop("Pet")
    new["components"]["schemas"]["Animal"] = pet
    schema = get_op(new)["responses"]["200"]["content"]["application/json"]["schema"]
    schema["$ref"] = "#/components/schemas/Animal"
    result = compare_specs(old, new)
    assert result.changes == []


def test_summary_counts_and_change_shape():
    old = base_spec()
    new = base_spec()
    del get_op(new)["responses"]["404"]
    new["paths"]["/owners"] = {"get": {"responses": {"200": {"description": "ok"}}}}
    result = compare_specs(old, new)
    summary = result.summary
    assert summary["total"] == len(result.changes)
    assert summary["breaking"] == 1
    assert summary["non_breaking"] == 1
    assert summary["by_kind"]["response_status_removed"] == 1
    for change in result.changes:
        as_dict = change.to_dict()
        assert set(as_dict) == {"kind", "severity", "location", "message", "reason"}
        assert as_dict["reason"]


@pytest.mark.parametrize("severity", ["breaking", "non-breaking", "info"])
def test_severities_are_from_known_set(severity):
    # Guard: every emitted severity must be one of the documented values.
    old = base_spec()
    new = base_spec()
    new["components"]["schemas"]["Pet"]["properties"]["state"]["enum"].append("adopted")
    result = compare_specs(old, new)
    assert all(c.severity in {"breaking", "non-breaking", "info"} for c in result.changes)
    assert severity in {"breaking", "non-breaking", "info"}
