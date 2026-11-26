from pathlib import Path
import socket
import socketserver
import tempfile
import threading
import time
import unittest

from telemetry.bridge import Bridge
from telemetry.storage import Storage
from telemetry.transports import (LocalProxyServer, ProxyConfig, TCPClientConfig,
                                  TCPClientTransport)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_for(predicate, timeout=2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def recv_exact(sock, size):
    data = b''
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return data


class _UpstreamHandler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        server.client = self.request
        server.connected.set()
        try:
            while not server.stopping.is_set():
                data = self.request.recv(4096)
                if not data:
                    break
                server.received.extend(data)
        except OSError:
            pass
        finally:
            server.disconnected.set()


class UpstreamServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(self):
        super().__init__(('127.0.0.1', 0), _UpstreamHandler)
        self.connected = threading.Event()
        self.disconnected = threading.Event()
        self.stopping = threading.Event()
        self.received = bytearray()
        self.client = None
        self.thread = threading.Thread(target=self.serve_forever, kwargs=dict(poll_interval=0.1), daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server_address[1]

    def send(self, payload):
        self.client.sendall(payload)

    def stop(self):
        self.stopping.set()
        if self.client:
            try:
                self.client.close()
            except OSError:
                pass
        try:
            self.shutdown()
        except Exception:
            pass
        self.server_close()


class TCPClientTransportTests(unittest.TestCase):
    def setUp(self):
        self.server = UpstreamServer()

    def tearDown(self):
        self.server.stop()

    def test_connect_send_and_receive(self):
        transport = TCPClientTransport()
        received = []
        transport.on_receive(received.append)
        self.assertTrue(transport.connect(TCPClientConfig('127.0.0.1', self.server.port)))
        self.assertTrue(self.server.connected.wait(2))
        self.assertTrue(transport.send(b'\x01\x02\x03'))
        self.assertTrue(wait_for(lambda: bytes(self.server.received) == b'\x01\x02\x03'))
        self.server.send(b'\xA5\x5A')
        self.assertTrue(wait_for(lambda: b''.join(received) == b'\xA5\x5A'))
        transport.disconnect()
        self.assertFalse(transport.connected)
        self.assertTrue(self.server.disconnected.wait(2))

    def test_connect_failure_is_reported(self):
        port = free_port()
        transport = TCPClientTransport()
        self.assertFalse(transport.connect(TCPClientConfig('127.0.0.1', port)))
        self.assertFalse(transport.connected)
        self.assertIn('Cannot connect', transport.error)

    def test_empty_host_is_rejected(self):
        transport = TCPClientTransport()
        self.assertFalse(transport.connect(TCPClientConfig()))
        self.assertFalse(transport.connected)
        self.assertIn('required', transport.error)


class ProxyServerTests(unittest.TestCase):
    def test_broadcasts_to_connected_viewers(self):
        proxy = LocalProxyServer(ProxyConfig('127.0.0.1', free_port()))
        self.assertTrue(proxy.start())
        first = socket.create_connection(('127.0.0.1', proxy.config.port), timeout=2)
        first.settimeout(2)
        try:
            self.assertTrue(wait_for(lambda: proxy.state()['clients'] == 1))
            proxy.broadcast(b'abc')
            self.assertEqual(recv_exact(first, 3), b'abc')

            second = socket.create_connection(('127.0.0.1', proxy.config.port), timeout=2)
            second.settimeout(2)
            try:
                self.assertTrue(wait_for(lambda: proxy.state()['clients'] == 2))
                proxy.broadcast(b'def')
                self.assertEqual(recv_exact(first, 3), b'def')
                self.assertEqual(recv_exact(second, 3), b'def')
            finally:
                second.close()
        finally:
            first.close()
            proxy.stop()
        self.assertFalse(proxy.state()['running'])

    def test_stop_is_idempotent(self):
        proxy = LocalProxyServer(ProxyConfig('127.0.0.1', free_port()))
        self.assertTrue(proxy.start())
        proxy.stop()
        proxy.stop()
        self.assertFalse(proxy.state()['running'])


class BridgeTCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(config_dir=Path(self.temp.name))
        self.bridge = Bridge(self.storage)
        self.bridge.call('demo')
        self.server = UpstreamServer()

    def tearDown(self):
        self.bridge.close()
        self.server.stop()
        self.temp.cleanup()

    def connect(self, proxy_port):
        return self.bridge.call('transport_connect', {
            'kind':'tcp',
            'config':{'host':'127.0.0.1', 'port':self.server.port},
            'proxy':{'host':'127.0.0.1', 'port':proxy_port},
        })

    def test_send_and_forward_telemetry_to_viewer(self):
        proxy_port = free_port()
        result = self.connect(proxy_port)
        self.assertNotIn('request_error', result)
        self.assertEqual(result['transport']['kind'], 'tcp')
        self.assertTrue(result['transport']['connected'])
        self.assertTrue(result['transport']['proxy']['running'])
        self.assertEqual(result['transport']['proxy']['port'], proxy_port)
        self.assertTrue(self.server.connected.wait(2))

        viewer = socket.create_connection(('127.0.0.1', proxy_port), timeout=2)
        viewer.settimeout(2)
        try:
            self.assertTrue(wait_for(lambda: self.bridge.manager.proxy.state()['clients'] == 1))
            self.server.send(b'\x10\x20')
            self.assertEqual(recv_exact(viewer, 2), b'\x10\x20')

            self.server.received.clear()
            sent = self.bridge.call('send')
            self.assertNotIn('request_error', sent)
            self.assertEqual(len(sent['logs']), 1)
            frame = bytes.fromhex(sent['frame']['hex'])
            self.assertTrue(wait_for(lambda: bytes(self.server.received) == frame))
        finally:
            viewer.close()

        self.bridge.flush()
        document = self.storage.read()
        self.assertEqual(document['transport']['tcp']['host'], '127.0.0.1')
        self.assertEqual(document['transport']['tcp']['port'], self.server.port)
        self.assertEqual(document['transport']['proxy']['port'], proxy_port)
        self.bridge.close()

        restored = Bridge(self.storage)
        try:
            state = restored.call('state')
            self.assertEqual(state['transport']['kind'], 'mock')
            self.assertEqual(state['transport']['tcp']['host'], '127.0.0.1')
            self.assertEqual(state['transport']['proxy']['port'], proxy_port)
            self.assertFalse(state['transport']['proxy']['running'])
        finally:
            restored.close()

    def test_connect_failure_keeps_proxy_stopped(self):
        port = free_port()
        result = self.bridge.call('transport_connect', {
            'kind':'tcp', 'config':{'host':'127.0.0.1', 'port':port},
            'proxy':{'host':'127.0.0.1', 'port':free_port()},
        })
        self.assertNotIn('request_error', result)
        self.assertEqual(result['transport']['kind'], 'tcp')
        self.assertFalse(result['transport']['connected'])
        self.assertIn('Cannot connect', result['transport']['error'])
        self.assertFalse(result['transport']['proxy']['running'])
        self.assertIn('request_error', self.bridge.call('send'))

    def test_proxy_start_and_stop_actions(self):
        port = free_port()
        result = self.bridge.call('proxy_start', {'config':{'host':'127.0.0.1', 'port':port}})
        self.assertNotIn('request_error', result)
        self.assertTrue(result['transport']['proxy']['running'])
        self.assertEqual(result['transport']['proxy']['port'], port)
        result = self.bridge.call('proxy_stop')
        self.assertFalse(result['transport']['proxy']['running'])
        self.bridge.flush()
        self.assertEqual(self.storage.read()['transport']['proxy']['port'], port)

    def test_workspace_switch_stops_tcp_and_proxy(self):
        result = self.connect(free_port())
        self.assertTrue(result['transport']['connected'])
        target = Path(self.temp.name) / 'next.tmws'
        result = self.bridge.call('workspace_new', {'path':str(target), 'name':'Next'})
        self.assertNotIn('request_error', result)
        self.assertEqual(self.bridge.manager.kind, 'mock')
        self.assertIsNone(self.bridge.manager.proxy)
        self.assertEqual(result['transport']['kind'], 'mock')
        self.assertFalse(result['transport']['proxy']['running'])


if __name__ == '__main__':
    unittest.main()
