"""Real serial transport built on pyserial; receiving remains for later work."""
from dataclasses import dataclass
import threading

from .base import BaseTransport

try:
    import serial
except ModuleNotFoundError:  # Keep mock mode usable before dependencies are installed.
    serial = None


@dataclass
class SerialConfig:
    port: str = 'COM3'
    baudrate: int = 115200
    data_bits: int = 8

    @classmethod
    def from_dict(cls, value=None):
        if value is None:
            value = {}
        if isinstance(value, cls):
            value = value.to_dict()
        if not isinstance(value, dict):
            raise ValueError('Serial settings must be an object.')
        return cls(port=value.get('port', cls.port), baudrate=value.get('baudrate', cls.baudrate),
                   data_bits=value.get('data_bits', cls.data_bits)).validated()

    def validated(self):
        if not isinstance(self.port, str) or not self.port.strip() or len(self.port) > 260:
            raise ValueError('Serial port must be a non-empty string of at most 260 characters.')
        if type(self.baudrate) is not int or not 1 <= self.baudrate <= 10_000_000:
            raise ValueError('Baud rate must be an integer between 1 and 10000000.')
        if type(self.data_bits) is not int or self.data_bits not in (5, 6, 7, 8):
            raise ValueError('Data bits must be 5, 6, 7, or 8.')
        return type(self)(port=self.port.strip(), baudrate=self.baudrate, data_bits=self.data_bits)

    def to_dict(self):
        return dict(port=self.port, baudrate=self.baudrate, data_bits=self.data_bits)


class SerialTransport(BaseTransport):
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()
        self.port = None
        self.config = None

    def connect(self, config):
        if serial is None:
            self.connected = False
            self.error = 'pyserial is not installed. Run: python -m pip install -r requirements.txt'
            return False
        try:
            config = SerialConfig.from_dict(config)
        except ValueError as error:
            self.error = str(error)
            return False
        with self.lock:
            self._close_locked()
            self.config = config
            self.error = ''
            try:
                self.port = serial.Serial(port=config.port, baudrate=config.baudrate,
                                          bytesize=config.data_bits, parity=serial.PARITY_NONE,
                                          stopbits=serial.STOPBITS_ONE, timeout=0, write_timeout=1)
            except (serial.SerialException, OSError, ValueError) as error:
                self.port = None
                self.connected = False
                self.error = f'Cannot open serial port {config.port}: {error}'
                return False
            self.connected = True
            return True

    def _close_locked(self):
        port, self.port = self.port, None
        self.connected = False
        if port:
            try:
                port.close()
            except (serial.SerialException, OSError):
                pass

    def disconnect(self):
        with self.lock:
            self._close_locked()
            self.error = ''

    def send(self, payload: bytes) -> bool:
        with self.lock:
            if not self.connected or not self.port:
                self.error = 'Serial port is not connected.'
                return False
            try:
                written = self.port.write(payload)
                if written != len(payload):
                    raise OSError(f'wrote {written} of {len(payload)} bytes')
                self.port.flush()
            except (serial.SerialException, OSError) as error:
                self.error = f'Serial send failed: {error}'
                self._close_locked()
                return False
            self.error = ''
            return True

    def get_status(self):
        if self.connected and self.config:
            return f'Serial {self.config.port} @ {self.config.baudrate} · Connected'
        if self.config:
            return f'Serial {self.config.port} · {"Error" if self.error else "Disconnected"}'
        return 'Serial disconnected'


def list_serial_ports():
    if serial is None:
        raise ValueError('pyserial is not installed. Run: python -m pip install -r requirements.txt')
    from serial.tools import list_ports
    try:
        ports = sorted(list_ports.comports(), key=lambda item: item.device)
        return [dict(device=port.device, description=port.description or '', hwid=port.hwid or '') for port in ports]
    except (serial.SerialException, OSError, ValueError) as error:
        raise ValueError(f'Cannot enumerate serial ports: {error}') from error
