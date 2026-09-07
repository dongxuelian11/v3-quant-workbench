import unittest
from unittest.mock import Mock,patch
import baostock.util.socketutil as upstream
import baostock.common.context as context
from v3_backend.research.baostock_connection import bounded_connection


class BaoStockConnectionTest(unittest.TestCase):
    def test_timeout_eof_and_relogin_are_bounded(self):
        previous = getattr(context,'default_socket',None)
        original_connect,original_send = upstream.SocketUtil.connect,upstream.send_msg
        try:
            for failure in [TimeoutError('no reply'),b'']:
                fake = Mock()
                if isinstance(failure,Exception):
                    fake.recv.side_effect = failure
                else:
                    fake.recv.return_value = failure
                context.default_socket = None
                with patch('v3_backend.research.baostock_connection.socket.socket',return_value=fake),bounded_connection():
                    upstream.SocketUtil().connect()
                    with self.assertRaises((TimeoutError,ConnectionError)):
                        upstream.send_msg('test')
                    self.assertEqual(fake.recv.call_count,1)
                    upstream.SocketUtil().connect()
                    self.assertEqual(fake.settimeout.call_args.args,(45,))
                    self.assertEqual(fake.settimeout.call_count,2)
                self.assertIs(upstream.SocketUtil.connect,original_connect)
                self.assertIs(upstream.send_msg,original_send)
        finally:
            context.default_socket = previous
