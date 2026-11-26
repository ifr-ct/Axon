from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from telemetry.bridge import Bridge
from telemetry.protocol import ChannelSlot
from telemetry.storage import Storage
from telemetry.transports import SerialConfig, SerialTransport, TransportManager


class FakeSerial:
    def __init__(self):
        self.writes = []
        self.closed = False
        self.flushes = 0
        self.fail_write = False

    def write(self, payload):
        if self.fail_write:
            raise OSError('device removed')
        self.writes.append(bytes(payload))
        return len(payload)

    def flush(self):
        self.flushes += 1

    def close(self):
        self.closed = True


class SerialConfigTests(unittest.TestCase):
    def test_from_dict_defaults_and_normalization(self):
        self.assertEqual(SerialConfig.from_dict({}).to_dict(), dict(port='COM3', baudrate=115200, data_bits=8))
        self.assertEqual(SerialConfig.from_dict({'port':' COM7 ', 'baudrate':921600, 'data_bits':7}).to_dict(),
                         dict(port='COM7', baudrate=921600, data_bits=7))

    def test_invalid_values_are_rejected(self):
        for value in ({'port':''}, {'port':123}, {'baudrate':0}, {'baudrate':True},
                      {'baudrate':'115200'}, {'data_bits':4}, {'data_bits':5.0}, {'data_bits':9}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SerialConfig.from_dict(value)


class SerialTransportTests(unittest.TestCase):
    def test_connect_send_and_disconnect(self):
        fake = FakeSerial()
        with patch('telemetry.transports.serial_transport.serial.Serial', return_value=fake) as constructor:
            transport = SerialTransport()
            self.assertTrue(transport.connect(SerialConfig(port='COM7', baudrate=921600, data_bits=7)))
            self.assertTrue(transport.connected)
            constructor.assert_called_once_with(port='COM7', baudrate=921600, bytesize=7, parity='N',
                                                stopbits=1, timeout=0, write_timeout=1)
            self.assertIn('COM7', transport.get_status())
            self.assertTrue(transport.send(b'\xAA\x55\x01'))
            self.assertEqual(fake.writes, [b'\xAA\x55\x01'])
            self.assertEqual(fake.flushes, 1)
            transport.disconnect()
            self.assertTrue(fake.closed)
            self.assertFalse(transport.connected)
            self.assertEqual(transport.get_status(), 'Serial COM7 · Disconnected')

    def test_open_failure_is_reported(self):
        with patch('telemetry.transports.serial_transport.serial.Serial', side_effect=OSError('Access denied')):
            transport = SerialTransport()
            self.assertFalse(transport.connect(SerialConfig(port='COM9')))
            self.assertFalse(transport.connected)
            self.assertIn('Access denied', transport.error)

    def test_send_failure_closes_port(self):
        fake = FakeSerial()
        with patch('telemetry.transports.serial_transport.serial.Serial', return_value=fake):
            transport = SerialTransport()
            self.assertTrue(transport.connect(SerialConfig(port='COM7')))
            fake.fail_write = True
            self.assertFalse(transport.send(b'\xAA'))
            self.assertFalse(transport.connected)
            self.assertTrue(fake.closed)
            self.assertIn('device removed', transport.error)
            self.assertIn('Error', transport.get_status())

    def test_missing_pyserial_keeps_transport_disconnected(self):
        with patch('telemetry.transports.serial_transport.serial', None):
            transport = SerialTransport()
            self.assertFalse(transport.connect(SerialConfig()))
            self.assertFalse(transport.connected)
            self.assertIn('pyserial', transport.error)

    def test_list_serial_ports(self):
        ports = [SimpleNamespace(device='COM7', description='USB Serial', hwid='USB VID:PID'),
                 SimpleNamespace(device='COM3', description=None, hwid=None)]
        with patch('serial.tools.list_ports.comports', return_value=ports):
            from telemetry.transports import list_serial_ports
            self.assertEqual(list_serial_ports(), [
                dict(device='COM3', description='', hwid=''),
                dict(device='COM7', description='USB Serial', hwid='USB VID:PID'),
            ])


class TransportManagerTests(unittest.TestCase):
    def test_switches_between_mock_and_serial(self):
        manager = TransportManager()
        slots = [ChannelSlot(0x20000000, 0)]
        self.assertTrue(manager.send(slots, 0x12345678))
        self.assertEqual(len(manager.log), 1)
        self.assertEqual(manager.kind, 'mock')

        fake = FakeSerial()
        with patch('telemetry.transports.serial_transport.serial.Serial', return_value=fake):
            self.assertTrue(manager.connect('serial', {'port':'COM8', 'baudrate':57600, 'data_bits':8}))
            self.assertEqual(manager.kind, 'serial')
            self.assertTrue(manager.send(slots, 0x12345678))
            self.assertEqual(len(fake.writes), 1)
            self.assertEqual(len(manager.log), 2)

        self.assertTrue(manager.connect('mock'))
        self.assertEqual(manager.kind, 'mock')
        self.assertTrue(manager.transport.connected)

    def test_failed_open_is_reflected_in_state(self):
        manager = TransportManager()
        with patch('telemetry.transports.serial_transport.serial.Serial', side_effect=OSError('busy')):
            self.assertFalse(manager.connect('serial', {'port':'COM4'}))
        state = manager.state()
        self.assertEqual(state['kind'], 'serial')
        self.assertFalse(state['connected'])
        self.assertIn('busy', state['error'])
        self.assertFalse(manager.send([ChannelSlot(0x20000000, 0)], 0))


class BridgeSerialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(config_dir=Path(self.temp.name))
        self.bridge = Bridge(self.storage)
        self.bridge.call('demo')

    def tearDown(self):
        self.bridge.close()
        self.temp.cleanup()

    def connect(self, fake, port='COM8'):
        with patch('telemetry.transports.serial_transport.serial.Serial', return_value=fake):
            return self.bridge.call('transport_connect', {'kind':'serial',
                                  'config':{'port':port, 'baudrate':57600, 'data_bits':8}})

    def test_send_persists_serial_config_and_restores_as_mock(self):
        fake = FakeSerial()
        result = self.connect(fake)
        self.assertNotIn('request_error', result)
        self.assertTrue(result['transport']['connected'])
        self.assertEqual(result['transport']['kind'], 'serial')
        self.assertEqual(result['transport']['serial']['port'], 'COM8')

        sent = self.bridge.call('send')
        self.assertNotIn('request_error', sent)
        self.assertEqual(len(sent['logs']), 1)
        self.assertEqual(fake.writes, [bytes.fromhex(sent['frame']['hex'])])
        self.bridge.flush()
        self.assertEqual(self.storage.read()['transport']['serial']['port'], 'COM8')
        self.bridge.close()
        self.assertTrue(fake.closed)

        restored = Bridge(self.storage)
        try:
            state = restored.call('state')
            self.assertEqual(state['transport']['kind'], 'mock')
            self.assertTrue(state['transport']['connected'])
            self.assertEqual(state['transport']['serial']['port'], 'COM8')
            self.assertEqual(state['logs'], [])
        finally:
            restored.close()

    def test_open_failure_is_visible_and_send_is_blocked(self):
        with patch('telemetry.transports.serial_transport.serial.Serial', side_effect=OSError('Access denied')):
            result = self.bridge.call('transport_connect', {'kind':'serial',
                                      'config':{'port':'COM9', 'baudrate':115200, 'data_bits':8}})
        self.assertNotIn('request_error', result)
        self.assertEqual(result['transport']['kind'], 'serial')
        self.assertFalse(result['transport']['connected'])
        self.assertIn('Access denied', result['transport']['error'])
        self.assertIn('request_error', self.bridge.call('send'))

    def test_invalid_config_is_rejected_without_switching(self):
        result = self.bridge.call('transport_connect', {'kind':'serial',
                                  'config':{'port':'COM9', 'baudrate':0, 'data_bits':8}})
        self.assertIn('request_error', result)
        self.assertEqual(self.bridge.manager.kind, 'mock')
        self.assertTrue(self.bridge.manager.transport.connected)

    def test_workspace_switch_closes_serial_and_resets_mock(self):
        fake = FakeSerial()
        result = self.connect(fake)
        self.assertTrue(result['transport']['connected'])
        target = Path(self.temp.name) / 'next.tmws'
        result = self.bridge.call('workspace_new', {'path':str(target), 'name':'Next'})
        self.assertNotIn('request_error', result)
        self.assertTrue(fake.closed)
        self.assertEqual(result['transport']['kind'], 'mock')
        self.assertTrue(result['transport']['connected'])
        self.assertEqual(result['transport']['serial']['port'], 'COM3')

    def test_switch_to_mock_closes_serial_and_keeps_config(self):
        fake = FakeSerial()
        self.connect(fake)
        result = self.bridge.call('transport_connect', {'kind':'mock'})
        self.assertNotIn('request_error', result)
        self.assertTrue(fake.closed)
        self.assertEqual(result['transport']['kind'], 'mock')
        self.assertTrue(result['transport']['connected'])
        self.assertEqual(result['transport']['serial']['port'], 'COM8')

    def test_serial_ports_action(self):
        ports = [SimpleNamespace(device='COM7', description='USB Serial', hwid='USB')]
        with patch('serial.tools.list_ports.comports', return_value=ports):
            result = self.bridge.call('serial_ports')
        self.assertEqual(result['ports'], [dict(device='COM7', description='USB Serial', hwid='USB')])


if __name__ == '__main__':
    unittest.main()
