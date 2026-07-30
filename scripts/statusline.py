import sys
import json
import os
import datetime
import hashlib
import time
import socket
import urllib.parse
import threading

# Prepend custom telemetry lib path containing OpenTelemetry SDK
lib_path = os.path.expanduser("~/.gemini/antigravity-cli/telemetry_lib")
if os.path.exists(lib_path) and lib_path not in sys.path:
    sys.path.insert(0, lib_path)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider, IdGenerator
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
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

def read_input_data():
    try:
        return json.loads(sys.stdin.read())
    except Exception:
        return None

def extract_cli_state(input_data):
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


    try:
        input_tokens = int(input_tokens)
    except (TypeError, ValueError):
        input_tokens = 0
    try:
        output_tokens = int(output_tokens)
    except (TypeError, ValueError):
        output_tokens = 0

    return (conversation_id, session_id, raw_transcript_path, model_name, model_info,
            input_tokens, output_tokens, used_percent, project_dir)

def resolve_transcript_path(raw_transcript_path):
    transcript_path = raw_transcript_path
    if not os.path.exists(transcript_path):
        alt_path = raw_transcript_path.replace("/.gemini/antigravity/", "/.gemini/antigravity-cli/")
        if os.path.exists(alt_path):
            transcript_path = alt_path
    return transcript_path

def load_cache(cache_path):
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as cf:
                cache = json.load(cf)
        except Exception:
            pass
    return cache

def calculate_token_deltas(cache, conversation_id, input_tokens, output_tokens):
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
    return last_sent_step, delta_input, delta_output

def check_telemetry_online():
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
            s.settimeout(0.2)
            s.connect((host, port))
            s.close()
            is_online = True
        except Exception:
            is_online = False

    t = threading.Thread(target=check_connection)
    t.daemon = True
    t.start()
    t.join(timeout=0.2)
    return is_online

def load_transcript_steps(transcript_path):
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
        return None, str(e)
    return steps, None

def initialize_otel():
    resource = Resource(attributes={"service.name": "agy-cli"})
    id_generator = PresetIdGenerator()
    provider = TracerProvider(resource=resource, id_generator=id_generator)
    exporter = OTLPSpanExporter(endpoint=ENDPOINT, timeout=0.5)
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("agy-telemetry-statusline")
    return tracer, provider, id_generator

def get_root_input_output(steps):
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
    return root_input, root_output

def create_root_span(tracer, steps, conversation_id, session_id, model_name,
                     input_tokens, output_tokens, project_dir):
    first_step_time = iso_to_nanos(steps[0].get("created_at"))
    last_step_time = iso_to_nanos(steps[-1].get("created_at"))

    root_input, root_output = get_root_input_output(steps)

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

    root_status_error = any(step.get("status") == "ERROR" for step in steps)
    if root_status_error:
        root_span.set_status(trace.StatusCode.ERROR, description="Conversation contained step failures")

    root_span.end(end_time=last_step_time)
    return first_step_time

def process_child_span_llm(tracer, parent_ctx, id_generator, step, i, steps, conversation_id,
                          trace_id_int, first_step_time, model_name, model_info, delta_input, delta_output, last_user_input):
    sindex = step.get("step_index")
    scontent = step.get("content", "")
    stime = iso_to_nanos(step.get("created_at"))

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

    invocation_params = {k: v for k, v in model_info.items() if k not in ["display_name", "model_id"]}
    if invocation_params:
        try:
            child_span.set_attribute("llm.invocation_parameters", json.dumps(invocation_params))
        except Exception:
            pass

    if step.get("status") == "ERROR":
        child_span.set_status(trace.StatusCode.ERROR, description="LLM inference step failed")

    child_span.end(end_time=stime)

def process_child_span_tool(tracer, parent_ctx, id_generator, step, i, steps, conversation_id,
                           trace_id_int, stype, last_planner_response):
    sindex = step.get("step_index")
    scontent = step.get("content", "")
    stime = iso_to_nanos(step.get("created_at"))

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
    stype_lower = stype.lower()
    tool_span.set_attribute("openinference.span.kind", "TOOL")
    tool_span.set_attribute("tool.name", stype_lower)
    tool_span.set_attribute("tool.output", scontent)

    tool_input = ""
    if last_planner_response:
        for tc in last_planner_response.get("tool_calls", []):
            tc_name = tc.get("name")
            if tc_name == stype_lower or tc_name == stype:
                tool_input = json.dumps(tc.get("args", {}))
                break
    tool_span.set_attribute("tool.input", tool_input)
    tool_span.set_attribute("input.value", tool_input)
    tool_span.set_attribute("output.value", str(scontent) if scontent is not None else "")
    tool_span.set_attribute("input.mime_type", "application/json")
    tool_span.set_attribute("output.mime_type", "text/plain")

    if step.get("status") == "ERROR":
        tool_span.set_status(trace.StatusCode.ERROR, description="Tool execution failed")

    tool_span.end(end_time=stime)

