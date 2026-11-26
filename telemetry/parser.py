"""Resolve statically located DWARF variables without guessing dynamic locations."""
from collections import Counter
from io import BytesIO
from pathlib import Path
import zlib

TYPE_MAP = {(2, 1): (6, 'bool'), (4, 4): (0, 'float'), (5, 4): (1, 'int32'), (7, 4): (2, 'uint32'),
            (5, 2): (3, 'int16'), (7, 2): (4, 'uint16'), (5, 1): (5, 'int8'),
            (6, 1): (5, 'int8'), (7, 1): (6, 'uint8'), (8, 1): (6, 'uint8')}


def demo():
    rows = []
    for path, addr, tid, kind in [
        ('g_imu.pitch_rad', 0x200014A0, 0, 'float'), ('g_imu.roll_rad', 0x200014A4, 0, 'float'),
        ('g_imu.yaw_rad', 0x200014A8, 0, 'float'), ('g_imu.accel[0]', 0x200014AC, 0, 'float'),
        ('g_imu.accel[1]', 0x200014B0, 0, 'float'), ('g_imu.accel[2]', 0x200014B4, 0, 'float'),
        ('g_chassis.leg.left_wheel_measured_rad_s', 0x24000020, 0, 'float'),
        ('g_chassis.leg.right_wheel_measured_rad_s', 0x24000024, 0, 'float'),
        ('g_motor.target_rpm', 0x30000000, 1, 'int32'), ('g_motor.current_ma', 0x30000004, 3, 'int16'),
        ('g_system.uptime_ms', 0x20000010, 2, 'uint32'), ('g_system.error_count', 0x20000014, 4, 'uint16'),
        ('g_system.temperature', 0x20000016, 5, 'int8'), ('g_system.state', 0x20000017, 6, 'uint8'),
        ('g_system.armed', 0x20000018, 6, 'bool'),
        ('g_diagnostic.external', 0x60000000, 0, 'float')]:
        rows.append(dict(path=path, address=addr, type_id=tid, type=kind, size={0:4,1:4,2:4,3:2,4:2,5:1,6:1}[tid]))
    return dict(name='demo_stm32h7.axf', fingerprint=0xA3F812C0, symbols=rows,
                warnings=['Demo symbols • no firmware file loaded'], fingerprint_source='Demo fixture')


