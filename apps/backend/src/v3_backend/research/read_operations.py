"""Cancellation handles for in-flight reads; computation jobs remain in Jobs."""
import threading

CANCELLABLE_READS = frozenset({
    'storage.migration.preview','storage.migration.start','storage.inspect', 'simulation.table', 'simulation.accounts.export', 'simulation.accounts.curve',
    'experiments.get', 'experiments.table', 'experiments.analysis',
    'experiments.calendar', 'experiments.compare', 'experiments.previousComparison', 'exports.create',
})


class ReadOperations:
    def __init__(self):
        self._lock = threading.Lock()
        self._active = {}

    def begin(self, method, params):
        key = params.get('readId')
        if method not in CANCELLABLE_READS or key is None:
            return None
        if not isinstance(key, str) or not key.strip() or len(key) > 160:
            raise ValueError('读取标识无效')
        with self._lock:
            if key in self._active:
                raise ValueError('读取标识正在使用，请为新请求使用独立标识')
            event = threading.Event()
            self._active[key] = event
        return key, event

    @staticmethod
    def check(operation):
        if operation is not None and operation[1].is_set():
            raise InterruptedError('读取已取消')

    def cancel(self, key):
        with self._lock:
            event = self._active.get(key) if isinstance(key, str) else None
            if event is not None:
                event.set()
            return {'requested': event is not None}

    def finish(self, operation):
        if operation is not None:
            with self._lock:
                if self._active.get(operation[0]) is operation[1]:
                    del self._active[operation[0]]

    def cancel_all(self):
        with self._lock:
            for event in self._active.values():
                event.set()
