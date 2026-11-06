def is_scope_token(value: str) -> bool:
    """RFC 6749 scope token"""
    return (
        bool(value)
        and value.isascii()
        and value.isprintable()
        and not any(char in value for char in (" ", '"', "\\"))
    )