def parse_firmware(path):
    from elftools.elf.elffile import ELFFile
    from elftools.dwarf.dwarf_expr import DWARFExprParser

    content = Path(path).read_bytes()
    elf = ELFFile(BytesIO(content))
    if elf.elfclass != 32 or not elf.little_endian or elf['e_type'] != 'ET_EXEC' or elf['e_machine'] != 'EM_ARM':
        raise ValueError('Expected a linked 32-bit little-endian ARM ELF/AXF executable.')
    if not elf.has_dwarf_info():
        raise ValueError('No DWARF debug information. Rebuild firmware with debug symbols.')
    dwarf = elf.get_dwarf_info()
    expressions = DWARFExprParser(dwarf.structs)
    warnings, rows, candidates = [], [], []
    skipped_locations = 0
    allocated = [s for s in elf.iter_sections() if s['sh_flags'] & 2 and s['sh_flags'] & 1]

    def attr(die, name, default=None):
        value = die.attributes.get(name)
        return value.value if value else default

    def name(die):
        value = attr(die, 'DW_AT_name', b'')
        return value.decode('utf-8', 'replace') if isinstance(value, bytes) else str(value)

    def ref(die):
        return die.get_DIE_from_attribute('DW_AT_type') if 'DW_AT_type' in die.attributes else None

    def unwrap(die):
        seen = set()
        while die and die.tag in ('DW_TAG_typedef', 'DW_TAG_const_type', 'DW_TAG_volatile_type', 'DW_TAG_restrict_type', 'DW_TAG_atomic_type'):
            if die.offset in seen:
                return None
            seen.add(die.offset)
            die = ref(die)
        return die

    def dimensions(die):
        result = []
        for sub in die.iter_children():
            if sub.tag == 'DW_TAG_subrange_type':
                lower = attr(sub, 'DW_AT_lower_bound', 0)
                count = attr(sub, 'DW_AT_count')
                upper = attr(sub, 'DW_AT_upper_bound')
                if not isinstance(lower, int) or (count is None and not isinstance(upper, int)):
                    raise ValueError('dynamic array bound')
                count = count if count is not None else upper - lower + 1
                if not isinstance(count, int) or count < 0:
                    raise ValueError('invalid array bound')
                result.append((lower, count))
        if not result:
            raise ValueError('unsized array')
        return result

    def size(die):
        die = unwrap(die)
        if not die:
            return 0
        explicit = attr(die, 'DW_AT_byte_size')
        if explicit is not None:
            return explicit
        if die.tag == 'DW_TAG_array_type':
            value = size(ref(die))
            for _, count in dimensions(die):
                value *= count
            return value
        return 0

    def member_offset(member):
        value = attr(member, 'DW_AT_data_member_location')
        if isinstance(value, int):
            return value
        if value is not None:
            ops = expressions.parse_expr(value)
            if len(ops) == 1 and ops[0].op_name == 'DW_OP_plus_uconst':
                return ops[0].args[0]
        raise ValueError('nonconstant member offset')

    def expand(die, path_name, address, depth=0):
        if depth > 32 or len(rows) >= 100000:
            raise ValueError('expansion limit reached (32 levels / 100000 leaves)')
        die = unwrap(die)
        if not die:
            raise ValueError('missing type')
        if die.tag in ('DW_TAG_structure_type', 'DW_TAG_class_type', 'DW_TAG_union_type'):
            for member in die.iter_children():
                if member.tag != 'DW_TAG_member' or attr(member, 'DW_AT_external', False):
                    continue
                child_path = path_name + ('.' + name(member) if name(member) else '')
                try:
                    if 'DW_AT_bit_size' in member.attributes:
                        raise ValueError('bitfield is not addressable')
                    offset = 0 if die.tag == 'DW_TAG_union_type' else member_offset(member)
                    expand(ref(member), child_path, address + offset, depth + 1)
                except ValueError as error:
                    warnings.append(f'{child_path}: {error}')
        elif die.tag == 'DW_TAG_array_type':
            element = ref(die)
            dims = dimensions(die)
            if size(element) <= 0:
                raise ValueError('unknown element size')
            def walk(index, prefix, base):
                if index == len(dims):
                    expand(element, prefix, base, depth + 1)
                    return
                stride = size(element)
                for _, count in dims[index + 1:]:
                    stride *= count
                lower, count = dims[index]
                if count > 100000:
                    raise ValueError('array expansion limit reached')
                for i in range(count):
                    walk(index + 1, f'{prefix}[{lower + i}]', base + stride * i)
            walk(0, path_name, address)
        else:
            base_type = unwrap(ref(die)) if die.tag == 'DW_TAG_enumeration_type' else die
            key = (attr(base_type, 'DW_AT_encoding'), size(die)) if base_type else None
            if key not in TYPE_MAP or die.tag not in ('DW_TAG_base_type', 'DW_TAG_enumeration_type'):
                raise ValueError('unsupported type (pointer, double, or incomplete type)')
            tid, kind = TYPE_MAP[key]
            rows.append(dict(path=path_name, address=address, type_id=tid, type=kind, size=size(die)))

    for cu in dwarf.iter_CUs():
        cu_name = name(cu.get_top_DIE())
        for die in cu.iter_DIEs():
            if die.tag != 'DW_TAG_variable' or 'DW_AT_location' not in die.attributes:
                continue
            location = die.attributes['DW_AT_location']
            if location.form not in ('DW_FORM_exprloc', 'DW_FORM_block', 'DW_FORM_block1', 'DW_FORM_block2', 'DW_FORM_block4'):
                skipped_locations += 1
                continue
            ops = expressions.parse_expr(location.value)
            if len(ops) != 1 or ops[0].op_name != 'DW_OP_addr':
                continue  # Stack locals and computed locations are not static RAM symbols.
            address = ops[0].args[0]
            if not any(s['sh_addr'] <= address < s['sh_addr'] + s['sh_size'] for s in allocated):
                continue
            declaration = die.get_DIE_from_attribute('DW_AT_specification') if 'DW_AT_specification' in die.attributes else die
            variable_name = name(declaration) or name(die)
            if not variable_name:
                continue
            scope, parent = [], die.get_parent()
            while parent and parent.tag != 'DW_TAG_compile_unit':
                if name(parent):
                    scope.insert(0, name(parent))
                parent = parent.get_parent()
            variable_name = '::'.join(scope + [variable_name])
            candidates.append((variable_name, cu_name, die, declaration, address))
    counts = Counter(item[0] for item in candidates)
    seen_paths = set()
    for variable_name, cu_name, die, declaration, address in candidates:
        label = f'{cu_name}::{variable_name}' if counts[variable_name] > 1 else variable_name
        if label in seen_paths:
            warnings.append(f'{label}: ambiguous duplicate skipped')
            continue
        seen_paths.add(label)
        try:
            expand(ref(die) or ref(declaration), label, address)
        except ValueError as error:
            warnings.append(f'{label}: {error}')

    fingerprint, source = 0, 'Missing g_telemetry_build_stamp'
    symtab = elf.get_section_by_name('.symtab')
    if symtab:
        for symbol in symtab.get_symbol_by_name('g_telemetry_build_stamp') or []:
            index = symbol['st_shndx']
            size = symbol['st_size']
            if not isinstance(index, int) or size <= 0:
                continue
            section = elf.get_section(index)
            offset = symbol['st_value'] - section['sh_addr']
            if section['sh_type'] != 'SHT_NOBITS' and 0 <= offset <= section['sh_size'] - size:
                fingerprint = zlib.crc32(section.data()[offset:offset + size])
                source = 'CRC32(g_telemetry_build_stamp)'
                break
    if not rows:
        warnings.append('No supported static RAM leaves found.')
    if skipped_locations:
        warnings.insert(0, f'{skipped_locations} dynamic/location-list variables skipped (includes optimized stack locals).')
    return dict(name=Path(path).name, fingerprint=fingerprint, fingerprint_source=source, symbols=rows, warnings=warnings)
