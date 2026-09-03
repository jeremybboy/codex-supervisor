# Architecture

Codex Supervisor is a local observer with four boundaries:

1. **Discovery** identifies coding-agent tasks and their existing local event sources.
2. **Adapter** converts agent-specific records into commentary, final response, tool invocation, tool result, build milestone, test result, or watcher error.
3. **Interpreter** deterministically deduplicates and classifies evidence. An optional local-model pass may summarize a bounded batch, but cannot override explicit waiting-for-user evidence.
4. **Presentation** serves an in-memory state snapshot to a local browser dashboard.

The observer does not write to watched projects, respond to worker agents, approve actions, or create a copied activity log. Raw hidden reasoning and encrypted model content are deliberately ignored.

## Adapter contract

An adapter provides task identity, objective metadata when available, and a chronological stream of externally visible records. It must fail visibly when its source schema is unsupported. Codex rollout JSONL is the first adapter source and is explicitly considered unstable.
