from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from telemetry.bridge import Bridge
from telemetry.onboarding import TITLES, generate_prompt
from telemetry.parser import demo
from telemetry.protocol import ChannelSlot, RAM_RANGES, crc16, encode
from telemetry.storage import Storage


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        payload = encode([ChannelSlot(0x20000034, 6)], 0x12345678)
        self.snapshot = dict(settings=dict(header='AA55', max_channels=12, ranges=RAM_RANGES),
                             workspace=dict(name='客户项目'), firmware=dict(name='customer.axf', fingerprint=0x12345678,
                             fingerprint_source='CRC32(g_telemetry_build_stamp)'), slots=['g_armed'],
                             frame=dict(hex=payload.hex(' ').upper()), loading=False, changed=False)

    def test_templates_match_real_protocol_and_include_valid_frame(self):
        for kind in TITLES:
            with self.subTest(kind=kind):
                prompt = generate_prompt(kind, self.snapshot)
                self.assertIn('10 + 5 × N', prompt)
                self.assertIn('4 通道为 30 bytes', prompt)
                self.assertIn('0xA001', prompt)
                self.assertIn(f'0x{crc16(b"123456789"):04X}', prompt)
                self.assertIn('type 6', prompt)
                self.assertIn('没有真实串口/TCP I/O', prompt)
                self.assertIn(self.snapshot['frame']['hex'], prompt)
                self.assertIn('0x12345678', prompt)

    def test_custom_protocol_settings_are_used(self):
        self.snapshot['settings'] = dict(header='12 34', max_channels=8, ranges=[(0x1000, 0x1100)])
        self.snapshot['frame'] = None
        prompt = generate_prompt('firmware', self.snapshot)
        self.assertIn('Header: 2 bytes = 12 34', prompt)
        self.assertIn('合法范围 1..8', prompt)
        self.assertIn('[0x00001000, 0x00001100)', prompt)
        self.assertNotIn('0x20020000', prompt)

    def test_generic_mode_excludes_customer_firmware_and_frame(self):
        prompt = generate_prompt('firmware', self.snapshot, include_context=False)
        for private in ('客户项目', 'customer.axf', '0x12345678', 'g_armed', self.snapshot['frame']['hex']):
            self.assertNotIn(private, prompt)
        self.assertIn('Header: 2 bytes = AA 55', prompt)

    def test_demo_never_supplies_fake_hardware_frame(self):
        self.snapshot['firmware'] = demo()
        prompt = generate_prompt('verification', self.snapshot)
        self.assertIn('演示数据，不得用于真实硬件', prompt)
        self.assertNotIn(self.snapshot['frame']['hex'], prompt)

    def test_stale_or_loading_frame_is_excluded(self):
        for field in ('loading', 'changed'):
            with self.subTest(field=field):
                snapshot = deepcopy(self.snapshot)
                snapshot[field] = True
                prompt = generate_prompt('verification', snapshot)
                self.assertIn('旧指纹和槽位可能失效', prompt)
                self.assertNotIn(snapshot['frame']['hex'], prompt)

    def test_missing_firmware_works_and_inputs_are_unchanged(self):
        self.snapshot['firmware'] = None
        self.snapshot['frame'] = None
        before = deepcopy(self.snapshot)
        prompt = generate_prompt('symbols', self.snapshot, mcu='STM32H743 / Keil')
        self.assertIn('STM32H743 / Keil', prompt)
        self.assertIn('没有可用配置帧样例', prompt)
        self.assertEqual(self.snapshot, before)

    def test_invalid_template_or_inputs_are_rejected(self):
        for kwargs in (dict(kind='unknown'), dict(kind='firmware', project='a' * 1001),
                       dict(kind='firmware', include_context='false')):
            with self.assertRaises(ValueError):
                generate_prompt(snapshot=self.snapshot, **kwargs)

    def test_bridge_generates_without_mutating_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Bridge(Storage(config_dir=Path(directory)))
            try:
                before = bridge.workspace_document(bridge.workspace_path)
                result = bridge.call('integration_prompt', {'kind':'firmware', 'project':'客户工程'})
                self.assertIn('客户工程', result['prompt'])
                self.assertEqual(bridge.workspace_document(bridge.workspace_path), before)
                self.assertFalse(bridge.dirty)
                self.assertFalse(bridge.storage.path.exists())
            finally:
                bridge.close()


if __name__ == '__main__':
    unittest.main()
