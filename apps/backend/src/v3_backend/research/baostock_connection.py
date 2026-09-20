"""Bounded socket I/O around BaoStock's unchanged message decoder."""
from contextlib import contextmanager
import socket


class ReceivingSocket:
    def __init__(self, connection):
        self.connection = connection
        self.failure = None

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def recv(self, size, *args):
        try:
            value = self.connection.recv(size, *args)
            if not value:
                raise ConnectionError('BaoStock连接已关闭（EOF），已保存的下载断点保留')
            return value
        except TimeoutError as exc:
            self.connection.close()
            self.failure = TimeoutError('BaoStock收包超过45秒无响应，已保存的下载断点保留')
            raise self.failure from exc
        except OSError as exc:
            self.connection.close()
            self.failure = exc
            raise


@contextmanager
def bounded_connection():
    import baostock.util.socketutil as upstream
    import baostock.common.context as context
    import baostock.common.contants as constants
    original_connect, original_send = upstream.SocketUtil.connect, upstream.send_msg

    def connect(_):
        old = getattr(context, 'default_socket', None)
        if old is not None:
            old.close()
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(45)
        try:
            connection.connect((constants.BAOSTOCK_SERVER_IP, constants.BAOSTOCK_SERVER_PORT))
        except OSError:
            connection.close()
            raise
        context.default_socket = ReceivingSocket(connection)

    def send(message):
        connection = getattr(context, 'default_socket', None)
        if isinstance(connection, ReceivingSocket):
            connection.failure = None
        result = original_send(message)
        # Upstream catches socket exceptions; restore their failure semantics.
        if isinstance(connection, ReceivingSocket) and connection.failure is not None:
            raise connection.failure
        return result

    upstream.SocketUtil.connect, upstream.send_msg = connect, send
    try:
        yield
    finally:
        upstream.SocketUtil.connect, upstream.send_msg = original_connect, original_send
