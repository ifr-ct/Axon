from dataclasses import dataclass
from .base import BaseTransport


@dataclass
class SerialConfig:
    port: str = 'COM3'
    baudrate: int = 115200
    data_bits: int = 8


class SerialTransport(BaseTransport):
    def connect(self, config):
        raise NotImplementedError('Serial transport is planned for V2.')

    def disconnect(self):
        pass

    def send(self, payload: bytes) -> bool:
        return False

    def get_status(self):
        return 'Pending V2'
