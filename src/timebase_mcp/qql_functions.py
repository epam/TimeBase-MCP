from datetime import datetime, timezone
from itertools import zip_longest
from typing import Any, Literal

from timebase_mcp.models import QQLFunctionGroup

QQLFunctionKind = Literal["stateless", "stateful"]
QQL_FUNCTIONS_FIELD = "FUNCS"


def normalize_qql_functions(
    kind: QQLFunctionKind,
    messages: list[dict[str, Any]],
) -> list[QQLFunctionGroup]:
    signatures_by_id: dict[str, set[str]] = {}
    display_id_by_key: dict[str, str] = {}

    for function_payload in _iter_qql_function_payloads(messages):
        function_id = _coerce_optional_string(
            _first_present(
                function_payload,
                "id",
                "ID",
            )
        )
        if function_id is None:
            raise ValueError("TimeBase returned QQL function metadata without an id.")

        function_key = function_id.casefold()
        display_id_by_key.setdefault(function_key, function_id)
        signatures_by_id.setdefault(function_key, set()).add(
            _format_qql_function_signature(function_id, kind, function_payload)
        )

    return [
        QQLFunctionGroup(
            id=display_id_by_key[function_key],
            signatures=sorted(signatures_by_id[function_key]),
            overload_count=len(signatures_by_id[function_key]),
        )
        for function_key in sorted(display_id_by_key)
    ]


