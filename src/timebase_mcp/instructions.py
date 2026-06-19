"""MCP server instructions exposed to clients on initialize."""

SERVER_INSTRUCTIONS = """\
TimeBase MCP connects to configured TimeBase instances. Use list_timebase_instances
when choosing between configured instances; pass the chosen name as the optional
instance_key argument for each TB operation. In single-instance setups, omit it.

Before querying: discover streams, read schema, then check time range and symbols.
Sample messages only when you need raw examples.

For QQL: Always use the QQL generator skill, when it is available in the workspace.
Otherwise, use compile_query first, then execute_query with a small limit.
execute_query can be expensive, so keep queries narrow.

A running MCP process does not guarantee TimeBase is reachable; use
get_server_configuration and client logs if tool calls fail.
"""
