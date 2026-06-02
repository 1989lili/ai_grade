import hashlib
import uuid
import subprocess
import platform
import sys


def _get_mac_addresses():
    macs = []
    node = uuid.getnode()
    mac = ':'.join(('%012x' % node)[i:i + 2] for i in range(0, 12, 2))
    macs.append(mac)
    return sorted(macs)


def _get_disk_serial():
    if sys.platform == 'win32':
        try:
            result = subprocess.run(
                ['wmic', 'diskdrive', 'get', 'serialnumber'],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                serial = lines[1].strip()
                if serial:
                    return serial
        except Exception:
            pass
    return 'DISK_UNKNOWN'


def _get_motherboard_serial():
    if sys.platform == 'win32':
        try:
            result = subprocess.run(
                ['wmic', 'baseboard', 'get', 'serialnumber'],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                serial = lines[1].strip()
                if serial and serial != 'To be filled by O.E.M.':
                    return serial
        except Exception:
            pass
    return 'MB_UNKNOWN'


def generate_hwid():
    components = [
        _get_mac_addresses()[0] if _get_mac_addresses() else 'MAC_UNKNOWN',
        _get_disk_serial(),
        _get_motherboard_serial(),
        platform.processor() or 'CPU_UNKNOWN',
    ]
    combined = '|'.join(components)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]
