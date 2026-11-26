from abc import ABC, abstractmethod


class BaseTransport(ABC):
    def __init__(self):
        self.callback = None

    @abstractmethod
    def connect(self, config): ...

    @abstractmethod
    def disconnect(self): ...

    @abstractmethod
    def send(self, payload: bytes) -> bool: ...

    def on_receive(self, callback):
        self.callback = callback

    @abstractmethod
    def get_status(self): ...
