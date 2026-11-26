from ..protocol import encode
from .mock_transport import MockTransport


class TransportManager:
    def __init__(self):
        self.transport = MockTransport()
        self.transport.connect({})

    def generate(self, slots, fingerprint, **options):
        return encode(slots, fingerprint, **options)

    def send(self, slots, fingerprint, **options):
        return self.transport.send(self.generate(slots, fingerprint, **options))
