"""Single upstream TCP client for the vehicle telemetry link."""
from dataclasses import dataclass
import socket
import threading

from .base import BaseTransport


@dataclass
class TCPClientConfig:
    host: str = ''
    port: int = 9000

    @classmethod
    def from_dict(cls, value=None):
        if value is None:
            value = {}
        if isinstance(value, cls):
            value = value.to_dict()
        if not isinstance(value, dict):
            raise ValueError('TCP settings must be an object.')
        return cls(host=value.get('host', cls.host), port=value.get('port', cls.port)).validated(allow_empty_host=True)

    def validated(self, allow_empty_host=False):
        if not isinstance(self.host, str) or len(self.host) > 253:
            raise ValueError('Vehicle host must be a string of at most 253 characters.')
        if not allow_empty_host and not self.host.strip():
            raise ValueError('Vehicle host is required.')
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError('Vehicle port must be an integer between 1 and 65535.')
        return type(self)(host=self.host.strip(), port=self.port)

    def to_dict(self):
        return dict(host=self.host, port=self.port)


class TCPClientTransport(BaseTransport):
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()
        self.sock = None
        self.config = None
        self.thread = None
        self.stop_event = threading.Event()

    def connect(self, config):
        try:
            config = TCPClientConfig.from_dict(config).validated()
        except ValueError as error:
            self.error = str(error)
            return False
        self.disconnect()
        with self.lock:
            self.config = config
            self.error = ''
            try:
                sock = socket.create_connection((config.host, config.port), timeout=3)
            except OSError as error:
                self.connected = False
                self.error = f'Cannot connect to {config.host}:{config.port}: {error}'
                return False
            sock.settimeout(0.5)
            self.sock = sock
            self.connected = True
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._read_loop, args=(sock,), daemon=True)
            self.thread.start()
        return True

    def _read_loop(self, sock):
        while not self.stop_event.is_set():
            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError as error:
                self._fail(f'TCP receive failed: {error}', sock)
                break
            if not data:
                self._fail('TCP connection closed by remote.', sock)
                break
            callback = self.callback
            if callback:
                try:
                    callback(data)
                except Exception:
                    pass

    def _fail(self, message, sock):
        with self.lock:
            if self.stop_event.is_set() or sock is not self.sock:
                return
            self.sock = None
            self.connected = False
            self.error = message
        if sock:
            try:
                sock.close()
            except OSError:
                pass

    def disconnect(self):
        self.stop_event.set()
        with self.lock:
            sock, self.sock = self.sock, None
            self.connected = False
            self.error = ''
            thread = self.thread
            self.thread = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1)

    def send(self, payload: bytes) -> bool:
        with self.lock:
            if not self.connected or not self.sock:
                self.error = 'TCP connection is not connected.'
                return False
            try:
                self.sock.sendall(payload)
            except OSError as error:
                self.stop_event.set()
                sock, self.sock = self.sock, None
                self.connected = False
                self.error = f'TCP send failed: {error}'
                try:
                    sock.close()
                except OSError:
                    pass
                return False
            self.error = ''
            return True

    def get_status(self):
        if self.connected and self.config:
            return f'TCP {self.config.host}:{self.config.port} · Connected'
        if self.config:
            return f'TCP {self.config.host}:{self.config.port} · {"Error" if self.error else "Disconnected"}'
        return 'TCP disconnected'