def export_telemetry(steps, conversation_id, session_id, model_name, model_info,
                     input_tokens, output_tokens, project_dir, last_sent_step,
                     delta_input, delta_output):
    tracer, provider, id_generator = initialize_otel()

    trace_id_hex = conversation_id.replace('-', '')
    root_span_id_hex = hashlib.sha256(conversation_id.encode()).hexdigest()[:16]
    trace_id_int = int(trace_id_hex, 16)
    root_span_id_int = int(root_span_id_hex, 16)

    id_generator.trace_id = trace_id_int
    id_generator.span_id = root_span_id_int

    first_step_time = create_root_span(
        tracer, steps, conversation_id, session_id, model_name,
        input_tokens, output_tokens, project_dir
    )

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

    last_user_input = None
    last_planner_response = None
    max_step_index = 0

    for i, step in enumerate(steps):
        stype = step.get("type")
        ssource = step.get("source")
        sindex = step.get("step_index")
        if sindex is not None and sindex > max_step_index:
            max_step_index = sindex
        
        if stype == "USER_INPUT":
            last_user_input = step
        elif stype == "PLANNER_RESPONSE":
            last_planner_response = step
            if sindex is not None and sindex > last_sent_step:
                process_child_span_llm(
                    tracer, parent_ctx, id_generator, step, i, steps, conversation_id,
                    trace_id_int, first_step_time, model_name, model_info, delta_input, delta_output, last_user_input
                )
        elif ssource == "MODEL" and stype not in {"PLANNER_RESPONSE", "CHECKPOINT", "CONVERSATION_HISTORY"}:
            if sindex is not None and sindex > last_sent_step:
                process_child_span_tool(
                    tracer, parent_ctx, id_generator, step, i, steps, conversation_id,
                    trace_id_int, stype, last_planner_response
                )

    provider.shutdown()
    return max_step_index

def update_cache(cache, cache_path, conversation_id, max_step_index, input_tokens, output_tokens):
    last_sent_steps = cache.get("last_sent_steps", {})
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

def main():
    input_data = read_input_data()
    if input_data is None:
        print("agy ✦ statusline")
        return

    (conversation_id, session_id, raw_transcript_path, model_name, model_info,
     input_tokens, output_tokens, used_percent, project_dir) = extract_cli_state(input_data)

    status_str = f"agy ✦ {model_name} ┃ 📥 {input_tokens} ┃ 📤 {output_tokens} ┃ 📊 {used_percent:.2f}%"

    if not OTEL_AVAILABLE:
        print(f"{status_str} ┃ 📡 telemetry: dep_missing")
        return

    if not conversation_id or not raw_transcript_path:
        print(f"{status_str} ┃ 📡 telemetry: off")
        return

    transcript_path = resolve_transcript_path(raw_transcript_path)
    if not os.path.exists(transcript_path):
        print(f"{status_str} ┃ 📡 telemetry: no_logs")
        return

    secure_dir = os.path.expanduser("~/.gemini/antigravity-cli")
    os.makedirs(secure_dir, exist_ok=True)
    cache_path = os.path.join(secure_dir, "agy_telemetry_cache.json")
    error_log_path = os.path.join(secure_dir, "agy_telemetry_error.log")

    cache = load_cache(cache_path)

    last_sent_step, delta_input, delta_output = calculate_token_deltas(cache, conversation_id, input_tokens, output_tokens)

    offline_ts = cache.get("telemetry_offline_timestamp", 0)
    if time.time() - offline_ts < 30:
        print(f"{status_str} ┃ 📡 telemetry: offline")
        return

    is_online = check_telemetry_online()
    if not is_online:
        cache["telemetry_offline_timestamp"] = time.time()
        try:
            with open(cache_path, 'w') as cf:
                json.dump(cache, cf)
        except Exception:
            pass
        print(f"{status_str} ┃ 📡 telemetry: offline")
        return

    if "telemetry_offline_timestamp" in cache:
        del cache["telemetry_offline_timestamp"]
        try:
            with open(cache_path, 'w') as cf:
                json.dump(cache, cf)
        except Exception:
            pass

    steps, err = load_transcript_steps(transcript_path)
    if err:
        with open(error_log_path, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] File read error: {err}\n")
        print(f"{status_str} ┃ 📡 telemetry: err")
        return

    if not steps:
        print(f"{status_str} ┃ 📡 telemetry: empty")
        return

    telemetry_status = "ok"
    try:
        max_step_index = export_telemetry(
            steps, conversation_id, session_id, model_name, model_info,
            input_tokens, output_tokens, project_dir, last_sent_step,
            delta_input, delta_output
        )
        update_cache(cache, cache_path, conversation_id, max_step_index, input_tokens, output_tokens)
    except Exception as e:
        telemetry_status = "offline"
        with open(error_log_path, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] Export error: {str(e)}\n")
        cache["telemetry_offline_timestamp"] = time.time()
        try:
            with open(cache_path, 'w') as cf:
                json.dump(cache, cf)
        except OSError:
            pass

    print(f"{status_str} ┃ 📡 telemetry: {telemetry_status}")

if __name__ == "__main__":
    main()
