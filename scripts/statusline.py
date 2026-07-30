import sys
import json
import os
import datetime
import hashlib
import time
import socket
import urllib.parse


# Prepend custom telemetry lib path containing OpenTelemetry SDK
lib_path = os.path.expanduser("~/.gemini/antigravity-cli/telemetry_lib")
if os.path.exists(lib_path) and lib_path not in sys.path:
    sys.path.insert(0, lib_path)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider, IdGenerator
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.trace import SpanContext, TraceFlags, NonRecordingSpan
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    class IdGenerator:
        pass


# Configurable telemetry endpoint
DEFAULT_ENDPOINT = "http://nas:6006/v1/traces"
ENDPOINT = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", DEFAULT_ENDPOINT)

class PresetIdGenerator(IdGenerator):
    def __init__(self):
        self.trace_id = None
        self.span_id = None
        
    def generate_trace_id(self) -> int:
        if self.trace_id is not None:
            return self.trace_id
        import secrets
        return secrets.randbits(128)
        
    def generate_span_id(self) -> int:
        if self.span_id is not None:
            return self.span_id
        import secrets
        return secrets.randbits(64)

def iso_to_nanos(iso_str):
    if not iso_str:
        return int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1e9)
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1e9)
    except Exception:
        return int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1e9)

def main():
    # Read CLI JSON state from stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except Exception:
        print("agy ✦ statusline")
        return

    # Extract info from CLI state
    conversation_id = input_data.get("conversation_id", "")
    session_id = input_data.get("session_id", conversation_id)
    raw_transcript_path = input_data.get("transcript_path", "")
    
    model_info = input_data.get("model") or {}
    model_name = model_info.get("display_name", "Gemini")
    
    context_window = input_data.get("context_window") or {}
    current_usage = context_window.get("current_usage") or {}
    input_tokens = current_usage.get("input_tokens") or context_window.get("total_input_tokens") or 0
    output_tokens = current_usage.get("output_tokens") or context_window.get("total_output_tokens") or 0
    used_percent = context_window.get("used_percentage") or 0.0
    workspace = input_data.get("workspace") or {}
    project_dir = workspace.get("project_dir", "")

    # Format standard status line
    status_str = f"agy ✦ {model_name} ┃ 📥 {input_tokens} ┃ 📤 {output_tokens} ┃ 📊 {used_percent:.2f}%"

    if not OTEL_AVAILABLE:
        print(f"{status_str} ┃ 📡 telemetry: dep_missing")
        return

    if not conversation_id or not raw_transcript_path:
        print(f"{status_str} ┃ 📡 telemetry: off")
        return

    # Resolve transcript path
    transcript_path = raw_transcript_path
    if not os.path.exists(transcript_path):
        alt_path = raw_transcript_path.replace("/.gemini/antigravity/", "/.gemini/antigravity-cli/")
        if os.path.exists(alt_path):
            transcript_path = alt_path

    if not os.path.exists(transcript_path):
        print(f"{status_str} ┃ 📡 telemetry: no_logs")
        return

    # Read cache to find last sent step
    secure_dir = os.path.expanduser("~/.gemini/antigravity-cli")
    os.makedirs(secure_dir, exist_ok=True)
    cache_path = os.path.join(secure_dir, "agy_telemetry_cache.json")
    error_log_path = os.path.join(secure_dir, "agy_telemetry_error.log")
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as cf:
                cache = json.load(cf)
        except Exception:
            pass
            
    try:
        input_tokens = int(input_tokens)
    except (TypeError, ValueError):
        input_tokens = 0
    try:
        output_tokens = int(output_tokens)
    except (TypeError, ValueError):
        output_tokens = 0

    last_sent_steps = cache.get("last_sent_steps") or {}
    last_sent_step = last_sent_steps.get(conversation_id, -1)
    last_tokens_info = (cache.get("last_token_counts") or {}).get(conversation_id) or {}
    last_input_tokens = last_tokens_info.get("input_tokens", 0)
    last_output_tokens = last_tokens_info.get("output_tokens", 0)
    try:
        last_input_tokens = int(last_input_tokens)
    except (TypeError, ValueError):
        last_input_tokens = 0
    try:
        last_output_tokens = int(last_output_tokens)
    except (TypeError, ValueError):
        last_output_tokens = 0

    delta_input = max(0, input_tokens - last_input_tokens)
    delta_output = max(0, output_tokens - last_output_tokens)

    # Check if telemetry is cached as offline
    offline_ts = cache.get("telemetry_offline_timestamp", 0)
    if time.time() - offline_ts < 30:
        print(f"{status_str} ┃ 📡 telemetry: offline")
        return

    # Check TCP connectivity to the Phoenix server in a background thread to prevent DNS hangs
    is_online = False
    def check_connection():
        nonlocal is_online
        try:
            parsed = urllib.parse.urlparse(ENDPOINT)
            host = parsed.hostname
            if not host:
                host = "localhost"
            port = parsed.port
            if port is None:
                port = 80 if parsed.scheme == "http" else 443
                
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)  # 200ms timeout
            s.connect((host, port))
            s.close()
            is_online = True
        except Exception:
            is_online = False

    import threading
    t = threading.Thread(target=check_connection)
    t.daemon = True
    t.start()
    t.join(timeout=0.2)
        
    if not is_online:
        # Update cache to avoid retrying for the next 30 seconds
        cache["telemetry_offline_timestamp"] = time.time()
        try:
            with open(cache_path, 'w') as cf:
                json.dump(cache, cf)
        except Exception:
            pass
        print(f"{status_str} ┃ 📡 telemetry: offline")
        return

    # Clean the offline timestamp from the cache if it is online
    if "telemetry_offline_timestamp" in cache:
        del cache["telemetry_offline_timestamp"]
        try:
            with open(cache_path, 'w') as cf:
                json.dump(cache, cf)
        except Exception:
            pass

    # Load transcript steps
    steps = []
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    steps.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        with open(error_log_path, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] File read error: {str(e)}\n")
        print(f"{status_str} ┃ 📡 telemetry: err")
        return

    if not steps:
        print(f"{status_str} ┃ 📡 telemetry: empty")
        return

    # Set up OpenTelemetry tracer
    try:
        resource = Resource(attributes={"service.name": "agy-cli"})
        id_generator = PresetIdGenerator()
        provider = TracerProvider(resource=resource, id_generator=id_generator)
        exporter = OTLPSpanExporter(endpoint=ENDPOINT, timeout=0.5)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer("agy-telemetry-statusline")

    except Exception as e:
        with open(error_log_path, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] OTel Init error: {str(e)}\n")
        print(f"{status_str} ┃ 📡 telemetry: offline")
        return

    # Convert UUIDs to integer OTel representations
    try:
        trace_id_hex = conversation_id.replace('-', '')
        root_span_id_hex = hashlib.sha256(conversation_id.encode()).hexdigest()[:16]
        
        trace_id_int = int(trace_id_hex, 16)
        root_span_id_int = int(root_span_id_hex, 16)
    except Exception as e:
        with open(error_log_path, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] UUID conversion error: {str(e)}\n")
        print(f"{status_str} ┃ 📡 telemetry: err")
        return

    first_step_time = iso_to_nanos(steps[0].get("created_at"))
    last_step_time = iso_to_nanos(steps[-1].get("created_at"))

    telemetry_status = "ok"
    try:
        # 1. Update/Send Root Chain Span
        id_generator.trace_id = trace_id_int
        id_generator.span_id = root_span_id_int
        
        # Find root input and output for CHAIN span
        root_input = ""
        root_output = ""
        for step in steps:
            if step.get("type") == "USER_INPUT":
                root_input = step.get("content", "")
                break
        if not root_input and steps:
            root_input = steps[0].get("content", "")

        for step in reversed(steps):
            if step.get("type") == "PLANNER_RESPONSE" or step.get("source") == "MODEL":
                root_output = step.get("content", "")
                break
        if not root_output and steps:
            root_output = steps[-1].get("content", "")

        if root_input is not None:
            root_input = str(root_input)
        if root_output is not None:
            root_output = str(root_output)

        root_span = tracer.start_span(
            name=f"Conversation: {conversation_id[:8]}",
            start_time=first_step_time
        )
        root_span.set_attribute("openinference.span.kind", "CHAIN")
        root_span.set_attribute("session_id", session_id)
        root_span.set_attribute("llm.model_name", model_name)
        root_span.set_attribute("llm.token_count.prompt", input_tokens)
        root_span.set_attribute("llm.token_count.completion", output_tokens)
        root_span.set_attribute("llm.token_count.total", input_tokens + output_tokens)
        root_span.set_attribute("workspace.project_dir", project_dir)
        root_span.set_attribute("input.value", root_input)
        root_span.set_attribute("output.value", root_output)
        root_span.set_attribute("input.mime_type", "text/plain")
        root_span.set_attribute("output.mime_type", "text/plain")

        # Set span error status if any step in the conversation failed
        root_status_error = any(step.get("status") == "ERROR" for step in steps)
        if root_status_error:
            root_span.set_status(trace.StatusCode.ERROR, description="Conversation contained step failures")

        root_span.end(end_time=last_step_time)

        # parent context helper for child spans
        parent_ctx = trace.set_span_in_context(
            NonRecordingSpan(
                SpanContext(
                    trace_id=trace_id_int,
                    span_id=root_span_id_int,
                    is_remote=False,
                    trace_flags=TraceFlags(TraceFlags.SAMPLED)
                )
            )
        )

        # 2. Send child spans for new steps
        last_user_input = None
        last_planner_response = None
        max_step_index = 0
        
        for i, step in enumerate(steps):
            stype = step.get("type")
            ssource = step.get("source")
            sindex = step.get("step_index")
            if sindex is not None and sindex > max_step_index:
                max_step_index = sindex
            scontent = step.get("content", "")
            stime = iso_to_nanos(step.get("created_at"))
            
            if stype == "USER_INPUT":
                last_user_input = step
            elif stype == "PLANNER_RESPONSE":
                last_planner_response = step
                
                if sindex > last_sent_step:
                    child_span_id_hex = hashlib.sha256(f"{conversation_id}_{sindex}".encode()).hexdigest()[:16]
                    child_span_id_int = int(child_span_id_hex, 16)
                    
                    id_generator.trace_id = trace_id_int
                    id_generator.span_id = child_span_id_int
                    
                    start_time = first_step_time
                    if last_user_input:
                        start_time = iso_to_nanos(last_user_input.get("created_at"))
                    else:
                        prev_idx = max(0, i - 1)
                        start_time = iso_to_nanos(steps[prev_idx].get("created_at"))
                        
                    child_span = tracer.start_span(
                        name="Model Inference",
                        context=parent_ctx,
                        start_time=start_time
                    )
                    child_span.set_attribute("openinference.span.kind", "LLM")
                    child_span.set_attribute("llm.model_name", model_name)
                    child_span.set_attribute("llm.provider", "google")
                    child_span.set_attribute("llm.token_count.prompt", delta_input)
                    child_span.set_attribute("llm.token_count.completion", delta_output)
                    child_span.set_attribute("llm.token_count.total", delta_input + delta_output)
                    child_span.set_attribute("llm.output_messages.0.message.role", "assistant")
                    child_span.set_attribute("llm.output_messages.0.message.content", scontent)
                    
                    ucontent = ""
                    if last_user_input:
                        ucontent = last_user_input.get("content", "")
                        child_span.set_attribute("llm.input_messages.0.message.role", "user")
                        child_span.set_attribute("llm.input_messages.0.message.content", ucontent)
                        
                    child_span.set_attribute("input.value", str(ucontent) if ucontent is not None else "")
                    child_span.set_attribute("output.value", str(scontent) if scontent is not None else "")
                    child_span.set_attribute("input.mime_type", "text/plain")
                    child_span.set_attribute("output.mime_type", "text/plain")

                    # Add invocation parameters if present in model info
                    invocation_params = {k: v for k, v in model_info.items() if k not in ["display_name", "model_id"]}
                    if invocation_params:
                        try:
                            child_span.set_attribute("llm.invocation_parameters", json.dumps(invocation_params))
                        except Exception:
                            pass

                    # Set error status if step failed
                    if step.get("status") == "ERROR":
                        child_span.set_status(trace.StatusCode.ERROR, description="LLM inference step failed")

                    child_span.end(end_time=stime)
                    
            elif ssource == "MODEL" and stype not in ["PLANNER_RESPONSE", "CHECKPOINT", "CONVERSATION_HISTORY"]:
                if sindex > last_sent_step:
                    child_span_id_hex = hashlib.sha256(f"{conversation_id}_{sindex}".encode()).hexdigest()[:16]
                    child_span_id_int = int(child_span_id_hex, 16)
                    
                    id_generator.trace_id = trace_id_int
                    id_generator.span_id = child_span_id_int
                    
                    prev_idx = max(0, i - 1)
                    start_time = iso_to_nanos(steps[prev_idx].get("created_at"))
                    
                    tool_span = tracer.start_span(
                        name=stype,
                        context=parent_ctx,
                        start_time=start_time
                    )
                    tool_span.set_attribute("openinference.span.kind", "TOOL")
                    tool_span.set_attribute("tool.name", stype.lower())
                    tool_span.set_attribute("tool.output", scontent)
                    
                    tool_input = ""
                    if last_planner_response:
                        for tc in last_planner_response.get("tool_calls", []):
                            if tc.get("name") == stype.lower() or tc.get("name") == stype:
                                tool_input = json.dumps(tc.get("args", {}))
                                break
                    tool_span.set_attribute("tool.input", tool_input)
                    tool_span.set_attribute("input.value", tool_input)
                    tool_span.set_attribute("output.value", str(scontent) if scontent is not None else "")
                    tool_span.set_attribute("input.mime_type", "application/json")
                    tool_span.set_attribute("output.mime_type", "text/plain")

                    # Set error status if step failed
                    if step.get("status") == "ERROR":
                        tool_span.set_status(trace.StatusCode.ERROR, description="Tool execution failed")

                    tool_span.end(end_time=stime)

        # Force flush and shutdown to ensure export
        provider.shutdown()
        
        # Update cache
        last_sent_steps[conversation_id] = max_step_index
        cache["last_sent_steps"] = last_sent_steps
        if "last_token_counts" not in cache:
            cache["last_token_counts"] = {}
        cache["last_token_counts"][conversation_id] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }
        with open(cache_path, 'w') as cf:
            json.dump(cache, cf)
            
    except Exception as e:
        telemetry_status = "offline"
        with open(error_log_path, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] Export error: {str(e)}\n")
        # Cache the failure to avoid blocking on subsequent prompts
        cache["telemetry_offline_timestamp"] = time.time()
        try:
            with open(cache_path, 'w') as cf:
                json.dump(cache, cf)
        except Exception:
            pass

    # Output formatted string for terminal TUI status line
    print(f"{status_str} ┃ 📡 telemetry: {telemetry_status}")

if __name__ == "__main__":
    main()
