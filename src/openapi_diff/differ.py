"""Core OpenAPI 3.x comparison logic.

Compares two parsed OpenAPI documents (plain ``dict`` objects loaded from
JSON) and produces a list of classified changes. Local ``$ref`` pointers
(``#/components/...`` and any other ``#/`` JSON pointer) are resolved
against the document that owns them, so schemas living in ``components``
are compared by their effective shape rather than by reference name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

SEVERITY_BREAKING = "breaking"
SEVERITY_NON_BREAKING = "non-breaking"
SEVERITY_INFO = "info"


@dataclass
class Change:
    """A single detected difference between two specs."""

    kind: str
    severity: str
    location: str
    message: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "location": self.location,
            "message": self.message,
            "reason": self.reason,
        }


@dataclass
class DiffResult:
    """The full result of comparing two specs."""

    changes: list[Change] = field(default_factory=list)

    @property
    def has_breaking(self) -> bool:
        return any(c.severity == SEVERITY_BREAKING for c in self.changes)

    @property
    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        counts = {SEVERITY_BREAKING: 0, SEVERITY_NON_BREAKING: 0, SEVERITY_INFO: 0}
        for change in self.changes:
            counts[change.severity] = counts.get(change.severity, 0) + 1
            by_kind[change.kind] = by_kind.get(change.kind, 0) + 1
        return {
            "total": len(self.changes),
            "breaking": counts[SEVERITY_BREAKING],
            "non_breaking": counts[SEVERITY_NON_BREAKING],
            "info": counts[SEVERITY_INFO],
            "by_kind": dict(sorted(by_kind.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_breaking": self.has_breaking,
            "summary": self.summary,
            "changes": [c.to_dict() for c in self.changes],
        }


# ---------------------------------------------------------------------------
# $ref resolution
# ---------------------------------------------------------------------------


def resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a local ``#/`` JSON-pointer reference against ``spec``.

    Returns an empty dict when the reference is external, malformed, or
    points at a non-object node.
    """
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return {}
    node: Any = spec
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return {}
        node = node[part]
    return node if isinstance(node, dict) else {}


def deref(spec: dict[str, Any], node: Any) -> dict[str, Any]:
    """Follow a ``$ref`` chain and return the effective object.

    Sibling keys next to ``$ref`` (allowed in OpenAPI 3.1) override the
    referenced object. Cycles terminate by returning the last node seen.
    """
    if not isinstance(node, dict):
        return {}
    seen: set[str] = set()
    current: dict[str, Any] = node
    while isinstance(current.get("$ref"), str):
        ref = current["$ref"]
        if ref in seen:
            break
        seen.add(ref)
        resolved = resolve_ref(spec, ref)
        if not resolved:
            break
        siblings = {k: v for k, v in current.items() if k != "$ref"}
        current = {**resolved, **siblings}
    return current


