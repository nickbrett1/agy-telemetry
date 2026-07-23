import sys
import json
import os
import datetime
import hashlib
import time
import socket
import urllib.parse
import tempfile


# Prepend custom telemetry lib path containing OpenTelemetry SDK
lib_path = os.path.expanduser("~/.gemini/antigravity-cli/telemetry_lib")
if os.path.exists(lib_path) and lib_path not in sys.path:
    sys.path.insert(0, lib_path)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider, IdGenerator
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
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
        import random
        return random.getrandbits(128)
        
    def generate_span_id(self) -> int:
        if self.span_id is not None:
            return self.span_id
        import random
        return random.getrandbits(64)

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

def extract_cli_info(input_data):
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

    return {
        "conversation_id": conversation_id,
        "session_id": session_id,
        "raw_transcript_path": raw_transcript_path,
        "model_name": model_name,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "used_percent": used_percent,
        "project_dir": project_dir
    }

def format_status_str(info):
    model_name = info.get("model_name", "Gemini")
    input_tokens = info.get("input_tokens", 0)
    output_tokens = info.get("output_tokens", 0)
    used_percent = info.get("used_percent", 0.0)
    return f"agy ✦ {model_name} ┃ 📥 {input_tokens} ┃ 📤 {output_tokens} ┃ 📊 {used_percent:.2f}%"

def check_is_online():
    try:
        parsed = urllib.parse.urlparse(ENDPOINT)
        host = parsed.hostname or "localhost"
        port = parsed.port
        if port is None:
            port = 80 if parsed.scheme == "http" else 443

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)  # 200ms timeout
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

def resolve_transcript_path(raw_transcript_path):
    if not os.path.exists(raw_transcript_path):
        alt_path = raw_transcript_path.replace("/.gemini/antigravity/", "/.gemini/antigravity-cli/")
        if os.path.exists(alt_path):
            return alt_path
    return raw_transcript_path

def send_root_span(tracer, id_generator, info, first_step_time, last_step_time, trace_id_int, root_span_id_int):
    id_generator.trace_id = trace_id_int
    id_generator.span_id = root_span_id_int

    root_span = tracer.start_span(
        name=f"Conversation: {info['conversation_id'][:8]}",
        start_time=first_step_time
    )
    root_span.set_attribute("openinference.span.kind", "CHAIN")
    root_span.set_attribute("session_id", info['session_id'])
    root_span.set_attribute("llm.model_name", info['model_name'])
    root_span.set_attribute("llm.token_count.prompt", info['input_tokens'])
    root_span.set_attribute("llm.token_count.completion", info['output_tokens'])
    root_span.set_attribute("llm.token_count.total", info['input_tokens'] + info['output_tokens'])
    root_span.set_attribute("workspace.project_dir", info['project_dir'])
    root_span.end(end_time=last_step_time)

    return trace.set_span_in_context(
        NonRecordingSpan(
            SpanContext(
                trace_id=trace_id_int,
                span_id=root_span_id_int,
                is_remote=False,
                trace_flags=TraceFlags(TraceFlags.SAMPLED)
            )
        )
    )

def process_child_spans(tracer, id_generator, parent_ctx, steps, last_sent_step, info, first_step_time, trace_id_int):
    last_user_input = None
    last_planner_response = None

    for i, step in enumerate(steps):
        stype = step.get("type")
        ssource = step.get("source")
        sindex = step.get("step_index")
        scontent = step.get("content", "")
        stime = iso_to_nanos(step.get("created_at"))

        if stype == "USER_INPUT":
            last_user_input = step
        elif stype == "PLANNER_RESPONSE":
            last_planner_response = step
            if sindex > last_sent_step:
                child_span_id_hex = hashlib.sha256(f"{info['conversation_id']}_{sindex}".encode()).hexdigest()[:16]
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
                child_span.set_attribute("llm.model_name", info['model_name'])
                child_span.set_attribute("llm.provider", "google")
                child_span.set_attribute("llm.output_messages.0.message.role", "assistant")
                child_span.set_attribute("llm.output_messages.0.message.content", scontent)

                if last_user_input:
                    ucontent = last_user_input.get("content", "")
                    child_span.set_attribute("llm.input_messages.0.message.role", "user")
                    child_span.set_attribute("llm.input_messages.0.message.content", ucontent)

                child_span.end(end_time=stime)

        elif ssource == "MODEL" and stype not in ["PLANNER_RESPONSE", "CHECKPOINT", "CONVERSATION_HISTORY"]:
            if sindex > last_sent_step:
                child_span_id_hex = hashlib.sha256(f"{info['conversation_id']}_{sindex}".encode()).hexdigest()[:16]
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
                tool_span.end(end_time=stime)

