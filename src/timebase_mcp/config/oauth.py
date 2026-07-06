from pydantic import SecretStr

from timebase_mcp.config.types import OutboundAuthMode

OAUTH2_CONFIG_FIELDS = (
    "tb_oauth2_token_url",
    "tb_oauth2_client_id",
    "tb_oauth2_client_secret",
    "tb_oauth2_scope",
    "tb_oauth2_token_params",
)
OAUTH2_REQUIRED_FIELDS = OAUTH2_CONFIG_FIELDS[:3]
OAUTH2_SERVICE_EVIDENCE_FIELDS = (
    "tb_oauth2_token_url",
    "tb_oauth2_client_secret",
    "tb_oauth2_token_params",
)
OAUTH2_INTERACTIVE_FORBIDDEN_FIELDS = (
    "tb_oauth2_token_url",
    "tb_oauth2_client_secret",
    "tb_oauth2_token_params",
)


def infer_outbound_auth_mode(
    *,
    username: str | None,
    password: SecretStr | None,
    oauth2_service_evidence_present: bool,
) -> OutboundAuthMode:
    if oauth2_service_evidence_present:
        return "oauth2_client_credentials"
    if username is not None or password is not None:
        return "basic"
    return "auto"


def oauth2_fields_present(source: object, fields: tuple[str, ...]) -> bool:
    return any(getattr(source, field_name) is not None for field_name in fields)
