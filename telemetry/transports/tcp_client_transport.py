from dataclasses import dataclass
from .serial_transport import SerialTransport


@dataclass
class TCPClientConfig:
    host: str = '127.0.0.1'
    port: int = 9000


class TCPClientTransport(SerialTransport):
    def connect(self, config):
        raise NotImplementedError('TCP client transport is planned for V2.')
