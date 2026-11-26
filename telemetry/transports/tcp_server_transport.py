from dataclasses import dataclass
from .serial_transport import SerialTransport


@dataclass
class TCPServerConfig:
    host: str = '0.0.0.0'
    port: int = 9000
    max_clients: int = 8


class TCPServerTransport(SerialTransport):
    def connect(self, config):
        raise NotImplementedError('TCP server transport is planned for V2.')
