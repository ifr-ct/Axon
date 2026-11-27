from collections import deque

from ..protocol import encode
from .mock_transport import MockTransport
from .proxy_server import LocalProxyServer, ProxyConfig
from .serial_transport import SerialConfig, SerialTransport, list_serial_ports
from .tcp_client_transport import TCPClientConfig, TCPClientTransport


class TransportManager:
    def __init__(self):
        self.log = deque(maxlen=200)
        self.kind = 'mock'
        self.transport = MockTransport()
        self.transport.connect({})
        self.error = ''
        self.tcp_config = TCPClientConfig()
        self.proxy_config = ProxyConfig()
        self.proxy = None

    def connect(self, kind, config=None, proxy_config=None):
        if kind not in ('mock', 'serial', 'tcp'):
            raise ValueError('Unknown transport type.')
        serial_config = None
        tcp_config = None
        serial_proxy_config = None
        if kind == 'serial':
            serial_config = SerialConfig.from_dict(config)
            serial_proxy_config = ProxyConfig.from_dict(proxy_config) if proxy_config is not None else None
        elif kind == 'tcp':
            tcp_config = TCPClientConfig.from_dict(config)
            proxy_config = ProxyConfig.from_dict(proxy_config) if proxy_config is not None else self.proxy_config
        self.transport.on_receive(None)
        self.transport.disconnect()
        self.stop_proxy()
        if kind == 'mock':
            transport = MockTransport()
            connected = transport.connect({})
        elif kind == 'serial':
            transport = SerialTransport()
            transport.on_receive(self._on_receive)
            connected = transport.connect(serial_config)
            if connected and serial_proxy_config is not None:
                self.proxy_config = serial_proxy_config
                self.start_proxy(serial_proxy_config)
        else:
            self.tcp_config = tcp_config
            self.proxy_config = proxy_config
            transport = TCPClientTransport()
            transport.on_receive(self._on_receive)
            connected = transport.connect(tcp_config)
            if connected:
                self.start_proxy(proxy_config)
        self.kind = kind
        self.transport = transport
        self.error = '' if connected else transport.error
        return connected

    def disconnect(self):
        self.transport.on_receive(None)
        self.transport.disconnect()
        self.stop_proxy()
        self.error = ''

    def reset(self):
        self.connect('mock')

    def close(self):
        self.disconnect()

    def start_proxy(self, config=None):
        if config is not None:
            self.proxy_config = ProxyConfig.from_dict(config)
        self.stop_proxy()
        proxy = LocalProxyServer(self.proxy_config)
        started = proxy.start()
        self.proxy = proxy
        return started

    def stop_proxy(self):
        proxy, self.proxy = self.proxy, None
        if proxy:
            proxy.stop()

    def _on_receive(self, payload: bytes):
        if self.proxy:
            self.proxy.broadcast(payload)

    def generate(self, slots, fingerprint, **options):
        return encode(slots, fingerprint, **options)

    def send(self, slots, fingerprint, **options):
        payload = self.generate(slots, fingerprint, **options)
        if not self.transport.send(payload):
            self.error = self.transport.error or 'Transport is not connected.'
            return False
        self.error = ''
        self.log.append(payload.hex(' ').upper())
        return True

    def state(self):
        proxy = self.proxy.state() if self.proxy else dict(running=False, host=self.proxy_config.host,
                                                          port=self.proxy_config.port, clients=0, error='')
        state = dict(kind=self.kind, status=self.transport.get_status(), connected=bool(self.transport.connected),
                     error=self.error or self.transport.error, proxy=proxy)
        if self.kind == 'tcp':
            state['tcp'] = self.tcp_config.to_dict()
        return state
