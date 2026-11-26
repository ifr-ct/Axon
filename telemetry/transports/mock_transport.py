from collections import deque
from .base import BaseTransport


class MockTransport(BaseTransport):
    def __init__(self):
        super().__init__()
        self.connected = False
        self.log = deque(maxlen=200)

    def connect(self, config):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def send(self, payload: bytes) -> bool:
        if not self.connected:
            return False
        self.log.append(payload.hex(' ').upper())
        return True

    def get_status(self):
        return 'Mock connected' if self.connected else 'Disconnected'
