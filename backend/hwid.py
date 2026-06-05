import hashlib
import uuid
import subprocess
import platform
import os
import sys

DEVICE_ID_FILENAME = 'device_id.dat'
APP_DIR_NAME = 'AI_Grader'


def _get_app_data_dir():
    base = os.environ.get('APPDATA')
    if not base:
        base = os.path.expanduser('~')
    path = os.path.join(base, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def _get_device_id_path():
    return os.path.join(_get_app_data_dir(), DEVICE_ID_FILENAME)


def _read_device_id():
    path = _get_device_id_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            device_id = f.read().strip()
        if device_id:
            return device_id
    except Exception:
        pass
    return None


def _write_device_id(device_id):
    path = _get_device_id_path()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(device_id)


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


def _build_initial_device_id():
    components = [
        _get_mac_addresses()[0] if _get_mac_addresses() else 'MAC_UNKNOWN',
        _get_disk_serial(),
        _get_motherboard_serial(),
        platform.processor() or 'CPU_UNKNOWN',
    ]
    combined = '|'.join(components)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


def generate_hwid():
    device_id = _read_device_id()
    if not device_id:
        device_id = _build_initial_device_id()
        _write_device_id(device_id)
    return device_id
