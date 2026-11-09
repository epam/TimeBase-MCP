import pytest

from timebase_mcp.auth.scopes import is_scope_token


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("mcp.access", True),
        ("https://mcp.example.com/mcp/mcp.access", True),
        ("!#[]~", True),
        ("", False),
        (" mcp.access", False),
        ("mcp.access ", False),
        ("mcp.access other", False),
        ("mcp.access\tother", False),
        ("mcp.access\n", False),
        ("mcp.access\x00", False),
        ("mcp.access\x7f", False),
        ('mcp."access', False),
        ("mcp.\\access", False),
        ("mcp.acc\u00e9ss", False),
    ],
)
def test_scope_token_character_rules(value: str, expected: bool) -> None:
    assert is_scope_token(value) is expected
