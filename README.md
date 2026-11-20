# Contexto Consolidado - TCC MBA Engenharia de Software (USP/Esalq)

## 1. Escopo Acadêmico e Regras Oficiais
* **Título:** Latência versus Resiliência: Benchmark de Desempenho e Consistência entre REST e EDA
* **Princípio Metodológico:** Neutralidade arquitetural estrita. O experimento mapeia *trade-offs* mútuos sem favorecer um paradigma.
* **Prazos do Sistema:** 
  * Resultados Preliminares: **29/01/2027 a 05/02/2027**
  * Entrega Final (TCC): **13/04/2027 a 27/04/2027**
  * Slides e Defesa: **04/05/2027 a 25/05/2027**
* **Normas USP/Esalq:** Máximo de 30 páginas (estendido até 50 para implementação de algoritmos). Citações apenas indiretas (sem *apud*). Proibido usar "Quadros" (usar apenas "Figuras" e "Tabelas"). Subtítulos sem numeração e com recuo de 1,25 cm.
* **Referências Base:** Kleppmann (2017), Dragoni et al. (2017), Richardson (2018), Laigner et al. (2020), Menzies (2022), Behuti et al. (2023), Farias & Lazzari (2023), Li et al. (2023), Nimkar (2024), Adapa & Reddy (2025).

## 2. Arquitetura e Contratos Prometidos no Projeto de Pesquisa
* **Cenário de Negócio:** Fluxo de *checkout* de e-commerce (`Checkout` -> `Storage` -> `Payment` -> `Notification`).
* **Pilha:** Python 3.14, Django 5.1.2, Django Ninja 1.3.0, RabbitMQ, Redis, PostgreSQL (`psycopg[binary]`), Docker/Docker Compose, Locust e Radon.
* **Padrões de Identificação e Precisão:** Uso estrito de **UUID** (`UUIDField`) para rastreabilidade distribuída (`order_id`, `event_id`) e **`Decimal`** (`NUMERIC`) para valores monetários.
* **Ecossistema Síncrono (REST):** Rota `/api/checkout/sincrono`. Chamadas HTTP bloqueantes via `requests` com **`timeout=2.0` segundos**.
* **Ecossistema Assíncrono (EDA):** Rota `/api/checkout/assincrono`. Orquestração do **Padrão Saga**. Publica evento `PedidoCriado` em *Exchange* do tipo **Fanout** (`ecommerce_events`) e retorna **`HTTP 202 Accepted`** imediato.
* **Resiliência EDA:** Filas persistentes (`delivery_mode=2`) com confirmação explícita (`basic_ack`). Bloqueio atômico de idempotência no Redis via `redis_client.set(event_id, "processing", nx=True, ex=600)`. Rollback lógico via evento `CompensarEstoque`.
* **Diretriz de Qualidade e Documentação:** Cobertura de testes unitários **exaustiva** em todos os módulos (cobrindo caminho feliz, erros de negócio, idempotência, falhas críticas de infraestrutura e bordas). Manuais técnicos (`README.md`) detalhados linha a linha.

## 3. Os 4 Cenários de Caos e as 5 Métricas
* **Cenários:** 
  * **(A)** Latência injetada de **2500ms** no Pagamento (`simulate_delay_ms=2500` — expõe falha em cascata no REST).
  * **(B)** Queda abrupta (`docker stop`) do Pagamento após reserva de estoque (expõe dados órfãos no REST).
  * **(C)** Concorrência estrita em inventário unitário `available_quantity = 1` (expõe risco de sobrevenda/atraso no EDA).
  * **(D)** Rajadas massivas sem *backpressure* (expõe exaustão de CPU/RAM na retaguarda na EDA).
* **Métricas:** (1) Latência percentil p95/p99; (2) Taxa residual de inconsistência lógica; (3) Consumo de CPU/RAM; (4) MTTR das filas (Efeito de Mascaramento de Falhas); (5) Complexidade estrutural (LOC e Complexidade Ciclomática de McCabe via `radon`).
* **Parâmetros Locust (`load_tests/locustfile.py`):** Rampa linear de **10 a 500 usuários virtuais**, com *think time* aleatório entre **1,5s e 3,0s**.

## 4. Ponto Atual do Desenvolvimento (Onde Paramos)
* **Infraestrutura Docker (`infra/docker-compose.yml`):** 5 contêineres ativos em redes isoladas (`net_checkout`, `net_storage`, `net_payment`, `net_eventos`): `broker-rabbitmq` (`5672`/`15672`), `idempotency-cache` (`6379`), `postgres-checkout` (`5432`), `postgres-storage` (`5433`) e `postgres-db_payment` (`5434`).
* **Debug VS Code (`.vscode/launch.json`):** Configurado com perfis isolados (`cwd` e `env`) e modo composto (`Debug Todos os Módulos`) usando `integratedTerminal`.
* **Módulo de Estoque (`module_storage`) — CONCLUÍDO E TESTADO (8 testes):**
  * Porta `8001` / Banco `5433`. Modelos (`Product`, `StockReservation`), `services.py` (`reserve_stock_strict` com `select_for_update`, `compensate_stock_saga`), API REST (`POST /api/storage/reserve`), Worker EDA (`run_eda_worker.py` com bloqueio atômico `SET NX EX`) e 8 testes passando.
* **Módulo de Pagamento (`module_payment`) — CONCLUÍDO E TESTADO (9 testes):**
  * Porta `8002` / Banco `5434`. Modelo (`Payment`), `services.py` (`process_payment_transaction` com `simulate_delay_ms` e `force_decline`), API REST (`POST /api/payment/pay`), Worker EDA (`run_eda_worker.py` disparando `PagamentoAprovado` ou rollback `CompensarEstoque`) e 9 testes passando.

## 5. Roadmap das Próximas Etapas
* *Nota de Infraestrutura:* Desenvolver e testar localmente no `.venv` primeiro com testes exaustivos; conteinerizar tudo no `docker-compose.yml` antes dos testes de carga e caos.
1. **Desenvolver `gateway_checkout` (Próximo Passo):** Configurar banco isolado (`5432`), modelos (`Order`), orquestração síncrona (`/api/checkout/sincrono` com `timeout=2.0`), orquestração assíncrona (`/api/checkout/assincrono` -> HTTP 202), Worker EDA para atualizar status final da Saga e suíte de testes exaustiva.
2. **Desenvolver `module_notification`:** Worker simples ouvindo eventos finais (`PagamentoAprovado` / falhas) para fechar o ciclo + testes exaustivos.
3. **Conteinerização e Experimentos (`infra` e `load_tests`):** Criar `Dockerfile`, subir os microsserviços no Docker Compose, implementar `locustfile.py`, executar os 4 cenários de caos e extrair métricas via `docker stats` e `radon`.
