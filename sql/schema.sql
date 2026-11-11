-- Howard's Billiards Place: schema (MySQL 8 / MariaDB 10.4 via XAMPP)
-- All times are stored as local (Asia/Manila) DATETIME values; see app/utils/time.py.

CREATE DATABASE IF NOT EXISTS hbp_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hbp_db;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS waitlist, loyalty_redemptions, order_items, orders, products,
    session_extensions, sessions, reservations, email_tokens, users, units, unit_categories;
SET FOREIGN_KEY_CHECKS = 1;

-- Rates and rules live here, never in Python.
CREATE TABLE unit_categories (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(50)  NOT NULL UNIQUE,
    unit_type    ENUM('BILLIARDS','KARAOKE') NOT NULL,
    hourly_rate  DECIMAL(10,2) NOT NULL,
    min_minutes  INT NOT NULL DEFAULT 30,
    reservable   TINYINT(1) NOT NULL DEFAULT 1,
    is_active    TINYINT(1) NOT NULL DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE units (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    category_id  INT NOT NULL,
    name         VARCHAR(50) NOT NULL UNIQUE,
    description  VARCHAR(255) NULL,
    -- OCCUPIED is set/cleared by the session service; UNAVAILABLE is manual (maintenance).
    status       ENUM('AVAILABLE','OCCUPIED','UNAVAILABLE') NOT NULL DEFAULT 'AVAILABLE',
    is_active    TINYINT(1) NOT NULL DEFAULT 1,
    CONSTRAINT fk_units_category FOREIGN KEY (category_id) REFERENCES unit_categories(id)
) ENGINE=InnoDB;

CREATE TABLE users (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    first_name          VARCHAR(50)  NOT NULL,
    last_name           VARCHAR(50)  NOT NULL,
    email               VARCHAR(120) NOT NULL UNIQUE,
    password_hash       VARCHAR(255) NOT NULL,
    role                ENUM('admin','customer') NOT NULL DEFAULT 'customer',
    is_verified         TINYINT(1) NOT NULL DEFAULT 0,
    photo_filename      VARCHAR(255) NULL,
    last_login          DATETIME NULL,
    password_changed_at DATETIME NULL,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- OTP for email verification and password reset. Store a HASH of the code, not the code.
CREATE TABLE email_tokens (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    purpose    ENUM('VERIFY','RESET') NOT NULL,
    code_hash  VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    used_at    DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_tokens_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE reservations (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    unit_id     INT NOT NULL,
    start_time  DATETIME NOT NULL,
    end_time    DATETIME NOT NULL,
    status      ENUM('PENDING','CONFIRMED','REJECTED','CANCELLED','ACTIVE','COMPLETED','NO_SHOW')
                NOT NULL DEFAULT 'PENDING',
    notes       VARCHAR(255) NULL,
    decided_by  INT NULL,
    decided_at  DATETIME NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_res_user    FOREIGN KEY (user_id)    REFERENCES users(id),
    CONSTRAINT fk_res_unit    FOREIGN KEY (unit_id)    REFERENCES units(id),
    CONSTRAINT fk_res_decider FOREIGN KEY (decided_by) REFERENCES users(id),
    CONSTRAINT chk_res_range  CHECK (end_time > start_time),
    INDEX idx_res_overlap (unit_id, start_time, end_time),
    INDEX idx_res_user (user_id, status)
) ENGINE=InnoDB;

CREATE TABLE sessions (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    unit_id             INT NOT NULL,
    user_id             INT NULL,                 -- NULL for walk-ins without an account
    customer_name       VARCHAR(100) NULL,        -- used for walk-ins
    reservation_id      INT NULL UNIQUE,          -- set when converted from a reservation
    started_at          DATETIME NOT NULL,
    scheduled_end       DATETIME NOT NULL,        -- moves forward on extension
    ended_at            DATETIME NULL,            -- real end; prep timer = ended_at + 30s
    status              ENUM('ACTIVE','COMPLETED') NOT NULL DEFAULT 'ACTIVE',
    hourly_rate_applied DECIMAL(10,2) NOT NULL,   -- snapshot so later rate changes don't alter history
    total_cost          DECIMAL(10,2) NOT NULL DEFAULT 0,
    created_by          INT NOT NULL,
    CONSTRAINT fk_sess_unit  FOREIGN KEY (unit_id)        REFERENCES units(id),
    CONSTRAINT fk_sess_user  FOREIGN KEY (user_id)        REFERENCES users(id),
    CONSTRAINT fk_sess_res   FOREIGN KEY (reservation_id) REFERENCES reservations(id),
    CONSTRAINT fk_sess_admin FOREIGN KEY (created_by)     REFERENCES users(id),
    INDEX idx_sess_unit (unit_id, status),
    INDEX idx_sess_user (user_id, started_at)
) ENGINE=InnoDB;

CREATE TABLE session_extensions (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    minutes    INT NOT NULL,
    cost       DECIMAL(10,2) NOT NULL,
    created_by INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ext_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    CONSTRAINT fk_ext_admin   FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE products (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL UNIQUE,
    price      DECIMAL(10,2) NOT NULL,
    stock_qty  INT NOT NULL DEFAULT 0,
    is_active  TINYINT(1) NOT NULL DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE orders (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    ordered_by INT NULL,
    status     ENUM('PENDING','DELIVERED','CANCELLED') NOT NULL DEFAULT 'PENDING',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ord_session FOREIGN KEY (session_id) REFERENCES sessions(id),
    CONSTRAINT fk_ord_user    FOREIGN KEY (ordered_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE order_items (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    order_id   INT NOT NULL,
    product_id INT NOT NULL,
    quantity   INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,   -- price snapshot
    CONSTRAINT fk_item_order   FOREIGN KEY (order_id)   REFERENCES orders(id) ON DELETE CASCADE,
    CONSTRAINT fk_item_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT chk_item_qty    CHECK (quantity > 0)
) ENGINE=InnoDB;

-- Loyalty progress is COMPUTED from sessions (distinct days per unit_type); only redemptions are stored.
CREATE TABLE loyalty_redemptions (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    unit_type   ENUM('BILLIARDS','KARAOKE') NOT NULL,
    session_id  INT NULL,
    redeemed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_loy_user    FOREIGN KEY (user_id)    REFERENCES users(id),
    CONSTRAINT fk_loy_session FOREIGN KEY (session_id) REFERENCES sessions(id)
) ENGINE=InnoDB;

-- Optional (Could Have): build last.
CREATE TABLE waitlist (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    user_id      INT NOT NULL,
    category_id  INT NOT NULL,
    status       ENUM('WAITING','SEATED','REMOVED') NOT NULL DEFAULT 'WAITING',
    requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_wait_user FOREIGN KEY (user_id)     REFERENCES users(id),
    CONSTRAINT fk_wait_cat  FOREIGN KEY (category_id) REFERENCES unit_categories(id)
) ENGINE=InnoDB;
