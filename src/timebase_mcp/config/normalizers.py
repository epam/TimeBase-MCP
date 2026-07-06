import json


def normalize_log_level(value: object) -> object:
    if isinstance(value, str):
        return value.upper()
    return value


def normalize_oauth2_scope(value: object) -> object:
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


def normalize_required_scopes(value: object) -> object:
    """Accept a space/comma-delimited string or list and return a list[str]|None."""
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
        tokens = [token for token in value.replace(",", " ").split() if token]
        return tokens or None

    if isinstance(value, list | tuple):
        tokens = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Scope values must be strings.")
            tokens.extend(token for token in item.replace(",", " ").split() if token)
        return tokens or None

    raise ValueError("Scope values must be a string or a list of strings.")
