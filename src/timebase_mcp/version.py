from importlib import metadata

_DIST_NAME = "timebase-mcp"


def get_version() -> str:
    try:
        return metadata.version(_DIST_NAME)
    except metadata.PackageNotFoundError:
        return "unknown"
