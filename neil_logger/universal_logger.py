# universal_logger.py
import logging
import sys
import traceback
import inspect
from datetime import datetime
from pathlib import Path
from pymongo import MongoClient
import functools
import atexit

try:
    from sentry_sdk import init as sentry_init, capture_exception, capture_message, set_tag
    from sentry_sdk.integrations.logging import LoggingIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False

class UniversalLogger:
    def __init__(self, mongo_uri: str, mongo_db: str, name: str = None, run_id: str = None, log_collection: str = "run_logs", error_collection: str = "error_logs", sentry_dsn: str = None):

        # ── Infer the calling module’s name if none provided
        if not name:
            for frame_info in inspect.stack()[1:]:
                mod = inspect.getmodule(frame_info.frame)
                if mod and mod.__name__ != __name__:
                    name = mod.__name__
                    break
            else:
                name = "__main__"
        self.name = name

        # ── Auto-generate a run_id if none provided
        if not run_id:
            try:
                caller_file = inspect.getmodule(inspect.stack()[1].frame).__file__
                stem = Path(caller_file).stem
            except Exception:
                stem = self.name
            run_id = f"{stem}_{datetime.utcnow():%Y%m%d_%H%M%S}"
        self.run_id = run_id

        # ── Set up MongoDB collections
        self.mongo_client = MongoClient(mongo_uri)
        self.db = self.mongo_client[mongo_db]
        self.log_collection = self.db[log_collection]
        self.error_collection = self.db[error_collection]
        self.buffer = []

        # ── Configure the stdlib Logger
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(logging.DEBUG)

        # Add Console + Buffer handlers once
        if not any(isinstance(h, logging.StreamHandler) for h in self.logger.handlers):
            fmt = "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
            formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

            # Console
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(formatter)
            self.logger.addHandler(stream_handler)

            # In-memory buffer
            class BufferHandler(logging.Handler):
                def emit(inner_self, record):
                    self.buffer.append({
                        "timestamp": datetime.utcnow(),
                        "level":     record.levelname,
                        "module":    record.name,
                        "function":  record.funcName,
                        "message":   record.getMessage(),
                        "run_id":    self.run_id
                    })
            self.logger.addHandler(BufferHandler())

        # ── Optional Sentry integration
        if sentry_dsn:
            if not SENTRY_AVAILABLE:
                raise ImportError("To enable Sentry logging, install universal-logger[sentry]")
            sentry_logging = LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
            sentry_init(dsn=sentry_dsn, traces_sample_rate=0.0, integrations=[sentry_logging])
            set_tag("run_id",  self.run_id)
            set_tag("logger",  self.name)

        # ── Flush buffer on process exit
        atexit.register(self.flush)

    # ── Convenience wrappers around the stdlib logger
    def debug(self,   msg): self.logger.debug(msg)
    def info(self,    msg): self.logger.info(msg)
    def warning(self, msg): self.logger.warning(msg)
    def critical(self, msg): self.logger.critical(msg)
    def log(self, level, msg): self.logger.log(level, msg)

    # ── Log + send to Sentry
    def error(self, msg, exc: Exception = None):
        self.logger.error(msg)
        if exc:
            capture_exception(exc)
        else:
            capture_message(msg, level="error")

    # ── Write buffered logs & errors to MongoDB
    def flush(self):
        if not self.buffer:
            return

        logs = self.buffer.copy()
        self.buffer.clear()

        # Insert all logs under a single run document
        self.log_collection.insert_one({
            "run_id":   self.run_id,
            "logs":     logs,
            "timestamp": datetime.utcnow()
        })

        # Extract only errors for the error collection
        errors = [r for r in logs if r["level"] in {"ERROR", "CRITICAL"}]
        if errors:
            self.error_collection.insert_one({
                "run_id":   self.run_id,
                "errors":   errors,
                "timestamp": datetime.utcnow()
            })

    # ── Catch *uncaught* exceptions and log them
    def enable_global_exception_hook(self):
        def handle(exc_type, exc_value, exc_tb):
            # allow normal KeyboardInterrupt behavior
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_tb)
                return
            tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            self.error_collection.insert_one({
                "timestamp":   datetime.utcnow(),
                "run_id":      self.run_id,
                "error_type":  str(exc_type),
                "error":       str(exc_value),
                "traceback":   tb_str,
                "script":      self.name
            })
            capture_exception(exc_value)
        sys.excepthook = handle

    # ── Decorator to capture & log exceptions in functions
    def capture_errors(self, suppress: bool = False):
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    self.logger.error(f"[{func.__name__}] {e}")
                    tb = traceback.format_exc()
                    self.buffer.append({
                        "timestamp": datetime.utcnow(),
                        "level":     "ERROR",
                        "module":    self.name,
                        "function":  func.__name__,
                        "message":   str(e),
                        "traceback": tb,
                        "run_id":    self.run_id
                    })
                    capture_exception(e)
                    if not suppress:
                        raise
            return wrapper
        return decorator
