-- User authentication schema

CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE refresh_tokens (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) UNIQUE NOT NULL,
    expires_at  TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);

CREATE OR REPLACE FUNCTION verify_token_expiry(p_token_hash VARCHAR)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM refresh_tokens
        WHERE token_hash = p_token_hash AND expires_at > NOW()
    );
END;
$$ LANGUAGE plpgsql;

CREATE VIEW active_users AS
    SELECT u.id, u.email, COUNT(rt.id) as active_sessions
    FROM users u
    LEFT JOIN refresh_tokens rt ON rt.user_id = u.id AND rt.expires_at > NOW()
    GROUP BY u.id, u.email;
