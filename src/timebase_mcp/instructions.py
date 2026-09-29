"""MCP server instructions advertised via server/discover and result metadata."""

SERVER_INSTRUCTIONS = """\
TimeBase MCP connects to configured TimeBase instances. Use list_timebase_instances
when choosing between configured instances; pass the chosen name as the
instance_key argument for each TB operation. In multi-instance setups,
instance_key is required. In single-instance setups, omit it.

Instances reported as read_only accept SELECT queries only, every other
statement is rejected before it reaches TimeBase.

Some tools have limited TimeBase server versions support.
Don't assume everything is available on the specific instance.

Before querying: discover streams, read schema, then check time range and symbols.
Sample messages only when you need raw examples.

Use WebAdmin tools only for views, topics, background tasks, and existing
order-book validation reports; prefer native TimeBase tools for stream data.

For QQL: Always use the QQL generator skill, when it is available in the workspace.
Otherwise, use compile_query first, then execute_query with a small limit.
execute_query can be expensive, so keep queries narrow.

When diagnosing an error or unexpected log output, use search_logs_kb with the
error text, stack trace, or a short log excerpt before suggesting a fix. The
tool searches bundled TimeBase troubleshooting cases. Treat a match as a lead
and confirm it against the current logs, configuration, and product version.

A running MCP process does not guarantee TimeBase is reachable; use
get_server_configuration and client logs if tool calls fail.
"""