def process_telemetry(info, status_str, cache_path, error_log_path, cache, last_sent_step, steps):
    try:
        resource = Resource(attributes={"service.name": "agy-cli"})
        id_generator = PresetIdGenerator()
        provider = TracerProvider(resource=resource, id_generator=id_generator)
        exporter = OTLPSpanExporter(endpoint=ENDPOINT, timeout=1.0)
        processor = SimpleSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer("agy-telemetry-statusline")
    except Exception as e:
        with open(error_log_path, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] OTel Init error: {str(e)}\n")
        return "offline"

    try:
        trace_id_hex = info['conversation_id'].replace('-', '')
        root_span_id_hex = hashlib.sha256(info['conversation_id'].encode()).hexdigest()[:16]

        trace_id_int = int(trace_id_hex, 16)
        root_span_id_int = int(root_span_id_hex, 16)
    except Exception as e:
        with open(error_log_path, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] UUID conversion error: {str(e)}\n")
        return "err"

    first_step_time = iso_to_nanos(steps[0].get("created_at"))
    last_step_time = iso_to_nanos(steps[-1].get("created_at"))

    try:
        parent_ctx = send_root_span(tracer, id_generator, info, first_step_time, last_step_time, trace_id_int, root_span_id_int)
        process_child_spans(tracer, id_generator, parent_ctx, steps, last_sent_step, info, first_step_time, trace_id_int)

        provider.shutdown()

        max_step_index = max(s.get("step_index", 0) for s in steps)
        last_sent_steps = cache.get("last_sent_steps", {})
        last_sent_steps[info['conversation_id']] = max_step_index
        cache["last_sent_steps"] = last_sent_steps
        with open(cache_path, 'w') as cf:
            json.dump(cache, cf)

        return "ok"
    except Exception as e:
        with open(error_log_path, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] Export error: {str(e)}\n")
        return "offline"

def main():
    input_data = read_input_data()
    if input_data is None:
        print("agy ✦ statusline")
        return

    info = extract_cli_info(input_data)
    status_str = format_status_str(info)

    if not OTEL_AVAILABLE:
        print(f"{status_str} ┃ 📡 telemetry: dep_missing")
        return

    if not info['conversation_id'] or not info['raw_transcript_path']:
        print(f"{status_str} ┃ 📡 telemetry: off")
        return

    transcript_path = resolve_transcript_path(info['raw_transcript_path'])
    if not os.path.exists(transcript_path):
        print(f"{status_str} ┃ 📡 telemetry: no_logs")
        return

    cache_path = os.path.join(tempfile.gettempdir(), "agy_telemetry_cache.json")
    error_log_path = os.path.join(tempfile.gettempdir(), "agy_telemetry_error.log")

    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as cf:
                cache = json.load(cf)
        except Exception:
            pass
            
    last_sent_step = cache.get("last_sent_steps", {}).get(info['conversation_id'], -1)

    offline_ts = cache.get("telemetry_offline_timestamp", 0)
    if time.time() - offline_ts < 30:
        print(f"{status_str} ┃ 📡 telemetry: offline")
        return

    if not check_is_online():
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

    steps = []
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        steps.append(json.loads(line))
                    except Exception:
                        pass
    except Exception as e:
        with open(error_log_path, "a") as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] File read error: {str(e)}\n")
        print(f"{status_str} ┃ 📡 telemetry: err")
        return

    if not steps:
        print(f"{status_str} ┃ 📡 telemetry: empty")
        return

    telemetry_status = process_telemetry(info, status_str, cache_path, error_log_path, cache, last_sent_step, steps)
    print(f"{status_str} ┃ 📡 telemetry: {telemetry_status}")

if __name__ == "__main__":
    main()
