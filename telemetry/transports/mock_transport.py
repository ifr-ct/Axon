from collections import deque
from .base import BaseTransport


class MockTransport(BaseTransport):
    def __init__(self):
        super().__init__()
        self.log = deque(maxlen=200)

    def connect(self, config):
        self.connected = True
        self.error = ''
        return True

    def disconnect(self):
        self.connected = False
        self.error = ''

    def send(self, payload: bytes) -> bool:
        if not self.connected:
            self.error = 'Mock transport is disconnected.'
            return False
        self.log.append(payload.hex(' ').upper())
        return True

    def get_status(self):
        return 'Mock connected' if self.connected else 'Disconnected'
