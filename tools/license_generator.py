"""发行方许可证生成器。此文件绝不随 EXE 分发，仅由发行方持有。"""
import json
import base64
import sys
from datetime import datetime, timedelta

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCzH2PVfGntZ+K9
mXFJFKKQedFULO1QORYJxrSg/h4rnkh4b5smTriW6GtILZtktBaDHV4x/z+9D62P
IS0P5qBHlQ8b+lt5CvUCS0Evg9ed4LBOvxsOwHCbfM0S/FmBxqlLuIFZ5i1WcSTL
pWCQNBcS2y5V9f6l79ot4ZR8G6MGZFxuPKMyxiwESqA2B2Mh+9NpRVTX3JhX+k+e
49SfflQYhtnSNr0I1buwOdtFwesw42fSzdeY77H53DOabvbcnWNAWbssd5pTFgVb
Y8IMgkm0DeMOu3VAd8e7KfOfIig/YCVT9kg/5EnSg6lavVaNH4L58Hi48SJalGI9
Un9x8v3/AgMBAAECggEALxyBcIQBhEx/iWiTMCp6O0+e6+nJHQF2t2mI1pMfsk82
Nl78So4H5MEKfnhoV4s6JJAT10iQJhS6jFuoc3cwDsO4rp4hcuub11edtHaTvlV7
aaq/3hhlRbAEbArtK8Hpgx3q/48Xu5WUnO9JP4RD0VTOkhNaP6CfHNQo7p+COEq6
cEv9p/EQbTEMSU7CEU5GK9JNgHPbVnCEsKvT3QK9G1v6aXmglmEs3EF/hYBXbTIS
Z2xBdpq6F40xzEVoLEqLhRYFU19wOOJ8y+IwRvUP+NlYMJsovSSMhv8sfsBEyaHr
wIZsqV8uTDec1sg4qVrkrNtB1SRez5D3lnAuBES0+QKBgQDhERDOuIJLMRqZkVg6
57FtWFO4GlxH7O8+0w/g1XAzecKCgJzu3T2fE2XVQfBJ7KHJ/vXQHmp3/u1VDeHT
9UpedLPqq45XC5wb6Oav+IlQbSjdiCUIeu8nXw0BLU5xQ79iPI+xUZCq3jtpnMs/
mS+8k2FvkuoKx7TpK1cECaGGSwKBgQDLvcpbxzsvOUG8rRrAriEeWHaASbJWiFze
A+K8mj0HDw9Yjz/7HJUjSh0F9JzZCrpeC/GuDuMFGpAnhhKpeuF+nX7HJB7to5sn
p+GCwZl+JGdzA4P5TzhfUNhTFhOGXBRoOL2HcY8qpOLPgFMjr+hCckNPqKkvXgEB
hbX4EQ2mnQKBgQDQoXAyIGlvaDpfJpNiL0qSsPESVSU760+vrhkm8tPKc9EyBiTz
a5TmtCWOtUwYSsmDJNwaq0dIqsC4OmEfiV8CBi6Nl7Af0nxIhvHpJ3uqWTYrfTvP
C55Lodm9QJFZf1KWrssItTJkohLzCMyDzO2qYfhNZCOeEJgMGQfVj1Py1wKBgQCR
pOXAgAaV9odAmjoynQe9yp1Djes3oplIeFygWF3h6ukcdKLXHpKaPIPM2xU4rkuV
qVImDCxLXLbKGjTDBL2npmyXbQHS/Q6P5Zn2v/C61MlC1bOFCBWTRZaupmxksvQ/
oLgT16DxahddIC3OqBQPU+E8U6RF4Rw0+2GeqIoqnQKBgHkXK8KC5/Xj0P1F0UTI
Gx9qkLSpYvRrzUNx4o6qKGZLtQLIP4b/t/JQmm/RmbTrOZ9Cygjeqk/AsmnmLQHc
bIQAC+JxUFAGGm7yQgat+uJ1eUMnts5R/DKhNvhy+lUVKQCdaPBXYRfWhedGEZGn
9m1NBApE8DmpUvrM83sNsWLu
-----END PRIVATE KEY-----"""


def generate_license(hwid, expiry_days=None):
    expiry = None
    if expiry_days:
        expiry = (datetime.utcnow() + timedelta(days=expiry_days)).isoformat()

    payload = {
        "hwid": hwid,
        "product": "ai_grade",
        "expiry": expiry,
        "features": ["full"],
        "issued_at": datetime.utcnow().isoformat()
    }
    payload_json = json.dumps(payload, ensure_ascii=False).encode()

    private_key = serialization.load_pem_private_key(
        _PRIVATE_KEY_PEM.encode(), password=None
    )
    signature = private_key.sign(
        payload_json,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )

    raw = payload_json + b'::' + signature
    return base64.b64encode(raw).decode()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python license_generator.py <HWID> [有效期天数]")
        print("示例: python license_generator.py abc123def456 365")
        sys.exit(1)

    hwid = sys.argv[1]
    days = int(sys.argv[2]) if len(sys.argv) > 2 else None

    license_key = generate_license(hwid, days)
    print(f"机器码: {hwid}")
    print(f"有效期: {days or '永久'}")
    print(f"激活码: {license_key}")
