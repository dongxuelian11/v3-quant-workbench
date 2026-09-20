import unittest
from unittest.mock import Mock,patch
import baostock.util.socketutil as upstream
import baostock.common.context as context
from v3_backend.research.baostock_connection import bounded_connection


class BaoStockConnectionTest(unittest.TestCase):
    def test_eof_during_real_result_pagination_never_returns_partial_rows(self):
        from baostock.data.resultset import ResultData
        import baostock.common.contants as constants
        from v3_backend.research.data import _bs_query
        result = ResultData()
        result.fields = ['code']
        result.data = [['sh.600000'],['sh.600001']]
        result.cur_row_num = 0
        result.cur_page_num = '1'
        result.msg_body = constants.MESSAGE_SPLIT.join(['x','x','1'])
        result.msg_type = constants.MESSAGE_TYPE_LOGIN_REQUEST
        result.error_code = '0'
        fake = Mock()
        fake.recv.return_value = b''
        previous = getattr(context,'default_socket',None)
        try:
            context.default_socket = None
            with patch('v3_backend.research.baostock_connection.socket.socket',return_value=fake),patch.object(constants,'BAOSTOCK_PER_PAGE_COUNT',2),bounded_connection():
                upstream.SocketUtil().connect()
                with self.assertRaisesRegex(ConnectionError,'EOF'):
                    _bs_query(Mock(),lambda:result)
                self.assertEqual(result.cur_row_num,2)
        finally:
            context.default_socket = previous

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
