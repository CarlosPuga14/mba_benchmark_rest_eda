# Latency vs. Resilience: Performance and Consistency Benchmark Between REST and EDA

Official repository for the experimental testbed developed as part of the final thesis for the **MBA in Software Engineering at USP/Esalq**.

## Objective

Quantitatively compare performance (p95/p99 latency percentiles), resource consumption stability, and data consistency across synchronous (**REST**) and event-driven (**EDA**) architectures under controlled Chaos Engineering scenarios.

## Technology Stack

* **Backend:** Python 3.12, Django, Django Ninja
* **Messaging and Caching:** RabbitMQ, Redis
* **Persistence:** PostgreSQL (*Database-per-Service*)
* **Infrastructure:** Docker and Docker Compose
* **Testing and Metrics:** Locust, Radon (Cyclomatic Complexity)

## Getting Started – Infrastructure Setup

```bash
docker-compose -f infra/docker-compose.yml up -d
```