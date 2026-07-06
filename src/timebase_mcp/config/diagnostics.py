from pydantic.fields import FieldInfo

from timebase_mcp.config.urls import extract_timebase_url_credentials

SECRET_FIELDS = frozenset({"tb_password", "tb_oauth2_client_secret"})

REDACTED_SECRET_VALUE = "**********"


def field_env_name(field_name: str, field_info: FieldInfo) -> str:
    validation_alias = field_info.validation_alias
    if validation_alias is None:
        return field_name

    if isinstance(validation_alias, str):
        return validation_alias

    raise TypeError(
        f"MCPSettings field {field_name!r} must use a string validation_alias."
    )


def redact_log_payload(payload: dict[str, object]) -> dict[str, object]:
    for secret_field in SECRET_FIELDS:
        if payload.get(secret_field) is not None:
            payload[secret_field] = REDACTED_SECRET_VALUE

    return payload


def sanitize_env_log_payload(payload: dict[str, object]) -> dict[str, object]:
    tb_url = payload.get("tb_url")
    if isinstance(tb_url, str):
        sanitized_tb_url, extracted_username, extracted_password = (
            extract_timebase_url_credentials(tb_url)
        )
        payload["tb_url"] = sanitized_tb_url

        if payload.get("tb_username") is None and extracted_username is not None:
            payload["tb_username"] = extracted_username

        if payload.get("tb_password") is None and extracted_password is not None:
            payload["tb_password"] = REDACTED_SECRET_VALUE

    if payload.get("servers"):
        payload["servers"] = REDACTED_SECRET_VALUE

    return redact_log_payload(payload)
