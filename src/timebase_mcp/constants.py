APP_NAME = "TimeBase MCP Server"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_TIMEBASE_URL = "dxtick://localhost:8011"
DEFAULT_TRANSPORT = "stdio"

DEFAULT_INSTANCE_KEY = "default"

# Pool key used for all connection modes that share a single TimeBase identity
# (``none`` / ``basic`` / ``oauth2_client_credentials`` / ``interactive``). Only
# ``forward_identity`` partitions an instance's pool per authenticated principal.
SHARED_PRINCIPAL_KEY = "__shared__"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"})
