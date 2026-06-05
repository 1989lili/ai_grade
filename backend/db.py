import os
import re
import datetime
import hashlib

import pymysql
import pymysql.cursors

DB_HOST = os.environ.get('GRADE_DB_HOST', '121.229.206.191')
DB_PORT = int(os.environ.get('GRADE_DB_PORT', '3306'))
DB_NAME = os.environ.get('GRADE_DB_NAME', 'xty_grade')
DB_USER = os.environ.get('GRADE_DB_USER', 'root')
DB_PASSWORD = os.environ.get('GRADE_DB_PASSWORD', '7XyQbbcdfgrG5*7w')
DB_CHARSET = 'utf8mb4'


class DatabaseError(Exception):
    pass


def _safe_identifier(name):
    if not re.match(r'^[A-Za-z0-9_]+$', name):
        raise DatabaseError('数据库名称只能包含字母、数字和下划线')
    return f'`{name}`'


def _connect(database=None):
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=database,
        charset=DB_CHARSET,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def get_conn():
    return _connect(DB_NAME)


def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''CREATE TABLE IF NOT EXISTS activations (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                hwid VARCHAR(255) NOT NULL,
                license_key TEXT NOT NULL,
                issued_at DATETIME NOT NULL,
                expiry DATETIME NULL,
                status ENUM('active', 'revoked') NOT NULL DEFAULT 'active',
                device_label VARCHAR(255) NOT NULL DEFAULT '',
                note TEXT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_verified_at DATETIME NULL,
                PRIMARY KEY (id),
                KEY idx_activations_hwid_status (hwid, status),
                KEY idx_activations_created_at (created_at),
                KEY idx_activations_expiry (expiry)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS admin_users (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                username VARCHAR(100) NOT NULL,
                password_hash CHAR(64) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uq_admin_users_username (username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')

            # 默认管理员 admin/admin123
            cursor.execute("SELECT COUNT(*) AS total FROM admin_users")
            row = cursor.fetchone()
            if row['total'] == 0:
                pw_hash = hashlib.sha256('admin123'.encode()).hexdigest()
                cursor.execute(
                    "INSERT INTO admin_users (username, password_hash) VALUES (%s, %s)",
                    ('admin', pw_hash)
                )
        conn.commit()
    finally:
        conn.close()


def _to_mysql_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        return datetime.datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError:
        return None


def add_activation(hwid, license_key, expiry=None, device_label='', note=''):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO activations (hwid, license_key, issued_at, expiry, device_label, note) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    hwid,
                    license_key,
                    datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
                    _to_mysql_datetime(expiry),
                    device_label,
                    note,
                )
            )
        conn.commit()
    finally:
        conn.close()


def _serialize_row(row):
    if not row:
        return None
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, datetime.datetime):
            result[key] = value.isoformat()
    return result


def get_activations(page=1, per_page=20, search='', status=''):
    conn = get_conn()
    try:
        where = []
        params = []
        if search:
            where.append("(hwid LIKE %s OR device_label LIKE %s OR note LIKE %s)")
            params.extend([f'%{search}%'] * 3)
        if status:
            where.append("status = %s")
            params.append(status)
        where_clause = ' AND '.join(where) if where else '1=1'

        with conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM activations WHERE {where_clause}", params)
            total = cursor.fetchone()['total']
            cursor.execute(
                f"SELECT * FROM activations WHERE {where_clause} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [per_page, (page - 1) * per_page]
            )
            rows = cursor.fetchall()
            return [_serialize_row(r) for r in rows], total
    finally:
        conn.close()


def get_activation_by_hwid(hwid):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM activations WHERE hwid=%s ORDER BY created_at DESC LIMIT 1", (hwid,))
            return _serialize_row(cursor.fetchone())
    finally:
        conn.close()


def revoke_activation(activation_id):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE activations SET status='revoked' WHERE id=%s", (activation_id,))
        conn.commit()
    finally:
        conn.close()


def get_stats():
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM activations")
            total = cursor.fetchone()['total']
            cursor.execute("SELECT COUNT(*) AS total FROM activations WHERE status='active'")
            active = cursor.fetchone()['total']
            cursor.execute("SELECT COUNT(*) AS total FROM activations WHERE status='revoked'")
            revoked = cursor.fetchone()['total']
            cursor.execute("SELECT COUNT(*) AS total FROM activations WHERE DATE(created_at)=CURDATE()")
            today = cursor.fetchone()['total']
            return {'total': total, 'active': active, 'revoked': revoked, 'today': today}
    finally:
        conn.close()


def verify_admin(username, password):
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM admin_users WHERE username=%s AND password_hash=%s",
                (username, pw_hash)
            )
            return cursor.fetchone()
    finally:
        conn.close()


def touch_activation_verified(activation_id):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE activations SET last_verified_at=%s WHERE id=%s",
                (datetime.datetime.now(datetime.UTC).replace(tzinfo=None), activation_id)
            )
        conn.commit()
    finally:
        conn.close()


def verify_activation_record(hwid, license_key):
    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM activations WHERE hwid=%s AND license_key=%s ORDER BY created_at DESC LIMIT 1",
                (hwid, license_key)
            )
            row = cursor.fetchone()
            if not row:
                return False, '激活码未在数据库登记'
            if row.get('status') != 'active':
                return False, '激活码已被撤销'
            expiry = _to_mysql_datetime(row.get('expiry'))
            if expiry and datetime.datetime.now(datetime.UTC).replace(tzinfo=None) > expiry:
                return False, '激活码已过期'
            cursor.execute(
                "UPDATE activations SET last_verified_at=%s WHERE id=%s",
                (datetime.datetime.now(datetime.UTC).replace(tzinfo=None), row['id'])
            )
        conn.commit()
        return True, row
    except pymysql.MySQLError as e:
        return False, f'无法连接激活数据库: {e}'
    finally:
        if conn:
            conn.close()
