-- Apply before deploying OTP application code to an existing database.
-- Fresh installations already have this column in schema.sql; this migration
-- checks INFORMATION_SCHEMA so it can safely follow fresh schema initialization.
-- The migration changes no account or historical business records.

SET @otp_attempt_count_ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE email_tokens ADD COLUMN attempt_count INT NOT NULL DEFAULT 0',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'email_tokens'
      AND COLUMN_NAME = 'attempt_count'
);

PREPARE otp_attempt_count_statement FROM @otp_attempt_count_ddl;
EXECUTE otp_attempt_count_statement;
DEALLOCATE PREPARE otp_attempt_count_statement;
