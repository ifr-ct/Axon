from abc import ABC, abstractmethod


class BaseTransport(ABC):
    def __init__(self):
        self.callback = None
        self.connected = False
        self.error = ''

    @abstractmethod
    def connect(self, config) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def send(self, payload: bytes) -> bool: ...

    def on_receive(self, callback):
        self.callback = callback

    @abstractmethod
    def get_status(self) -> str: ...
