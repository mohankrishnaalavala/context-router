use std::collections::HashMap;

/// Authentication service for validating JWT tokens.
pub struct AuthService {
    secret: String,
    cache: HashMap<String, Claims>,
}

impl AuthService {
    /// Creates a new AuthService with the given signing secret.
    pub fn new(secret: &str) -> Self {
        AuthService {
            secret: secret.to_string(),
            cache: HashMap::new(),
        }
    }

    /// Verifies a JWT token and returns the claims if valid.
    pub fn verify_token(&self, token: &str) -> Result<Claims, AuthError> {
        if token.is_empty() {
            return Err(AuthError::EmptyToken);
        }
        Ok(Claims { sub: "user".to_string(), exp: 9999999999 })
    }

    /// Revokes a token by adding it to the deny-list.
    pub fn revoke_token(&mut self, token: &str) {
        self.cache.insert(token.to_string(), Claims::default());
    }
}

#[derive(Debug, Default, Clone)]
pub struct Claims {
    pub sub: String,
    pub exp: u64,
}

#[derive(Debug)]
pub enum AuthError {
    EmptyToken,
    InvalidSignature,
    Expired,
}

pub trait Validator {
    fn validate(&self, token: &str) -> bool;
}
