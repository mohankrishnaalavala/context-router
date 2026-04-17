-- Migration 0011: service-contract tables for cross-language dependency
-- tracking (OpenAPI / protobuf / GraphQL). Signature-only — we do NOT
-- persist request/response bodies or schemas; see the ADR "Contract
-- extraction scope = signatures only".

CREATE TABLE IF NOT EXISTS api_endpoints (
  id INTEGER PRIMARY KEY,
  repo TEXT NOT NULL,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  operation_id TEXT,
  source_file TEXT,
  line INTEGER
);
CREATE INDEX IF NOT EXISTS idx_api_endpoints_repo ON api_endpoints(repo);
CREATE UNIQUE INDEX IF NOT EXISTS idx_api_endpoints_unique
  ON api_endpoints(repo, method, path);

CREATE TABLE IF NOT EXISTS grpc_services (
  id INTEGER PRIMARY KEY,
  repo TEXT NOT NULL,
  service TEXT NOT NULL,
  rpc TEXT NOT NULL,
  request_type TEXT,
  response_type TEXT,
  source_file TEXT,
  line INTEGER
);
CREATE INDEX IF NOT EXISTS idx_grpc_services_repo ON grpc_services(repo);
CREATE UNIQUE INDEX IF NOT EXISTS idx_grpc_services_unique
  ON grpc_services(repo, service, rpc);

CREATE TABLE IF NOT EXISTS graphql_operations (
  id INTEGER PRIMARY KEY,
  repo TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  source_file TEXT,
  line INTEGER
);
CREATE INDEX IF NOT EXISTS idx_graphql_operations_repo ON graphql_operations(repo);
CREATE UNIQUE INDEX IF NOT EXISTS idx_graphql_operations_unique
  ON graphql_operations(repo, name, kind);

INSERT OR REPLACE INTO schema_version(version) VALUES (11);
