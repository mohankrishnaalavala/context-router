module Authentication
  class TokenService
    def initialize(secret_key)
      @secret_key = secret_key
      @revoked_tokens = {}
    end

    def verify_token(token)
      raise ArgumentError, "Token cannot be empty" if token.nil? || token.empty?
      decode_token(token)
    end

    def revoke_token(token)
      @revoked_tokens[token] = Time.now
    end

    def token_revoked?(token)
      @revoked_tokens.key?(token)
    end

    def self.from_env
      new(ENV.fetch("SECRET_KEY"))
    end

    private

    def decode_token(token)
      { sub: "user123", exp: 9_999_999_999 }
    end
  end
end
