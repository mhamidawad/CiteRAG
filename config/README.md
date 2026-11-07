# CiteRAG local configuration

Mount this folder read-only into the container only after reviewing file contents. Do not commit real configuration, API keys, private session data or environment files. This folder currently contains no runtime configuration files. Generation is disabled by default unless deliberately configured in a private server environment.

The Docker Compose template is **unbuilt and untested** and its health checks are liveness probes, not authenticated integration acceptance.
