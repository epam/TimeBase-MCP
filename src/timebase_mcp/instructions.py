"""MCP server instructions exposed to clients on initialize."""

SERVER_INSTRUCTIONS = """\
TimeBase MCP connects to the TimeBase instance configured via TIMEBASE_URL and related
auth environment variables.

Before querying: discover streams, read schema, then check time range and symbols.
Sample messages only when you need raw examples.

For QQL: Always use the QQL generator skill, when it is available in the workspace.
Otherwise, use compile_query first, then execute_query with a small limit.
execute_query can be expensive, so keep queries narrow.

A running MCP process does not guarantee TimeBase is reachable; use
get_server_configuration and client logs if tool calls fail.
"""
