import json


def normalize_log_level(value: object) -> object:
    if isinstance(value, str):
        return value.upper()
    return value


def normalize_oauth2_scope(value: object) -> str | None:
    if value in (None, ""):
        return None

    if isinstance(value, str):
        normalized_scope = " ".join(value.split())
        return normalized_scope or None

    if isinstance(value, list | tuple):
        normalized_scopes: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(
                    "TIMEBASE_OAUTH2_SCOPE must be a string or a list of strings."
                )
            normalized_scopes.extend(part for part in item.split() if part)

        return " ".join(normalized_scopes) or None

    raise ValueError("TIMEBASE_OAUTH2_SCOPE must be a string or a list of strings.")


def normalize_oauth2_token_params(value: object) -> object:
    if value in (None, ""):
        return None

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "TIMEBASE_OAUTH2_TOKEN_PARAMS must be valid JSON."
            ) from exc

    if not isinstance(value, dict):
        raise ValueError(
            "TIMEBASE_OAUTH2_TOKEN_PARAMS must be a JSON object with string keys and values."
        )

    normalized_params: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(
                "TIMEBASE_OAUTH2_TOKEN_PARAMS must be a JSON object with string keys and values."
            )
        normalized_params[key] = item

    return normalized_params


def normalize_string_list(value: object, *, error_message: str) -> list[str] | None:
    """Accept a space/comma-delimited string, JSON array string, or list of either.

    Returns a ``list[str]`` of the individual tokens, or ``None`` when empty.
    """
    if value in (None, ""):
        return None

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        else:
            if isinstance(parsed, list):
                value = parsed
            else:
                value = str(parsed)

    if isinstance(value, str):
        return _split_tokens(value) or None

    if isinstance(value, list | tuple):
        tokens: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(error_message)
            tokens.extend(_split_tokens(item))
        return tokens or None

    raise ValueError(error_message)


def _split_tokens(value: str) -> list[str]:
    return [token for token in value.replace(",", " ").split() if token]
