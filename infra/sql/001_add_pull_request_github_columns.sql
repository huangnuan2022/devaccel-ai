ALTER TABLE pull_requests
ADD COLUMN IF NOT EXISTS delivery_id VARCHAR(255);

ALTER TABLE pull_requests
ADD COLUMN IF NOT EXISTS installation_id INTEGER;

CREATE UNIQUE INDEX IF NOT EXISTS ix_pull_requests_delivery_id
ON pull_requests (delivery_id);

CREATE INDEX IF NOT EXISTS ix_pull_requests_installation_id
ON pull_requests (installation_id);
