"""Two-layer UTF-8 JSON persistence: global state and portable workspaces."""
import json
import os
from pathlib import Path
import tempfile

from .protocol import RAM_RANGES


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def default_workspace(name='默认工作区') -> dict:
    return dict(schema_version=1, name=name, axf_path='', mcu_ram_ranges=[list(r) for r in RAM_RANGES],
                protocol=dict(header='AA55', max_channels=12, crc='CRC-16/MODBUS'),
                favorites=[], presets={}, active_slots=[], transport={})


def validate_workspace(data: dict) -> dict:
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('Unsupported workspace schema_version; expected 1.')
    if not isinstance(data.get('name'), str) or not data['name'].strip() or len(data['name']) > 120:
        raise ValueError('Workspace name must contain 1–120 characters.')
    if not isinstance(data.get('axf_path'), str):
        raise ValueError('Workspace axf_path must be a string.')
    for field in ('favorites', 'active_slots'):
        paths = data.get(field)
        if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths) or len(paths) != len(set(paths)):
            raise ValueError(f'{field} must contain unique symbol paths.')
    presets = data.get('presets')
    if not isinstance(presets, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, list)
            and all(isinstance(p, str) and p for p in v) and len(v) == len(set(v)) for k, v in presets.items()):
        raise ValueError('Presets must contain named lists of unique symbol paths.')
    protocol = data.get('protocol')
    if not isinstance(protocol, dict) or protocol.get('crc') != 'CRC-16/MODBUS':
        raise ValueError('Only CRC-16/MODBUS is supported.')
    header, maximum = protocol.get('header'), protocol.get('max_channels')
    if not isinstance(header, str) or len(bytes.fromhex(header)) != 2 or type(maximum) is not int or not 1 <= maximum <= 255:
        raise ValueError('Use a two-byte header and 1–255 maximum channels.')
    ranges = data.get('mcu_ram_ranges')
    if not isinstance(ranges, list) or not ranges or not all(isinstance(r, list) and len(r) == 2
            and all(type(n) is int for n in r) and 0 <= r[0] < r[1] <= 0x100000000 for r in ranges):
        raise ValueError('Invalid half-open MCU RAM ranges.')
    if not isinstance(data.get('transport'), dict):
        raise ValueError('Workspace transport must be an object.')
    return data


def relative_firmware_path(firmware: str | None, workspace_path: Path) -> str:
    if not firmware:
        return ''
    try:
        return os.path.relpath(Path(firmware).resolve(), workspace_path.resolve().parent)
    except ValueError:
        return str(Path(firmware).resolve())


class Storage:
    def __init__(self, path=None, config_dir=None):
        self.directory = Path(config_dir) if config_dir else Path(path).parent if path else Path.home() / '.axf_telemetry'
        self.path = Path(path).resolve() if path else (self.directory / 'default.tmws').resolve()
        self.app_state_path = self.directory / 'app_state.json'

    def read(self, path=None):
        target = Path(path) if path else self.path
        return validate_workspace(json.loads(target.read_text(encoding='utf-8')))

    def write(self, data, path=None):
        atomic_write(Path(path) if path else self.path, validate_workspace(data))

    def read_app_state(self):
        default = dict(last_workspace=None, recent_workspaces=[], window_size=dict(width=1440, height=960))
        if not self.app_state_path.exists():
            return default
        data = json.loads(self.app_state_path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or (data.get('last_workspace') is not None and not isinstance(data.get('last_workspace'), str)):
            raise ValueError('Invalid global app state.')
        recent = data.get('recent_workspaces', [])
        if not isinstance(recent, list) or not all(isinstance(p, str) for p in recent):
            raise ValueError('Invalid recent workspaces.')
        default.update(last_workspace=data.get('last_workspace'), recent_workspaces=list(dict.fromkeys(recent))[:5])
        size = data.get('window_size', {})
        if isinstance(size, dict) and all(type(size.get(k)) is int and 200 <= size[k] <= 16384 for k in ('width', 'height')):
            default['window_size'] = size
        return default

    def write_app_state(self, data):
        atomic_write(self.app_state_path, data)
