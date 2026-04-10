"""OpenTelemetry setup for the memory service (optional dependency)."""
import os

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False

_tracer = None


class _NoopSpan:
    """Minimal no-op span for when OpenTelemetry is not installed."""
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def set_attribute(self, *args): pass
    def set_status(self, *args): pass
    def add_event(self, *args): pass


class _NoopTracer:
    """Minimal no-op tracer for when OpenTelemetry is not installed."""
    def start_as_current_span(self, name, **kwargs):
        return _NoopSpan()


def setup_telemetry(service_name: str = "memory"):
    global _tracer
    if _tracer is not None:
        return _tracer

    if not _HAS_OTEL:
        _tracer = _NoopTracer()
        return _tracer

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    otlp_endpoint = os.getenv("OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        except ImportError:
            exporter = ConsoleSpanExporter()
    else:
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    return _tracer


def get_tracer():
    global _tracer
    if _tracer is None:
        return setup_telemetry()
    return _tracer
