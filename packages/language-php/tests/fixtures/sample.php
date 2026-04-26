<?php

namespace App\Services;

interface AuthInterface
{
    public function verify(string $token): array;
}

class TokenService implements AuthInterface
{
    private string $secretKey;
    private array $revokedTokens = [];

    public function __construct(string $secretKey)
    {
        $this->secretKey = $secretKey;
    }

    public function verify(string $token): array
    {
        if (empty($token)) {
            throw new \InvalidArgumentException('Token cannot be empty');
        }
        return $this->decode($token);
    }

    public function revoke(string $token): void
    {
        $this->revokedTokens[$token] = time();
    }

    private function decode(string $token): array
    {
        return ['sub' => 'user123', 'exp' => 9999999999];
    }
}

function create_token(string $subject): string
{
    return base64_encode($subject . ':' . time());
}
