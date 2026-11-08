"""Structured JSON logging, correlation ids and OpenTelemetry tracing shared by every service."""
import contextvars
import json
import logging
import os
import sys
import time

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")
current_agent: contextvars.ContextVar[str] = contextvars.ContextVar("current_agent", default="-")

_propagator = TraceContextTextMapPropagator()


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        span = trace.get_current_span().get_span_context()
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": correlation_id.get(),
            "agent": current_agent.get(),
            "trace_id": format(span.trace_id, "032x") if span.is_valid else None,
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(service: str) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    for noisy in ("httpx", "httpcore", "uvicorn.access", "opentelemetry", "rq.worker"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger(service)


def log(logger: logging.Logger, level: int, msg: str, **fields) -> None:
    logger.log(level, msg, extra={"fields": fields})


def setup_tracing(service: str) -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
    trace.set_tracer_provider(provider)


def tracer(name: str = "triage"):
    return trace.get_tracer(name)


def inject_context() -> dict:
    carrier: dict = {}
    _propagator.inject(carrier)
    return carrier


def extract_context(carrier: dict | None):
    return _propagator.extract(carrier or {})


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None
