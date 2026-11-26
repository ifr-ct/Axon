"""Pure little-endian configuration frame codec; RAM ends are exclusive."""
from dataclasses import dataclass
import struct

RAM_RANGES = [(0x20000000, 0x20020000), (0x24000000, 0x24080000), (0x30000000, 0x30048000)]
TYPE_SIZES = {0: 4, 1: 4, 2: 4, 3: 2, 4: 2, 5: 1, 6: 1}


@dataclass(frozen=True)
class ChannelSlot:
    address: int
    type_id: int


def crc16(data: bytes) -> int:
    value = 0xFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return value


def in_ram(address: int, size: int, ranges=RAM_RANGES) -> bool:
    return size > 0 and any(start <= address and address + size <= end for start, end in ranges)


def encode(slots: list[ChannelSlot], fingerprint: int, header=b'\xaa\x55', max_channels=12, ranges=RAM_RANGES) -> bytes:
    if len(header) != 2 or not 1 <= max_channels <= 255 or not 1 <= len(slots) <= max_channels:
        raise ValueError('Select 1 to MaxChannels slots and a two-byte header.')
    if not 0 <= fingerprint <= 0xFFFFFFFF:
        raise ValueError('Fingerprint must fit uint32.')
    body = header + struct.pack('<BIB', 1, fingerprint, len(slots))
    for slot in slots:
        if slot.type_id not in TYPE_SIZES or not 0 <= slot.address <= 0xFFFFFFFF:
            raise ValueError('Unsupported channel type or address.')
        if not in_ram(slot.address, TYPE_SIZES[slot.type_id], ranges):
            raise ValueError(f'Address 0x{slot.address:08X} exceeds configured RAM.')
        body += struct.pack('<IB', slot.address, slot.type_id)
    return body + struct.pack('<H', crc16(body))


def decode(payload: bytes, header=b'\xaa\x55', max_channels=12, ranges=RAM_RANGES):
    if len(payload) < 15 or payload[:2] != header or payload[2] != 1:
        raise ValueError('Invalid frame header, command, or length.')
    fingerprint, count = struct.unpack_from('<IB', payload, 3)
    if len(payload) != 10 + 5 * count or crc16(payload[:-2]) != int.from_bytes(payload[-2:], 'little'):
        raise ValueError('Frame length or CRC mismatch.')
    slots = [ChannelSlot(*struct.unpack_from('<IB', payload, 8 + i * 5)) for i in range(count)]
    encode(slots, fingerprint, header, max_channels, ranges)
    return fingerprint, slots
