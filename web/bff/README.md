# HTC BFF

Spring Boot BFF for the HTC Web Q1 demo.

## Requirements

- Java 17
- Maven

## Start

```bash
cd bff
mvn spring-boot:run
```

The service starts on port `8080`.

## Health Check

```bash
curl http://localhost:8080/api/v1/health
```

Expected response:

```json
{"status":"ok"}
```

## Chat Mock

```bash
curl -X POST http://localhost:8080/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"项目 Q1 阶段需要完成哪些功能？","session_id":"local-session-001","stream":false}'
```

The endpoint returns a non-streaming Mock response with `trace_id`, `status`, `answer`, and `citations`.

## Scope

This skeleton includes the application bootstrap, CORS configuration, package structure, health check endpoint, and a non-streaming `/api/v1/chat` Mock endpoint. Real Agent forwarding and SSE streaming are intentionally left for later steps.
