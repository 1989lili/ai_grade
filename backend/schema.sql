CREATE DATABASE IF NOT EXISTS grade
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE grade;

CREATE TABLE IF NOT EXISTS admin_users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  username VARCHAR(100) NOT NULL,
  password_hash CHAR(64) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_admin_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS activations (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO admin_users (username, password_hash)
VALUES ('admin', SHA2('admin123', 256))
ON DUPLICATE KEY UPDATE username = username;
