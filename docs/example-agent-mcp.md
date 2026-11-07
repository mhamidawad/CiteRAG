# Local MCP agent configuration example

CiteRAG currently exposes `rag_search` over streamable HTTP. A separately verified Python MCP ClientSession has called it on an isolated localhost port.

A generic MCP client may use a URL such as `http://127.0.0.1:18761/mcp` **only when both client and server are on the same trusted machine**. Refer to that client's current documentation for its configuration schema; no generic JSON here is asserted to be valid for OpenCode, Continue, or other coding agents.

Never bind this unauthenticated development endpoint to public interfaces. An authenticated remote configuration is not yet available.
