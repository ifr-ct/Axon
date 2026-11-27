import json
from concurrent.futures import Future
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from telemetry.bridge import Bridge
from telemetry.storage import Storage, atomic_write, default_workspace, relative_firmware_path
from elf_fixture import build_elf


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Storage(config_dir=self.root / 'config')
        self.bridge = Bridge(self.store)

    def tearDown(self):
        # Tests may deliberately leave an unwritable/unsaved workspace.
        self.bridge.watch_stop.set()
        if self.bridge.save_timer:
            self.bridge.save_timer.cancel()
        self.bridge.pool.shutdown(wait=True)
        self.temp.cleanup()

    def action(self, action, data=None):
        result = self.bridge.call(action, data)
        self.assertNotIn('request_error', result, result)
        return result

    def complete_parse(self, bridge=None):
        bridge = bridge or self.bridge
        if bridge.future:
            bridge.future.result(timeout=5)
        return bridge.call('state')

    def test_project_isolation_relative_paths_and_startup_restore(self):
        project = self.root / 'robot'
        project.mkdir()
        firmware = project / 'build.axf'
        build_elf(firmware)
        target = project / 'robot.axon'
        self.action('workspace_new', {'path':str(target), 'name':'机器人'})
        self.action('load', {'path':str(firmware)})
        self.complete_parse()
        self.action('favorite', {'path':'g_armed'})
        self.action('slots', {'paths':['g_counter', 'g_armed']})
        self.action('save_preset', {'name':'Flags'})
        self.action('settings', {'header':'BB66', 'max_channels':8, 'ranges':[[0x20000000, 0x20000100]]})
        other = self.root / 'other.axon'
        self.action('workspace_new', {'path':str(other), 'name':'Other'})
        document = self.store.read(target)
        self.assertEqual(document['axf_path'], 'build.axf')
        self.assertEqual(document['favorites'], ['g_armed'])
        self.assertEqual(document['active_slots'], ['g_counter', 'g_armed'])
        self.assertEqual(document['transport'], {})
        self.assertEqual(self.bridge.slots, [])
        self.assertEqual(self.bridge.saved['favorites'], [])
        self.action('workspace_open', {'path':str(target)})
        self.complete_parse()
        self.bridge.remember_window_size(1234, 876)
        self.bridge.close()
        restored = Bridge(Storage(config_dir=self.root / 'config'))
        try:
            result = self.complete_parse(restored)
            self.assertEqual(result['workspace']['name'], '机器人')
            self.assertEqual(result['slots'], ['g_counter', 'g_armed'])
            self.assertEqual(result['favorites'], ['g_armed'])
            self.assertEqual(result['settings']['header'], 'BB66')
            self.assertEqual(restored.app_state['window_size'], dict(width=1234, height=876))
            self.assertEqual(result['firmware']['fingerprint'], zlib.crc32(b'12345678901234567890'))
        finally:
            restored.close()

    def test_recent_limit_and_duplicate_removal(self):
        targets = [self.root / f'project-{i}.axon' for i in range(7)]
        for target in targets:
            self.action('workspace_new', {'path':str(target)})
        self.action('workspace_open', {'path':str(targets[3])})
        recent = self.store.read_app_state()['recent_workspaces']
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[0], str(targets[3]))
        self.assertEqual(len(set(recent)), 5)

    def test_autosave_debounce_coalesces_and_ignores_old_callbacks(self):
        with patch('telemetry.bridge.threading.Timer') as timer, patch.object(self.store, 'write', wraps=self.store.write) as write:
            self.action('demo')
            first_callback = timer.call_args.args[1]
            first_args = timer.call_args.kwargs['args']
            self.action('slots', {'paths':['g_system.armed']})
            self.assertEqual(timer.call_args.args[0], .5)
            first_callback(*first_args)
            write.assert_not_called()
            timer.call_args.args[1](*timer.call_args.kwargs['args'])
            self.assertEqual(write.call_count, 1)
            self.assertEqual(self.store.read()['active_slots'], ['g_system.armed'])
            self.assertFalse(self.bridge.dirty)

    def test_real_timer_saves_without_polling(self):
        saved = threading.Event()
        original = self.store.write
        def write(*args, **kwargs):
            original(*args, **kwargs)
            saved.set()
        with patch.object(self.store, 'write', side_effect=write):
            self.action('demo')
            self.assertTrue(saved.wait(3), '500ms autosave did not run')
        with self.bridge.lock:
            self.assertFalse(self.bridge.dirty)

    def test_save_as_rebases_firmware_and_preserves_selections(self):
        firmware = self.root / 'robot.axf'
        build_elf(firmware)
        self.action('load', {'path':str(firmware)})
        self.complete_parse()
        self.action('slots', {'paths':['g_armed']})
        target = self.root / 'nested' / 'copy.axon'
        self.action('workspace_save_as', {'path':str(target)})
        document = self.store.read(target)
        self.assertEqual(document['axf_path'], str(Path('..') / 'robot.axf'))
        self.assertEqual(document['active_slots'], ['g_armed'])
        self.assertEqual(self.store.read_app_state()['last_workspace'], str(target))

    def test_cross_drive_falls_back_to_absolute(self):
        firmware = str((self.root / 'build.axf').resolve())
        with patch('telemetry.storage.os.path.relpath', side_effect=ValueError('different drive')):
            self.assertEqual(relative_firmware_path(firmware, self.root / 'robot.axon'), firmware)

    def test_atomic_failure_preserves_original_and_cleans_temp(self):
        target = self.root / 'atomic.axon'
        atomic_write(target, {'original':True})
        before = target.read_bytes()
        with patch('telemetry.storage.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                atomic_write(target, {'original':False})
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_save_failure_is_visible_and_blocks_switch(self):
        with patch('telemetry.bridge.threading.Timer'), patch.object(self.store, 'write', side_effect=PermissionError('read only')):
            self.action('demo')
            self.bridge._autosave(self.bridge.save_generation)
            self.assertEqual(self.action('state')['workspace']['status'], 'error')
            self.assertFalse(self.bridge.prepare_close())
            result = self.bridge.call('workspace_new', {'path':str(self.root / 'new.axon')})
            self.assertIn('request_error', result)
            self.assertTrue(self.bridge.dirty)

    def test_save_as_recovers_from_unwritable_original(self):
        original_write = self.store.write
        def write(data, path=None):
            if Path(path) == self.store.path:
                raise PermissionError('original is read only')
            return original_write(data, path)
        self.action('demo')
        target = self.root / 'recovered.axon'
        with patch.object(self.store, 'write', side_effect=write):
            self.bridge._autosave(self.bridge.save_generation)
            self.assertTrue(self.bridge.save_error)
            result = self.action('workspace_save_as', {'path':str(target)})
            self.assertEqual(result['workspace']['status'], 'saved')
        self.assertEqual(self.store.read(target)['active_slots'], self.bridge.slots)

    def test_switch_during_parse_discards_old_result(self):
        pending = Future()
        pending.set_running_or_notify_cancel()
        self.bridge.future = pending
        target = self.root / 'next.axon'
        self.action('workspace_new', {'path':str(target), 'name':'Next'})
        pending.set_result(dict(name='stale.axf', symbols=[], fingerprint=123))
        result = self.action('state')
        self.assertEqual(result['workspace']['name'], 'Next')
        self.assertIsNone(result['firmware'])

    def test_bad_workspace_leaves_current_state_and_file_intact(self):
        self.action('demo')
        before = self.bridge.slots[:]
        target = self.root / 'invalid.axon'
        target.write_text('{bad json', encoding='utf-8')
        result = self.bridge.call('workspace_open', {'path':str(target)})
        self.assertIn('request_error', result)
        self.assertEqual(self.bridge.slots, before)
        self.assertEqual(target.read_text(), '{bad json')

    def test_missing_workspace_startup_falls_back(self):
        self.store.write_app_state(dict(last_workspace=str(self.root / 'gone.axon'), recent_workspaces=[], window_size={}))
        restored = Bridge(self.store)
        try:
            self.assertEqual(restored.workspace_name, '默认工作区')
            self.assertFalse(restored.future)
            self.assertEqual(restored.slots, [])
        finally:
            restored.close()

    def test_missing_firmware_retains_workspace_paths(self):
        target = self.root / 'missing.axon'
        document = default_workspace('missing firmware')
        document.update(axf_path='gone.axf', favorites=['g_armed'], active_slots=['g_armed'])
        self.store.write(document, target)
        result = self.action('workspace_open', {'path':str(target)})
        self.assertFalse(result['loading'])
        self.assertEqual(result['favorites'], ['g_armed'])
        self.assertEqual(result['slots'], ['g_armed'])
        self.assertIn('unavailable', result['error'])
        self.assertEqual(result['workspace']['name'], 'missing firmware')

    def test_unknown_schema_rejected(self):
        target = self.root / 'future.axon'
        data = default_workspace()
        data['schema_version'] = 99
        target.write_text(json.dumps(data), encoding='utf-8')
        result = self.bridge.call('workspace_open', {'path':str(target)})
        self.assertIn('schema_version', result['request_error'])

    def test_legacy_tmws_remains_readable_and_saves_in_place(self):
        target = self.root / 'legacy.tmws'
        self.store.write(default_workspace('Legacy'), target)
        result = self.action('workspace_open', {'path':str(target)})
        self.assertEqual(result['workspace']['name'], 'Legacy')
        self.assertEqual(Path(result['workspace']['path']).suffix, '.tmws')
        self.action('settings', {'header':'AA55', 'max_channels':6, 'ranges':[[0x20000000, 0x20000100]]})
        self.bridge.flush()
        self.assertEqual(self.store.read(target)['protocol']['max_channels'], 6)
        self.assertFalse(target.with_suffix('.axon').exists())

    def test_new_workspace_converts_tmws_suffix_to_axon(self):
        target = self.root / 'new.tmws'
        result = self.action('workspace_new', {'path':str(target), 'name':'New'})
        expected = target.with_suffix('.axon')
        self.assertEqual(Path(result['workspace']['path']), expected)
        self.assertTrue(expected.exists())
        self.assertFalse(target.exists())

    def test_writable_ram_ranges_are_optional_and_isolated(self):
        target = self.root / 'writable.axon'
        document = default_workspace('Writable')
        document['writable_ram_ranges'] = [[0x20000000, 0x20000100]]
        self.store.write(document, target)
        self.action('workspace_open', {'path':str(target)})
        self.assertEqual(self.bridge.writable_ram_ranges, [[0x20000000, 0x20000100]])
        self.assertEqual(self.bridge.settings['ranges'], document['mcu_ram_ranges'])
        self.bridge.flush()
        self.assertEqual(self.store.read(target)['writable_ram_ranges'], [[0x20000000, 0x20000100]])

        legacy = default_workspace('No writable')
        del legacy['writable_ram_ranges']
        self.store.write(legacy, target)
        self.action('workspace_open', {'path':str(target)})
        self.assertEqual(self.bridge.writable_ram_ranges, [])

        invalid = default_workspace('Invalid')
        invalid['writable_ram_ranges'] = [[0x20000000, 0x20000000]]
        with self.assertRaises(ValueError):
            self.store.write(invalid, target)

    def test_default_workspace_falls_back_to_legacy_tmws(self):
        config = self.root / 'legacy-config'
        legacy = Storage(config_dir=config)
        legacy.write(default_workspace('Legacy default'), legacy.legacy_path)
        restored = Bridge(legacy)
        try:
            self.assertEqual(restored.workspace_name, 'Legacy default')
            self.assertEqual(Path(restored.workspace_path).suffix, '.tmws')
        finally:
            restored.close()


if __name__ == '__main__':
    unittest.main()
