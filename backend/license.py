"""许可证验证（用户版）—— 仅含公钥，可安全分发。"""
import json
import base64
import os
import sys
import datetime

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

try:
    from .hwid import generate_hwid
except ImportError:
    from hwid import generate_hwid  # type: ignore

_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsx9j1Xxp7WfivZlxSRSi
kHnRVCztUDkWCca0oP4eK55IeG+bJk64luhrSC2bZLQWgx1eMf8/vQ+tjyEtD+ag
R5UPG/pbeQr1AktBL4PXneCwTr8bDsBwm3zNEvxZgcapS7iBWeYtVnEky6VgkDQX
EtsuVfX+pe/aLeGUfBujBmRcbjyjMsYsBEqgNgdjIfvTaUVU19yYV/pPnuPUn35U
GIbZ0ja9CNW7sDnbRcHrMONn0s3XmO+x+dwzmm723J1jQFm7LHeaUxYFW2PCDIJJ
tA3jDrt1QHfHuynznyIoP2AlU/ZIP+RJ0oOpWr1WjR+C+fB4uPEiWpRiPVJ/cfL9
/wIDAQAB
-----END PUBLIC KEY-----"""

LICENSE_FILENAME = 'license.dat'


def _get_license_path():
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), LICENSE_FILENAME)
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), LICENSE_FILENAME)


def validate_license_key(license_key_str):
    try:
        raw = base64.b64decode(license_key_str)
        parts = raw.split(b'::', 1)
        if len(parts) != 2:
            return False, "许可证格式无效"

        payload_json, signature = parts

        public_key = serialization.load_pem_public_key(
            _PUBLIC_KEY_PEM.encode(), backend=default_backend()
        )
        public_key.verify(
            signature,
            payload_json,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )

        payload = json.loads(payload_json.decode())
        current_hwid = generate_hwid()

        if payload.get('product') != 'ai_grade':
            return False, "许可证产品不匹配"

        if not _hwid_fuzzy_match(payload['hwid'], current_hwid):
            return False, "许可证不匹配当前设备"

        if payload.get('expiry'):
            if datetime.datetime.now(datetime.timezone.utc) > datetime.datetime.fromisoformat(payload['expiry']):
                return False, "许可证已过期"

        return True, payload
    except Exception as e:
        return False, f"许可证验证失败: {str(e)}"


def _hwid_fuzzy_match(licensed_hwid, current_hwid):
    return licensed_hwid == current_hwid


def store_license(license_key_str):
    try:
        from .crypto import encrypt_data
    except ImportError:
        from crypto import encrypt_data  # type: ignore
    license_path = _get_license_path()
    encrypted = encrypt_data(license_key_str.encode())
    with open(license_path, 'wb') as f:
        f.write(encrypted)


def load_license():
    try:
        from .crypto import decrypt_data
    except ImportError:
        from crypto import decrypt_data  # type: ignore
    license_path = _get_license_path()
    if not os.path.exists(license_path):
        return None
    with open(license_path, 'rb') as f:
        encrypted = f.read()
    return decrypt_data(encrypted).decode()


def is_activated():
    stored = load_license()
    if not stored:
        return False
    valid, _ = validate_license_key(stored)
    return valid
