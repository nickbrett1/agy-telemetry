# agy-telemetry

A lightweight, robust telemetry integration for the Google Antigravity (`agy`) CLI that exports chat logs, metadata, and tool executions as OpenTelemetry traces to an [Arize Phoenix](https://github.com/Arize-ai/phoenix) telemetry server.

This tool captures conversations, model responses, token usage, and tool execution logs, formatting them to adhere to the standard **OpenInference** semantic conventions. This allows you to analyze conversation latency, trace agent loops, and determine which chats or tasks are expensive to help optimize your usage of Google Antigravity.

---

## Features

- **Automated Trace Correlation:** Converts each `agy` conversation (identified by a UUID) into a single Trace ID, grouping all agent steps and tool calls under a single trace.
- **OpenInference Compliance:** Maps prompts, model completions, token counts, and tool inputs/outputs to standard OpenInference attributes (like `llm.input_messages`, `llm.token_count.total`, and `tool.name`).
- **Nested Agent Spans:** Groups LLM inference calls and tool executions chronologically as child spans of the main conversation chain.
- **Duplicate Prevention Cache:** Caches previously exported step indexes in a temporary directory (e.g., `/tmp` on macOS/Linux, or `%TEMP%` on Windows) so that only new steps and updated root tokens are pushed on each statusline refresh, minimizing network overhead.
- **Fail-safe Design:** Telemetry runs completely out-of-band and will never crash or interrupt your interactive `agy` session, even if the Phoenix server is offline.

---

## Quick Installation

To install this telemetry hook on your development boxes:

### macOS / Linux / Dev Containers
Run this command in your terminal:
```bash
curl -fsSL https://raw.githubusercontent.com/nickbrett1/agy-telemetry/main/install.py | python3
```

### Windows
Run this command in your command prompt or terminal (using `python` instead of `python3`):
```cmd
curl -fsSL https://raw.githubusercontent.com/nickbrett1/agy-telemetry/main/install.py | python
```

This installer script will:
1. Locate your local `settings.json` directory (`~/.gemini/antigravity-cli/`).
2. Download the `statusline.py` telemetry hook.
3. Install the required OpenTelemetry SDK dependencies in a separate isolated directory (`~/.gemini/antigravity-cli/telemetry_lib`) to avoid polluting your system packages or virtual environments.
4. Configure your `settings.json` to route your statusline updates through the python telemetry hook.

---

## Configuration

By default, the script sends OTLP traces to `http://nas:6006/v1/traces`.

If your Phoenix server runs on a different host, port, or cloud instance, you can override this endpoint by setting the `PHOENIX_COLLECTOR_ENDPOINT` environment variable in your shell configuration (e.g., `.bashrc`, `.zshrc`):

```bash
export PHOENIX_COLLECTOR_ENDPOINT="http://localhost:6006/v1/traces"
```

---

## File Structure

- `scripts/statusline.py`: The custom statusline script that reads stdin, parses the conversation transcript, constructs OpenTelemetry spans, and exports them.
- `install.py`: The cross-platform installer script.
- `pyproject.toml`: The standard python project configuration.
