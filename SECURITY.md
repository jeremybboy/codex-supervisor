# Security

Codex Supervisor reads local coding-agent activity that may contain sensitive paths, commands, or source excerpts. It binds the dashboard to `127.0.0.1`, keeps derived state in memory by default, and must never transmit activity unless the user explicitly enables a configured interpreter.

Do not report vulnerabilities through public issues when they contain sensitive data. Use GitHub private vulnerability reporting after repository publication.
