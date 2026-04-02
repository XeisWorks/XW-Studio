"""Thread-safe background worker using QThread + signals."""
from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """Signals emitted by BackgroundWorker."""
    started = Signal()
    progress = Signal(int, str)
    result = Signal(object)
    error = Signal(Exception)
    finished = Signal()


class BackgroundWorker(QThread):
    """Run a callable in a background thread with progress reporting.

    Usage::

        worker = BackgroundWorker(some_function, arg1, arg2)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.start()
    """

    signals: WorkerSignals

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        self.signals.started.emit()
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.signals.result.emit(result)
        except Exception as exc:
            logger.error("Worker error: %s\n%s", exc, traceback.format_exc())
            self.signals.error.emit(exc)
        finally:
            self.signals.finished.emit()
