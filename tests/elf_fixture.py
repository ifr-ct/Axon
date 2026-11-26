"""Construct a small ARM ELF32 + DWARF4 fixture without a cross compiler."""
import struct


def build_elf(path):
    # Abbreviations: CU, variable, struct, member, base, array, subrange, typedef.
    abbrev = bytearray()
    def ab(code, tag, children, attributes):
        abbrev.extend(bytes([code, tag, children]))
        for attr, form in attributes:
            abbrev.extend(bytes([attr, form]))
        abbrev.extend(b'\0\0')
    ab(1, 0x11, 1, [(3, 8)])
    ab(2, 0x34, 0, [(3, 8), (2, 0x18), (0x49, 0x13)])
    ab(3, 0x13, 1, [(3, 8), (0x0B, 0x0B)])
    ab(4, 0x0D, 0, [(3, 8), (0x49, 0x13), (0x38, 0x0B)])
    ab(5, 0x24, 0, [(3, 8), (0x3E, 0x0B), (0x0B, 0x0B)])
    ab(6, 0x01, 1, [(0x49, 0x13)])
    ab(7, 0x21, 0, [(0x37, 0x0B)])
    ab(8, 0x16, 0, [(3, 8), (0x49, 0x13)])
    abbrev.append(0)
    info = bytearray(b'\0' * 4 + struct.pack('<HIB', 4, 0, 4))
    info.extend(b'\x01fixture.c\0')
    offsets, fixes = {}, []
    def reference(label):
        fixes.append((len(info), label))
        info.extend(b'\0' * 4)
    def variable(name, address, target):
        info.extend(b'\x02' + name.encode() + b'\0\x05\x03' + struct.pack('<I', address))
        reference(target)
    variable('g_imu', 0x20000000, 'imu')
    variable('g_values', 0x20000010, 'array')
    variable('g_counter', 0x20000030, 'alias')
    variable('g_armed', 0x20000034, 'bool')
    offsets['imu'] = len(info)
    info.extend(b'\x03IMU\0\x08')
    for name, offset in [('pitch', 0), ('roll', 4)]:
        info.extend(b'\x04' + name.encode() + b'\0')
        reference('float')
        info.append(offset)
    info.append(0)
    offsets['float'] = len(info)
    info.extend(b'\x05float\0\x04\x04')
    offsets['int'] = len(info)
    info.extend(b'\x05int\0\x05\x04')
    offsets['bool'] = len(info)
    info.extend(b'\x05bool\0\x02\x01')
    offsets['array'] = len(info)
    info.append(6)
    reference('float')
    info.extend(b'\x07\x02\x07\x03\0')  # float[2][3]
    offsets['alias'] = len(info)
    info.extend(b'\x08counter_t\0')
    reference('int')
    info.append(0)
    for offset, target in fixes:
        struct.pack_into('<I', info, offset, offsets[target])
    struct.pack_into('<I', info, 0, len(info) - 4)
    names = b'\0.shstrtab\0.debug_abbrev\0.debug_info\0.data\0.rodata\0.strtab\0.symtab\0'
    strings = b'\0g_telemetry_build_stamp\0'
    stamp = b'12345678901234567890\0'
    symbol = b'\0' * 16 + struct.pack('<IIIBBH', 1, 0x08000000, len(stamp), 0x11, 0, 5)
    sections = [('.shstrtab', 3, 0, 0, names, 0, 0), ('.debug_abbrev', 1, 0, 0, abbrev, 0, 0),
                ('.debug_info', 1, 0, 0, info, 0, 0), ('.data', 1, 3, 0x20000000, bytes(64), 0, 0),
                ('.rodata', 1, 2, 0x08000000, stamp, 0, 0),
                ('.strtab', 3, 0, 0, strings, 0, 0), ('.symtab', 2, 0, 0, symbol, 6, 16)]
    content = bytearray(52)
    headers = [bytes(40)]
    for name, kind, flags, addr, data, link, entry_size in sections:
        offset = len(content)
        content.extend(data)
        headers.append(struct.pack('<IIIIIIIIII', names.index(name.encode()), kind, flags, addr, offset, len(data), link, 1 if kind == 2 else 0, 1, entry_size))
    shoff = len(content)
    content.extend(b''.join(headers))
    content[:52] = struct.pack('<16sHHIIIIIHHHHHH', b'\x7fELF\x01\x01\x01' + bytes(9), 2, 40, 1, 0, 0, shoff, 0, 52, 0, 0, 40, len(headers), 1)
    path.write_bytes(content)