def _effective_schema(spec: dict[str, Any], schema: Any) -> dict[str, Any]:
    """Deref a schema and shallow-merge any ``allOf`` members."""
    schema = deref(spec, schema)
    if not schema:
        return {}
    all_of = schema.get("allOf")
    if not isinstance(all_of, list):
        return schema
    merged: dict[str, Any] = {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for member in all_of:
        member_eff = _effective_schema(spec, member)
        for key, value in member_eff.items():
            if key == "properties" and isinstance(value, dict):
                properties.update(value)
            elif key == "required" and isinstance(value, list):
                required.extend(v for v in value if v not in required)
            elif key != "allOf":
                merged[key] = value
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            properties.update(value)
        elif key == "required" and isinstance(value, list):
            required.extend(v for v in value if v not in required)
        elif key != "allOf":
            merged[key] = value
    if properties:
        merged["properties"] = properties
    if required:
        merged["required"] = required
    return merged


# ---------------------------------------------------------------------------
# Schema comparison
# ---------------------------------------------------------------------------


def _enum_values(schema: dict[str, Any]) -> list[Any] | None:
    enum = schema.get("enum")
    return enum if isinstance(enum, list) else None


def _compare_schemas(
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
    old_schema: Any,
    new_schema: Any,
    location: str,
    context: str,
    changes: list[Change],
) -> None:
    """Recursively compare two schemas.

    ``context`` is ``"request"``, ``"response"`` or ``"parameter"`` and
    decides how property additions/removals and required-flag flips are
    classified.
    """
    old = _effective_schema(old_spec, old_schema)
    new = _effective_schema(new_spec, new_schema)
    if not old and not new:
        return

    # Type changes.
    old_type = old.get("type")
    new_type = new.get("type")
    if old_type is not None and new_type is not None and old_type != new_type:
        changes.append(
            Change(
                kind="schema_type_changed",
                severity=SEVERITY_BREAKING,
                location=location,
                message=f"type changed from {old_type!r} to {new_type!r}",
                reason="Clients serialising or deserialising the old type will fail.",
            )
        )
        return

    # Format changes.
    old_format = old.get("format")
    new_format = new.get("format")
    if old_format != new_format and (old_format is not None or new_format is not None):
        changes.append(
            Change(
                kind="schema_format_changed",
                severity=SEVERITY_BREAKING,
                location=location,
                message=f"format changed from {old_format!r} to {new_format!r}",
                reason="Values valid under the old format may be rejected or misread.",
            )
        )

    # Enum changes.
    old_enum = _enum_values(old)
    new_enum = _enum_values(new)
    if old_enum is not None and new_enum is not None:
        for value in old_enum:
            if value not in new_enum:
                changes.append(
                    Change(
                        kind="enum_value_removed",
                        severity=SEVERITY_BREAKING,
                        location=location,
                        message=f"enum value {value!r} removed",
                        reason="Clients may send or expect the removed enum value.",
                    )
                )
        for value in new_enum:
            if value not in old_enum:
                changes.append(
                    Change(
                        kind="enum_value_added",
                        severity=SEVERITY_INFO,
                        location=location,
                        message=f"enum value {value!r} added",
                        reason="Existing clients keep working, but may not handle the new value.",
                    )
                )
    elif old_enum is not None and new_enum is None:
        changes.append(
            Change(
                kind="enum_removed",
                severity=SEVERITY_INFO,
                location=location,
                message="enum constraint removed",
                reason="The value set widened; existing clients keep working.",
            )
        )

    # Array items.
    if isinstance(old.get("items"), dict) and isinstance(new.get("items"), dict):
        _compare_schemas(
            old_spec, new_spec, old["items"], new["items"],
            f"{location}.items", context, changes,
        )

    # Object properties.
    old_props = old.get("properties") if isinstance(old.get("properties"), dict) else {}
    new_props = new.get("properties") if isinstance(new.get("properties"), dict) else {}
    old_required = set(old.get("required") or [])
    new_required = set(new.get("required") or [])

    for name in sorted(old_props):
        prop_loc = f"{location}.{name}"
        if name not in new_props:
            changes.append(
                Change(
                    kind=f"{context}_property_removed",
                    severity=SEVERITY_BREAKING,
                    location=prop_loc,
                    message=f"property '{name}' removed",
                    reason=(
                        "Clients may read this property from responses."
                        if context == "response"
                        else "Clients may send this property; the contract narrowed."
                    ),
                )
            )
            continue
        was_required = name in old_required
        is_required = name in new_required
        if context in ("request", "parameter"):
            if is_required and not was_required:
                changes.append(
                    Change(
                        kind=f"{context}_property_became_required",
                        severity=SEVERITY_BREAKING,
                        location=prop_loc,
                        message=f"property '{name}' became required",
                        reason="Requests that omit this property are now rejected.",
                    )
                )
            elif was_required and not is_required:
                changes.append(
                    Change(
                        kind=f"{context}_property_became_optional",
                        severity=SEVERITY_NON_BREAKING,
                        location=prop_loc,
                        message=f"property '{name}' became optional",
                        reason="Requests that already send this property keep working.",
                    )
                )
        elif context == "response":
            if was_required and not is_required:
                changes.append(
                    Change(
                        kind="response_property_became_optional",
                        severity=SEVERITY_BREAKING,
                        location=prop_loc,
                        message=f"response property '{name}' is no longer guaranteed",
                        reason="Clients may rely on this property always being present.",
                    )
                )
        _compare_schemas(
            old_spec, new_spec, old_props[name], new_props[name],
            prop_loc, context, changes,
        )

    for name in sorted(new_props):
        if name in old_props:
            continue
        prop_loc = f"{location}.{name}"
        if context in ("request", "parameter") and name in new_required:
            changes.append(
                Change(
                    kind=f"{context}_required_property_added",
                    severity=SEVERITY_BREAKING,
                    location=prop_loc,
                    message=f"required property '{name}' added",
                    reason="Existing requests do not send this property and will be rejected.",
                )
            )
        else:
            changes.append(
                Change(
                    kind=f"{context}_property_added",
                    severity=SEVERITY_NON_BREAKING,
                    location=prop_loc,
                    message=f"property '{name}' added",
                    reason="Existing clients are unaffected by an additional property.",
                )
            )


# ---------------------------------------------------------------------------
# Operation comparison
# ---------------------------------------------------------------------------


def _parameters_by_key(
    spec: dict[str, Any], path_item: dict[str, Any], operation: dict[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Merge path-item and operation parameters, keyed by (name, in)."""
    params: dict[tuple[str, str], dict[str, Any]] = {}
    for source in (path_item.get("parameters"), operation.get("parameters")):
        if not isinstance(source, list):
            continue
        for raw in source:
            param = deref(spec, raw)
            name = param.get("name")
            where = param.get("in")
            if isinstance(name, str) and isinstance(where, str):
                params[(name, where)] = param
    return params


def _compare_parameters(
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
    old_path_item: dict[str, Any],
    new_path_item: dict[str, Any],
    old_op: dict[str, Any],
    new_op: dict[str, Any],
    location: str,
    changes: list[Change],
) -> None:
    old_params = _parameters_by_key(old_spec, old_path_item, old_op)
    new_params = _parameters_by_key(new_spec, new_path_item, new_op)

    for key in sorted(old_params):
        name, where = key
        param_loc = f"{location} parameter {name} ({where})"
        if key not in new_params:
            changes.append(
                Change(
                    kind="parameter_removed",
                    severity=SEVERITY_BREAKING,
                    location=param_loc,
                    message=f"parameter '{name}' ({where}) removed",
                    reason="Clients may send this parameter; the contract narrowed.",
                )
            )
            continue
        old_param = old_params[key]
        new_param = new_params[key]
        was_required = bool(old_param.get("required", False))
        is_required = bool(new_param.get("required", False))
        if is_required and not was_required:
            changes.append(
                Change(
                    kind="parameter_became_required",
                    severity=SEVERITY_BREAKING,
                    location=param_loc,
                    message=f"parameter '{name}' ({where}) became required",
                    reason="Requests that omit this parameter are now rejected.",
                )
            )
        elif was_required and not is_required:
            changes.append(
                Change(
                    kind="parameter_became_optional",
                    severity=SEVERITY_NON_BREAKING,
                    location=param_loc,
                    message=f"parameter '{name}' ({where}) became optional",
                    reason="Requests that already send this parameter keep working.",
                )
            )
        old_schema = _effective_schema(old_spec, old_param.get("schema"))
        new_schema = _effective_schema(new_spec, new_param.get("schema"))
        if old_schema.get("type") != new_schema.get("type") and (
            old_schema.get("type") is not None and new_schema.get("type") is not None
        ):
            changes.append(
                Change(
                    kind="parameter_type_changed",
                    severity=SEVERITY_BREAKING,
                    location=param_loc,
                    message=(
                        f"parameter '{name}' type changed from "
                        f"{old_schema.get('type')!r} to {new_schema.get('type')!r}"
                    ),
                    reason="Clients sending the old type will be rejected or misread.",
                )
            )
        else:
            _compare_schemas(
                old_spec, new_spec, old_param.get("schema"), new_param.get("schema"),
                param_loc, "parameter", changes,
            )

    for key in sorted(new_params):
        if key in old_params:
            continue
        name, where = key
        param_loc = f"{location} parameter {name} ({where})"
        if bool(new_params[key].get("required", False)):
            changes.append(
                Change(
                    kind="required_parameter_added",
                    severity=SEVERITY_BREAKING,
                    location=param_loc,
                    message=f"required parameter '{name}' ({where}) added",
                    reason="Existing requests do not send this parameter and will be rejected.",
                )
            )
        else:
            changes.append(
                Change(
                    kind="parameter_added",
                    severity=SEVERITY_NON_BREAKING,
                    location=param_loc,
                    message=f"optional parameter '{name}' ({where}) added",
                    reason="Existing requests remain valid without this parameter.",
                )
            )


def _body_schema(spec: dict[str, Any], container: dict[str, Any]) -> Any:
    """Return the JSON (or first) content schema of a body/response object."""
    content = container.get("content")
    if not isinstance(content, dict) or not content:
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        media = next(iter(content.values()), None)
    if isinstance(media, dict):
        return media.get("schema")
    return None


def _compare_request_body(
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
    old_op: dict[str, Any],
    new_op: dict[str, Any],
    location: str,
    changes: list[Change],
) -> None:
    old_body = deref(old_spec, old_op.get("requestBody")) if "requestBody" in old_op else {}
    new_body = deref(new_spec, new_op.get("requestBody")) if "requestBody" in new_op else {}
    body_loc = f"{location} requestBody"

    if old_body and not new_body:
        changes.append(
            Change(
                kind="request_body_removed",
                severity=SEVERITY_BREAKING,
                location=body_loc,
                message="request body removed",
                reason="Clients sending a body may be rejected or ignored.",
            )
        )
        return
    if new_body and not old_body:
        if bool(new_body.get("required", False)):
            changes.append(
                Change(
                    kind="request_body_became_required",
                    severity=SEVERITY_BREAKING,
                    location=body_loc,
                    message="a required request body was added",
                    reason="Existing requests send no body and will be rejected.",
                )
            )
        else:
            changes.append(
                Change(
                    kind="request_body_added",
                    severity=SEVERITY_NON_BREAKING,
                    location=body_loc,
                    message="an optional request body was added",
                    reason="Existing requests remain valid without a body.",
                )
            )
        return
    if not old_body and not new_body:
        return

    was_required = bool(old_body.get("required", False))
    is_required = bool(new_body.get("required", False))
    if is_required and not was_required:
        changes.append(
            Change(
                kind="request_body_became_required",
                severity=SEVERITY_BREAKING,
                location=body_loc,
                message="request body became required",
                reason="Requests without a body are now rejected.",
            )
        )
    elif was_required and not is_required:
        changes.append(
            Change(
                kind="request_body_became_optional",
                severity=SEVERITY_NON_BREAKING,
                location=body_loc,
                message="request body became optional",
                reason="Requests that already send a body keep working.",
            )
        )

    _compare_schemas(
        old_spec, new_spec, _body_schema(old_spec, old_body),
        _body_schema(new_spec, new_body), body_loc, "request", changes,
    )


def _compare_responses(
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
    old_op: dict[str, Any],
    new_op: dict[str, Any],
    location: str,
    changes: list[Change],
) -> None:
    old_responses = old_op.get("responses") if isinstance(old_op.get("responses"), dict) else {}
    new_responses = new_op.get("responses") if isinstance(new_op.get("responses"), dict) else {}

    for status in sorted(old_responses):
        resp_loc = f"{location} response {status}"
        if status not in new_responses:
            changes.append(
                Change(
                    kind="response_status_removed",
                    severity=SEVERITY_BREAKING,
                    location=resp_loc,
                    message=f"response status {status} removed",
                    reason="Clients handling this status code will no longer see it documented.",
                )
            )
            continue
        old_resp = deref(old_spec, old_responses[status])
        new_resp = deref(new_spec, new_responses[status])
        _compare_schemas(
            old_spec, new_spec, _body_schema(old_spec, old_resp),
            _body_schema(new_spec, new_resp), resp_loc, "response", changes,
        )

    for status in sorted(new_responses):
        if status not in old_responses:
            changes.append(
                Change(
                    kind="response_status_added",
                    severity=SEVERITY_NON_BREAKING,
                    location=f"{location} response {status}",
                    message=f"response status {status} added",
                    reason="Existing clients are unaffected by an additional status code.",
                )
            )


def _compare_operation(
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
    old_path_item: dict[str, Any],
    new_path_item: dict[str, Any],
    old_op: dict[str, Any],
    new_op: dict[str, Any],
    location: str,
    changes: list[Change],
) -> None:
    _compare_parameters(
        old_spec, new_spec, old_path_item, new_path_item, old_op, new_op, location, changes
    )
    _compare_request_body(old_spec, new_spec, old_op, new_op, location, changes)
    _compare_responses(old_spec, new_spec, old_op, new_op, location, changes)


# ---------------------------------------------------------------------------
# Top-level comparison
# ---------------------------------------------------------------------------


def compare_specs(old: dict[str, Any], new: dict[str, Any]) -> DiffResult:
    """Compare two OpenAPI documents and return a :class:`DiffResult`."""
    changes: list[Change] = []
    old_paths = old.get("paths") if isinstance(old.get("paths"), dict) else {}
    new_paths = new.get("paths") if isinstance(new.get("paths"), dict) else {}

    for path in sorted(old_paths):
        if path not in new_paths:
            changes.append(
                Change(
                    kind="path_removed",
                    severity=SEVERITY_BREAKING,
                    location=path,
                    message=f"path '{path}' removed",
                    reason="Clients calling this path will receive 404 responses.",
                )
            )
    for path in sorted(new_paths):
        if path not in old_paths:
            changes.append(
                Change(
                    kind="path_added",
                    severity=SEVERITY_NON_BREAKING,
                    location=path,
                    message=f"path '{path}' added",
                    reason="Existing clients are unaffected by an additional path.",
                )
            )

    for path in sorted(set(old_paths) & set(new_paths)):
        old_item = deref(old, old_paths[path])
        new_item = deref(new, new_paths[path])
        for method in HTTP_METHODS:
            location = f"{method.upper()} {path}"
            old_op = old_item.get(method)
            new_op = new_item.get(method)
            if isinstance(old_op, dict) and not isinstance(new_op, dict):
                changes.append(
                    Change(
                        kind="operation_removed",
                        severity=SEVERITY_BREAKING,
                        location=location,
                        message=f"operation {location} removed",
                        reason="Clients calling this operation will receive 404/405 responses.",
                    )
                )
            elif isinstance(new_op, dict) and not isinstance(old_op, dict):
                changes.append(
                    Change(
                        kind="operation_added",
                        severity=SEVERITY_NON_BREAKING,
                        location=location,
                        message=f"operation {location} added",
                        reason="Existing clients are unaffected by an additional operation.",
                    )
                )
            elif isinstance(old_op, dict) and isinstance(new_op, dict):
                _compare_operation(
                    old, new, old_item, new_item, old_op, new_op, location, changes
                )

    severity_order = {SEVERITY_BREAKING: 0, SEVERITY_NON_BREAKING: 1, SEVERITY_INFO: 2}
    changes.sort(key=lambda c: (severity_order.get(c.severity, 3), c.location, c.kind))
    return DiffResult(changes=changes)
