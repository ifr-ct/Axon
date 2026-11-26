"""Loopback TCP fan-out for raw downstream telemetry (VOFA+)."""
from dataclasses import dataclass
import socket
import socketserver
import threading


@dataclass
class ProxyConfig:
    host: str = '127.0.0.1'
    port: int = 9000

    @classmethod
    def from_dict(cls, value=None):
        if value is None:
            value = {}
        if isinstance(value, cls):
            value = value.to_dict()
        if not isinstance(value, dict):
            raise ValueError('Proxy settings must be an object.')
        return cls(host=value.get('host', cls.host), port=value.get('port', cls.port)).validated()

    def validated(self):
        if not isinstance(self.host, str) or not self.host.strip() or len(self.host) > 253:
            raise ValueError('Proxy listen host must be a non-empty string of at most 253 characters.')
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError('Proxy listen port must be an integer between 1 and 65535.')
        return type(self)(host=self.host.strip(), port=self.port)

    def to_dict(self):
        return dict(host=self.host, port=self.port)


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(0.5)
        with self.server.clients_lock:
            self.server.clients.add(client)
        try:
            while not self.server.stopping.is_set():
                try:
                    data = client.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                # VOFA+ is a viewer; ignore anything it writes.
        finally:
            with self.server.clients_lock:
                self.server.clients.discard(client)
            try:
                client.close()
            except OSError:
                pass


class _ProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(self, address):
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.stopping = threading.Event()
        super().__init__(address, _ProxyHandler)


class LocalProxyServer:
    def __init__(self, config=None):
        self.config = ProxyConfig.from_dict(config)
        self.server = None
        self.thread = None
        self.error = ''

    def start(self):
        if self.server:
            return True
        try:
            server = _ProxyServer((self.config.host, self.config.port))
        except OSError as error:
            self.error = f'Cannot listen on {self.config.host}:{self.config.port}: {error}'
            return False
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, kwargs=dict(poll_interval=0.2), daemon=True)
        self.thread.start()
        self.error = ''
        return True

    def stop(self):
        server, thread = self.server, self.thread
        self.server, self.thread = None, None
        if server:
            server.stopping.set()
            try:
                server.shutdown()
            except Exception:
                pass
            with server.clients_lock:
                clients = list(server.clients)
                server.clients.clear()
            for client in clients:
                try:
                    client.close()
                except OSError:
                    pass
            server.server_close()
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1)
        self.error = ''

    def broadcast(self, payload: bytes):
        server = self.server
        if not server:
            return
        with server.clients_lock:
            clients = list(server.clients)
        for client in clients:
            try:
                client.sendall(payload)
            except OSError:
                with server.clients_lock:
                    server.clients.discard(client)
                try:
                    client.close()
                except OSError:
                    pass

    def state(self):
        server = self.server
        clients = 0
        if server:
            with server.clients_lock:
                clients = len(server.clients)
        return dict(running=bool(server), host=self.config.host, port=self.config.port,
                    clients=clients, error=self.error)