def _iter_qql_function_payloads(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for message in messages:
        wrapped_functions = _first_present(message, QQL_FUNCTIONS_FIELD)
        for function_payload in _coerce_dict_list(wrapped_functions):
            payloads.append(function_payload)

    return payloads


def _format_qql_function_signature(
    function_id: str,
    kind: QQLFunctionKind,
    function_payload: dict[str, Any],
) -> str:
    arguments = _format_qql_arguments(_extract_qql_arguments(function_payload))
    return_type = _format_qql_type(
        _first_present(function_payload, "returnType", "RETURN_TYPE", "return_type")
    )
    return_type_text = return_type or "UNKNOWN"

    if kind == "stateful":
        init_arguments = _format_qql_arguments(
            _extract_qql_arguments(
                function_payload,
                key_names=("initArguments", "INIT_ARGUMENTS", "init_arguments"),
                include_defaults=True,
            )
        )
        return f"{function_id}{{{init_arguments}}}({arguments}) -> {return_type_text}"

    return f"{function_id}({arguments}) -> {return_type_text}"


def _extract_qql_arguments(
    function_payload: dict[str, Any],
    *,
    key_names: tuple[str, ...] = ("arguments", "ARGUMENTS"),
    include_defaults: bool = False,
) -> list[dict[str, str | None]]:
    raw_arguments = _first_present(function_payload, *key_names)
    if raw_arguments is not None:
        return [
            _normalize_qql_argument(argument, include_defaults=include_defaults)
            for argument in _coerce_dict_list(raw_arguments)
        ]

    if include_defaults:
        return []

    argument_names = _coerce_string_list(
        _first_present(
            function_payload,
            "argument_names",
            "ARGUMENT_NAMES",
            "arguments_name",
            "ARGUMENTS_NAME",
        )
    )
    argument_types = _coerce_string_list(
        _first_present(
            function_payload,
            "argument_data_types",
            "ARGUMENT_DATA_TYPES",
            "arguments_datatype_basename",
            "ARGUMENTS_DATATYPE_BASENAME",
            "data_type",
            "DATA_TYPE",
            "baseName",
            "BASENAME",
        )
    )
    return [
        {"name": name, "type": data_type, "default": None}
        for name, data_type in zip_longest(argument_names, argument_types)
    ]


def _normalize_qql_argument(
    argument: dict[str, Any],
    *,
    include_defaults: bool,
) -> dict[str, str | None]:
    default_value = None
    if include_defaults:
        default_value = _coerce_optional_string(
            _first_present(argument, "defaultValue", "DEFAULT_VALUE", "default")
        )
    return {
        "name": _coerce_optional_string(_first_present(argument, "name", "NAME")),
        "type": _format_qql_type(
            _first_present(argument, "dataType", "DATA_TYPE", "data_type")
        ),
        "default": default_value,
    }


def _format_qql_arguments(arguments: list[dict[str, str | None]]) -> str:
    rendered_arguments: list[str] = []
    for argument in arguments:
        argument_name = argument.get("name") or "ARG"
        argument_type = argument.get("type") or "UNKNOWN"
        rendered_argument = f"{argument_name}: {argument_type}"
        default_value = argument.get("default")
        if default_value is not None:
            rendered_argument = f"{rendered_argument} = {default_value}"
        rendered_arguments.append(rendered_argument)
    return ", ".join(rendered_arguments)


def _format_qql_type(data_type: Any) -> str | None:
    if data_type is None:
        return None
    if isinstance(data_type, str):
        return data_type
    if not isinstance(data_type, dict):
        return _coerce_optional_string(data_type)

    base_name = _coerce_optional_string(
        _first_present(data_type, "baseName", "BASE_NAME", "base_name")
    )
    encoding = _coerce_optional_string(
        _first_present(data_type, "encoding", "ENCODING")
    )
    is_nullable = _first_present(data_type, "isNullable", "IS_NULLABLE")

    if base_name == "ARRAY":
        element_type = _format_qql_type(
            _first_present(data_type, "elementType", "ELEMENT_TYPE", "element_type")
        )
        type_text = f"ARRAY<{element_type or 'UNKNOWN'}>"
    elif base_name == "OBJECT":
        type_text = _format_qql_object_type(data_type)
    else:
        type_text = base_name or _format_qql_object_type(data_type)
        if encoding is not None:
            type_text = f"{type_text}({encoding})"

    if is_nullable is True:
        type_text = f"{type_text}?"
    return type_text


def _format_qql_object_type(data_type: dict[str, Any]) -> str:
    descriptors = _first_present(
        data_type,
        "typeDescriptors",
        "TYPE_DESCRIPTORS",
        "type_descriptors",
    )
    descriptor_names = [
        _short_type_name(descriptor.get("name"))
        for descriptor in _coerce_dict_list(descriptors)
        if descriptor.get("name") is not None
    ]
    if not descriptor_names:
        type_name = _coerce_optional_string(
            _first_present(data_type, "typeName", "TYPE_NAME", "type_name")
        )
        return _short_type_name(type_name) if type_name else "OBJECT"
    if len(descriptor_names) == 1:
        return descriptor_names[0]
    return "OBJECT<" + " | ".join(descriptor_names) + ">"


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]

    normalized_payload = {key.casefold(): value for key, value in payload.items()}
    for key in keys:
        normalized_key = key.casefold()
        if normalized_key in normalized_payload:
            return normalized_payload[normalized_key]

    return None


def _coerce_string_list(value: Any) -> list[str | None]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [_coerce_optional_string(item) for item in value]
    return [_coerce_optional_string(value)]


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)):
        value = [value]

    result: list[dict[str, Any]] = []
    for item in value:
        normalized_item = _json_safe_value(item)
        if isinstance(normalized_item, dict):
            result.append(normalized_item)
    return result


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _short_type_name(type_name: str | None) -> str:
    if not type_name:
        return "UNKNOWN"
    return type_name.rsplit(".", 1)[-1]


def _json_safe_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in payload.items()}


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]

    value_to_dict = getattr(value, "to_dict", None)
    if callable(value_to_dict):
        raw_value = value_to_dict()
        if isinstance(raw_value, dict):
            return _json_safe_value(raw_value)

    value_vars = getattr(value, "__dict__", None)
    if isinstance(value_vars, dict):
        return _json_safe_value(value_vars)

    return str(value)
