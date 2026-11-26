from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import subprocess
import sys
import threading

from .parser import demo, parse_firmware
from .onboarding import generate_prompt
from .protocol import ChannelSlot, RAM_RANGES, in_ram
from .storage import Storage, default_workspace, relative_firmware_path
from .transports import TransportManager


class Bridge:
    def __init__(self, storage=None):
        self.lock = threading.RLock()
        self.storage = storage or Storage()
        self.error = ''
        try:
            self.app_state = self.storage.read_app_state()
        except (ValueError, OSError) as error:
            self.app_state = dict(last_workspace=None, recent_workspaces=[], window_size=dict(width=1440, height=960))
            self.error = f'Global state could not be read: {error}'
        self.saved = dict(favorites=[], presets={})
        self.settings = dict(header='AA55', max_channels=12, ranges=RAM_RANGES, crc='CRC-16/MODBUS')
        self.firmware = None
        self.slots = []
        self.path = None
        self.stamp = None
        self.loading_stamp = None
        self.loading_path = None
        self.future = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.manager = TransportManager()
        self.window = None
        self.workspace_path = self.storage.path
        self.workspace_name = '默认工作区'
        self.transport_config = {}
        self.dirty = False
        self.save_error = ''
        self.save_timer = None
        self.save_generation = 0
        self.workspace_generation = 0
        global_error = self.error
        try:
            last = self.app_state['last_workspace']
            target = Path(last) if last and Path(last).is_file() else self.storage.path
            document = self.storage.read(target) if target.is_file() else default_workspace()
            self._activate_workspace(document, target)
        except (ValueError, OSError, TypeError) as error:
            # A broken file stays untouched; fallback uses a fresh in-memory workspace.
            self._activate_workspace(default_workspace(), None)
            self.error = f'Workspace could not be restored: {error}'
        if global_error and not self.error:
            self.error = global_error

    @staticmethod
    def validate_settings(value):
        header = bytes.fromhex(value['header'])
        maximum = int(value['max_channels'])
        ranges = [[int(a), int(b)] for a, b in value['ranges']]
        if len(header) != 2 or not 1 <= maximum <= 255 or not ranges or any(not 0 <= a < b <= 0x100000000 for a, b in ranges):
            raise ValueError('Use a two-byte header, 1–255 channels, and valid half-open RAM ranges.')
        return dict(header=header.hex().upper(), max_channels=maximum, ranges=ranges, crc='CRC-16/MODBUS')

    def persist(self):
        self.dirty = True
        self.save_error = ''
        self.save_generation += 1
        if self.save_timer:
            self.save_timer.cancel()
        self.save_timer = threading.Timer(.5, self._autosave, args=(self.save_generation,))
        self.save_timer.daemon = True
        self.save_timer.start()

    def _autosave(self, generation):
        with self.lock:
            if generation != self.save_generation:
                return
            try:
                self.flush()
            except (OSError, ValueError) as error:
                self.save_error = str(error)

    def workspace_document(self, target):
        return dict(schema_version=1, name=self.workspace_name,
                    axf_path=relative_firmware_path(self.path, target),
                    mcu_ram_ranges=self.settings['ranges'],
                    protocol={k: self.settings[k] for k in ('header', 'max_channels', 'crc')},
                    favorites=list(self.saved['favorites']),
                    presets={k: list(v) for k, v in self.saved['presets'].items()},
                    active_slots=list(self.slots), transport=self.transport_config)

    def _remember_workspace(self):
        if self.workspace_path:
            path = str(self.workspace_path)
            self.app_state['last_workspace'] = path
            self.app_state['recent_workspaces'] = [path] + [p for p in self.app_state['recent_workspaces'] if os.path.normcase(p) != os.path.normcase(path)][:4]
        self.storage.write_app_state(self.app_state)

    def flush(self):
        if self.save_timer:
            self.save_timer.cancel()
            self.save_timer = None
        if not self.dirty:
            return
        if not self.workspace_path:
            raise ValueError('Choose Save As to save this workspace.')
        try:
            self.storage.write(self.workspace_document(self.workspace_path), self.workspace_path)
            self._remember_workspace()
        except (OSError, ValueError) as error:
            self.save_error = str(error)
            raise
        self.dirty = False
        self.save_error = ''

    def remember_window_size(self, width, height):
        with self.lock:
            if width >= 200 and height >= 200:
                self.app_state['window_size'] = dict(width=int(width), height=int(height))

    def prepare_close(self):
        with self.lock:
            try:
                self.flush()
                self._remember_workspace()
                return True
            except (OSError, ValueError) as error:
                self.error = f'Could not save before closing: {error}'
                return False

    def close(self):
        try:
            with self.lock:
                self.flush()
                self._remember_workspace()
        finally:
            self.pool.shutdown(wait=False, cancel_futures=True)

    def _start_parse(self, path):
        stat = Path(path).stat()
        self.loading_path = str(Path(path).resolve())
        self.loading_stamp = (stat.st_mtime_ns, stat.st_size)
        self.future = self.pool.submit(parse_firmware, self.loading_path)

    def _activate_workspace(self, document, path):
        if self.future:
            self.future.cancel()
        self.future = None
        self.workspace_generation += 1
        self.workspace_path = Path(path).resolve() if path else None
        self.workspace_name = document['name']
        self.settings = self.validate_settings({**document['protocol'], 'ranges': document['mcu_ram_ranges']})
        self.saved = dict(favorites=list(document['favorites']), presets={k: list(v) for k, v in document['presets'].items()})
        self.slots = list(document['active_slots'])
        self.transport_config = document['transport']
        self.firmware, self.path, self.stamp = None, None, None
        self.error, self.save_error, self.dirty = '', '', False
        if document['axf_path']:
            firmware_path = Path(document['axf_path'])
            if not firmware_path.is_absolute():
                firmware_path = self.workspace_path.parent / firmware_path
            self.path = str(firmware_path.resolve())
            try:
                self._start_parse(self.path)
            except OSError as error:
                self.error = f'Firmware unavailable; workspace selections retained: {error}'

    def _workspace_dialog(self, save=False):
        if not self.window:
            raise ValueError('Enter a .tmws path in browser mode.')
        import webview
        options = dict(file_types=('Telemetry workspace (*.tmws)',))
        if save:
            options['save_filename'] = self.workspace_name + '.tmws'
        result = self.window.create_file_dialog(webview.FileDialog.SAVE if save else webview.FileDialog.OPEN, **options)
        if isinstance(result, (tuple, list)):
            return result[0] if result else None
        return result

    def _workspace_action(self, action, data):
        if action == 'workspace_info':
            return
        if action == 'workspace_reveal':
            if not self.workspace_path or not self.workspace_path.exists():
                raise ValueError('Save the workspace before locating it.')
            if sys.platform == 'win32':
                subprocess.Popen(['explorer.exe', '/select,', str(self.workspace_path)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', str(self.workspace_path)])
            else:
                subprocess.Popen(['xdg-open', str(self.workspace_path.parent)])
            return
        if action == 'workspace_save':
            self.flush()
            return
        path = data.get('path') or self._workspace_dialog(save=action != 'workspace_open')
        if not path:
            return
        target = Path(path).expanduser().resolve()
        if action != 'workspace_open' and target.suffix.lower() != '.tmws':
            target = target.with_suffix('.tmws')
        if target.suffix.lower() != '.tmws':
            raise ValueError('Choose a .tmws workspace file.')
        if action == 'workspace_open':
            document = self.storage.read(target)  # Validate fully before leaving current workspace.
            self.flush()
            self._activate_workspace(document, target)
        elif action == 'workspace_new':
            if target.exists():
                raise ValueError('A workspace already exists at this path. Choose a new filename.')
            name = data.get('name', target.stem).strip()
            document = default_workspace(name)
            self.flush()
            self.storage.write(document, target)
            self._activate_workspace(document, target)
        elif action == 'workspace_save_as':
            self.storage.write(self.workspace_document(target), target)
            self.workspace_path = target
            self.dirty, self.save_error = False, ''
            if self.save_timer:
                self.save_timer.cancel()
                self.save_timer = None
        else:
            raise ValueError('Unknown workspace action.')
        self._remember_workspace()

    def _frame(self):
        symbols = {s['path']: s for s in (self.firmware or {}).get('symbols', [])}
        missing = [p for p in self.slots if p not in symbols]
        if missing:
            raise ValueError('Missing channels: ' + ', '.join(missing))
        selected = [ChannelSlot(symbols[p]['address'], symbols[p]['type_id']) for p in self.slots]
        options = dict(header=bytes.fromhex(self.settings['header']), max_channels=self.settings['max_channels'], ranges=self.settings['ranges'])
        return selected, (self.firmware or {}).get('fingerprint', 0), options

    def snapshot(self):
        if self.future and self.future.done():
            pending, self.future = self.future, None
            try:
                loaded = pending.result()
                self.firmware = loaded
                self.stamp = self.loading_stamp
                self.path = self.loading_path
                self.error = ''
                self.persist()
            except Exception as error:
                self.error = str(error)
        changed = False
        if self.path and self.stamp:
            try:
                stat = Path(self.path).stat()
                changed = (stat.st_mtime_ns, stat.st_size) != self.stamp
            except OSError:
                changed = True
        firmware = None
        if self.firmware:
            firmware = {**self.firmware, 'symbols': [{**s, 'valid': in_ram(s['address'], s['size'], self.settings['ranges'])} for s in self.firmware['symbols']]}
        frame, frame_error = None, ''
        if self.slots:
            try:
                slots, fingerprint, options = self._frame()
                payload = self.manager.generate(slots, fingerprint, **options)
                frame = dict(hex=payload.hex(' ').upper(), c_array='{ ' + ', '.join(f'0x{b:02X}' for b in payload) + ' }',
                             python="bytes.fromhex('" + payload.hex(' ') + "')", size=len(payload), crc=f'0x{int.from_bytes(payload[-2:], "little"):04X}',
                             segments=[payload[:2].hex(' '), payload[2:3].hex(), payload[3:7].hex(' '), payload[7:8].hex()] +
                                      [payload[8+i*5:13+i*5].hex(' ') for i in range(len(slots))] + [payload[-2:].hex(' ')])
            except ValueError as error:
                frame_error = str(error)
        return dict(firmware=firmware, slots=self.slots, favorites=self.saved['favorites'], presets=self.saved['presets'],
                    settings=self.settings, loading=bool(self.future), changed=changed, error=self.error,
                    frame=frame, frame_error=frame_error, transport=self.manager.transport.get_status(), logs=list(self.manager.transport.log),
                    workspace=dict(name=self.workspace_name, path=str(self.workspace_path) if self.workspace_path else None,
                                   generation=self.workspace_generation, firmware_path=self.path,
                                   status='error' if self.save_error else 'pending' if self.dirty else 'saved',
                                   save_error=self.save_error, recent=self.app_state['recent_workspaces'],
                                   native_dialog=bool(self.window)))

    def call(self, action, data=None):
        with self.lock:
            try:
                if action == 'integration_prompt':
                    data = data or {}
                    return {'prompt': generate_prompt(data.get('kind', 'firmware'), self.snapshot(),
                                                     project=data.get('project', ''), mcu=data.get('mcu', ''),
                                                     link=data.get('link', ''), include_context=data.get('include_context', True))}
                self._action(action, data or {})
                return self.snapshot()
            except Exception as error:
                return {'request_error': str(error)}

    def _action(self, action, data):
        if action.startswith('workspace_'):
            return self._workspace_action(action, data)
        if action == 'state':
            return
        if action == 'demo':
            if self.future:
                raise ValueError('Wait for the current parse to finish.')
            self.firmware, self.path, self.stamp = demo(), None, None
            self.slots = ['g_imu.pitch_rad', 'g_imu.roll_rad', 'g_motor.target_rpm', 'g_system.state']
            self.error = ''
            self.persist()
        elif action in ('load', 'reload', 'browse'):
            if self.future:
                raise ValueError('A firmware file is already loading.')
            path = self.path if action == 'reload' else data.get('path')
            if action == 'browse':
                if not self.window:
                    raise ValueError('Enter a local path in browser mode, or use the desktop file picker.')
                import webview
                result = self.window.create_file_dialog(webview.FileDialog.OPEN, file_types=('Firmware (*.axf;*.elf)',))
                path = result[0] if result else None
                if not path:
                    return
            if not path or Path(path).suffix.lower() not in ('.axf', '.elf'):
                raise ValueError('Choose a local .axf or .elf file.')
            self._start_parse(path)
            self.error = ''
        elif action == 'favorite':
            path = data['path']
            favorites = self.saved['favorites']
            if path in favorites:
                favorites.remove(path)
            else:
                if path not in {s['path'] for s in (self.firmware or {}).get('symbols', [])}:
                    raise ValueError('Symbol no longer exists.')
                favorites.append(path)
            self.persist()
        elif action == 'slots':
            paths = data['paths']
            if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths) or len(set(paths)) != len(paths):
                raise ValueError('Channel paths must be unique strings.')
            if len(paths) > self.settings['max_channels']:
                raise ValueError('Maximum channel count reached.')
            self.slots = paths
            self.persist()
        elif action == 'save_preset':
            name = data['name'].strip()
            if not name or len(name) > 80:
                raise ValueError('Enter a preset name (1–80 characters).')
            self.saved['presets'][name] = list(self.slots)
            self.persist()
        elif action == 'load_preset':
            self.slots = list(self.saved['presets'][data['name']])
            self.persist()
        elif action == 'delete_preset':
            self.saved['presets'].pop(data['name'], None)
            self.persist()
        elif action == 'settings':
            settings = self.validate_settings(data)
            self.settings = settings
            self.persist()
        elif action in ('generate', 'send'):
            slots, fingerprint, options = self._frame()
            if action == 'send':
                if not self.manager.send(slots, fingerprint, **options):
                    raise ValueError('Mock transport is disconnected.')
            else:
                self.manager.generate(slots, fingerprint, **options)
        else:
            raise ValueError('Unknown action.')
