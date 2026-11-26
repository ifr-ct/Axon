import json
from pathlib import Path
import tempfile
import time
import unittest

from telemetry.bridge import Bridge
from telemetry.protocol import ChannelSlot, crc16, decode, encode, in_ram
from telemetry.storage import Storage
from telemetry.parser import parse_firmware
from elf_fixture import build_elf


class ProtocolTests(unittest.TestCase):
    def test_modbus_reference_vector(self):
        self.assertEqual(crc16(b'123456789'), 0x4B37)

    def test_wire_layout_and_roundtrip(self):
        slots = [ChannelSlot(0x200014A0, 0), ChannelSlot(0x30000004, 3)]
        frame = encode(slots, 0xA3F812C0)
        self.assertEqual(frame[:-2].hex(), 'aa5501c012f8a302a0140020000400003003')
        self.assertEqual(len(frame), 20)
        self.assertEqual(frame[-2:], crc16(frame[:-2]).to_bytes(2, 'little'))
        self.assertEqual(decode(frame), (0xA3F812C0, slots))

    def test_ram_full_extent(self):
        self.assertTrue(in_ram(0x2001FFFC, 4))
        self.assertFalse(in_ram(0x2001FFFE, 4))
        self.assertFalse(in_ram(0x20020000, 1))

    def test_invalid_slots_and_frame(self):
        for slots in ([], [ChannelSlot(0x60000000, 0)], [ChannelSlot(0x20000000, 7)], [ChannelSlot(0x20000000, 0)] * 13):
            with self.assertRaises(ValueError):
                encode(slots, 0)
        valid = encode([ChannelSlot(0x20000000, 0)], 42)
        for malformed in (valid[:-1], valid + b'\0', valid[:-1] + bytes([valid[-1] ^ 1]), b'bad'):
            with self.assertRaises(ValueError):
                decode(malformed)

    def test_custom_header_and_ranges(self):
        options = dict(header=b'\x12\x34', ranges=[(0x1000, 0x1100)], max_channels=1)
        frame = encode([ChannelSlot(0x1000, 6)], 1, **options)
        self.assertEqual(decode(frame, **options)[0], 1)


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Storage(Path(self.temp.name) / 'settings.json')
        self.bridge = Bridge(self.store)
        self.bridge.call('demo')

    def tearDown(self):
        self.bridge.close()
        self.temp.cleanup()

    def test_path_only_persistence_and_rebinding(self):
        path = 'g_imu.pitch_rad'
        self.bridge.call('favorite', {'path':path})
        self.bridge.call('save_preset', {'name':'test'})
        self.bridge.flush()
        data = json.loads(self.store.path.read_text(encoding='utf-8'))
        self.assertEqual(data['favorites'], [path])
        self.assertNotIn('address', json.dumps(data))
        self.bridge.firmware['symbols'][0]['address'] += 16
        frame = bytes.fromhex(self.bridge.call('state')['frame']['hex'])
        self.assertEqual(decode(frame)[1][0].address, 0x200014B0)
        self.bridge.firmware['symbols'].pop(0)
        result = self.bridge.call('state')
        self.assertIn(path, result['favorites'])
        self.assertIsNone(result['frame'])
        self.assertIn('Missing', result['frame_error'])

    def test_preset_order_and_mock_send(self):
        self.bridge.call('slots', {'paths':['g_system.state', 'g_imu.pitch_rad']})
        self.bridge.call('save_preset', {'name':'ordered'})
        self.bridge.call('slots', {'paths':[]})
        result = self.bridge.call('load_preset', {'name':'ordered'})
        self.assertEqual(result['slots'], ['g_system.state', 'g_imu.pitch_rad'])
        self.assertEqual(len(self.bridge.call('send')['logs']), 1)

    def test_settings_validation(self):
        result = self.bridge.call('settings', {'header':'AA', 'max_channels':0, 'ranges':[]})
        self.assertIn('request_error', result)
        self.assertEqual(self.bridge.settings['header'], 'AA55')

    def test_invalid_firmware_keeps_current_symbols(self):
        path = Path(self.temp.name) / 'bad.axf'
        path.write_bytes(b'not an elf')
        self.bridge.call('load', {'path':str(path)})
        for _ in range(100):
            result = self.bridge.call('state')
            if not result['loading']:
                break
            time.sleep(.01)
        self.assertTrue(result['error'])
        self.assertEqual(result['firmware']['name'], 'demo_stm32h7.axf')


class ParserTests(unittest.TestCase):
    def test_arm_dwarf_struct_array_typedef_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.axf'
            build_elf(path)
            result = parse_firmware(path)
            symbols = {s['path']:s for s in result['symbols']}
            self.assertEqual(result['fingerprint'], 0x12345678)
            self.assertEqual(result['fingerprint_source'], 'g_fw_fingerprint')
            self.assertEqual(symbols['g_imu.roll']['address'], 0x20000004)
            self.assertEqual(symbols['g_values[1][2]']['address'], 0x20000024)
            self.assertEqual(symbols['g_counter']['type_id'], 1)
            self.assertEqual(symbols['g_armed']['type'], 'bool')
            self.assertEqual(symbols['g_armed']['type_id'], 6)
            payload = encode([ChannelSlot(symbols['g_armed']['address'], 6)], result['fingerprint'])
            self.assertEqual(decode(payload)[1][0], ChannelSlot(0x20000034, 6))
            self.assertEqual(len(symbols), 10)
            self.assertEqual(result['warnings'], [])

    def test_file_watcher_and_async_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.axf'
            build_elf(path)
            bridge = Bridge(Storage(Path(directory) / 'settings.json'))
            try:
                bridge.call('load', {'path':str(path)})
                bridge.future.result(timeout=5)
                self.assertFalse(bridge.call('state')['loading'])
                path.write_bytes(path.read_bytes() + b'new build')
                self.assertTrue(bridge.call('state')['changed'])
            finally:
                bridge.close()


if __name__ == '__main__':
    unittest.main()
