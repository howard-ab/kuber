import json
import os
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest


CONFIG_DIR = os.environ.get("CONFIG_DIR", "/app/config")
LOG_DIR = os.environ.get("LOG_DIR", "/app/logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
DEFAULT_PORT = 8080
LOG_LOCK = threading.Lock()
METRICS_LOCK = threading.Lock()
LOG_DURATION_TOTAL_SECONDS = 0.0
LOG_DURATION_COUNT = 0

LOG_REQUESTS_TOTAL = Counter(
    "custom_app_log_requests_total",
    "Total number of POST /log requests.",
)
LOG_ATTEMPTS_TOTAL = Counter(
    "custom_app_log_attempts_total",
    "POST /log attempts grouped by result.",
    ["result"],
)
LOG_REQUEST_DURATION_SECONDS = Histogram(
    "custom_app_log_request_duration_seconds",
    "Time spent processing POST /log requests.",
)
LOG_REQUEST_AVERAGE_DURATION_SECONDS = Gauge(
    "custom_app_log_request_average_duration_seconds",
    "Average time spent processing POST /log requests.",
)


def read_config_value(name, default):
    file_path = os.path.join(CONFIG_DIR, name)

    try:
        with open(file_path, "r", encoding="utf-8") as config_file:
            value = config_file.read().strip()
            return value if value else default
    except FileNotFoundError:
        return os.environ.get(name.upper(), default)
    except OSError:
        return default


def load_runtime_settings():
    return {
        "welcome_message": read_config_value("welcome_message", "Welcome to the custom app"),
        "welcome_header": read_config_value("welcome_header", "Custom Student App"),
        "log_level": read_config_value("log_level", "INFO"),
    }


def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def append_log(message, log_level, pod_name):
    ensure_log_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{timestamp} [{log_level}] [{pod_name}] {message}"

    with LOG_LOCK:
        with open(LOG_FILE, "a", encoding="utf-8") as log_file:
            log_file.write(line + "\n")

    print(line, flush=True)


def read_logs():
    ensure_log_dir()

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as log_file:
            return log_file.read()
    except FileNotFoundError:
        return ""


def record_log_duration(duration_seconds):
    global LOG_DURATION_COUNT
    global LOG_DURATION_TOTAL_SECONDS

    LOG_REQUEST_DURATION_SECONDS.observe(duration_seconds)

    with METRICS_LOCK:
        LOG_DURATION_COUNT += 1
        LOG_DURATION_TOTAL_SECONDS += duration_seconds
        LOG_REQUEST_AVERAGE_DURATION_SECONDS.set(
            LOG_DURATION_TOTAL_SECONDS / LOG_DURATION_COUNT
        )


class CustomAppHandler(BaseHTTPRequestHandler):
    server_version = "CustomAppHTTP/1.0"

    def _pod_name(self):
        return os.environ.get("POD_NAME", "local-run")

    def _write_headers(self, status_code, content_type):
        settings = load_runtime_settings()
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Pod-Name", self._pod_name())
        self.send_header("X-Welcome-Header", settings["welcome_header"])
        self.send_header("X-Log-Level", settings["log_level"])
        self.end_headers()

    def _send_text(self, status_code, body):
        encoded_body = body.encode("utf-8")
        self._write_headers(status_code, "text/plain; charset=utf-8")
        self.wfile.write(encoded_body)

    def _send_json(self, status_code, payload):
        encoded_body = json.dumps(payload).encode("utf-8")
        self._write_headers(status_code, "application/json; charset=utf-8")
        self.wfile.write(encoded_body)

    def _send_metrics(self):
        encoded_body = generate_latest()
        self._write_headers(HTTPStatus.OK, CONTENT_TYPE_LATEST)
        self.wfile.write(encoded_body)

    def _read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        return json.loads(raw_body.decode("utf-8"))

    def do_GET(self):
        settings = load_runtime_settings()

        if self.path == "/":
            self._send_text(HTTPStatus.OK, settings["welcome_message"])
            return

        if self.path == "/status":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return

        if self.path == "/logs":
            self._send_text(HTTPStatus.OK, read_logs())
            return

        if self.path == "/metrics":
            self._send_metrics()
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/log":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        start_time = time.perf_counter()
        LOG_REQUESTS_TOTAL.inc()

        try:
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                LOG_ATTEMPTS_TOTAL.labels(result="failure").inc()
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
                return

            message = payload.get("message")

            if not isinstance(message, str) or not message.strip():
                LOG_ATTEMPTS_TOTAL.labels(result="failure").inc()
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Field 'message' is required"})
                return

            settings = load_runtime_settings()
            append_log(message.strip(), settings["log_level"], self._pod_name())
            LOG_ATTEMPTS_TOTAL.labels(result="success").inc()
            self._send_json(HTTPStatus.CREATED, {"result": "saved"})
        finally:
            record_log_duration(time.perf_counter() - start_time)

    def log_message(self, fmt, *args):
        print(
            "%s - - [%s] %s"
            % (self.address_string(), self.log_date_time_string(), fmt % args),
            flush=True,
        )


def resolve_server_port():
    raw_port = read_config_value("server_port", str(DEFAULT_PORT))

    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT


def run():
    ensure_log_dir()
    server_port = resolve_server_port()
    server = ThreadingHTTPServer(("0.0.0.0", server_port), CustomAppHandler)
    print(f"Custom app is running on port {server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run()
