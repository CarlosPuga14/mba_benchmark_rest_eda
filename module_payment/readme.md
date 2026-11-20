# Payment Microservice (`module_payment`)

Line-by-line technical documentation for the financial billing microservice, built for the comparative benchmark between REST and EDA architectures (MBA in Software Engineering — USP/Esalq).

---

## 1. Overview and Configuration (`config/`)

* **`config/settings.py`**
  * **`INSTALLED_APPS`**: Registers the local `'billing'` application to enable ORM mapping and custom management commands.
  * **`DATABASES['default']`**: Configures `django.db.backends.postgresql` pointing exclusively to the isolated `db_payment` database on `127.0.0.1:5434` (`postgres-db_payment` container), enforcing the *Database-per-Service* pattern.
* **`config/urls.py`**
  * **`urlpatterns`**: Maps `path("api/payment/", api.urls)` to expose the synchronous Django Ninja router.

---

## 2. Persistence Layer (`billing/models/`)

### `billing/models/__init__.py`
* Exports `Payment` at the `billing.models` package level so Django's migration engine discovers the entity automatically.

### `billing/models/payment.py`
* **`class Payment(models.Model)`**: Stores transaction records and ensures database-level idempotency per order.
  * `STATUS_CHOICES` / Constants (`approved`, `declined`): Defines the two terminal financial states (`APPROVED` and `DECLINED`).
  * `order_id = models.UUIDField(unique=True, primary_key=True)`: Uses the distributed order `UUID` as the primary key, preventing duplicate charges for the same order.
  * `amount = models.DecimalField(max_digits=10, decimal_places=2)`: Stores exact monetary values mapped to PostgreSQL `NUMERIC`, avoiding binary floating-point rounding errors.
  * `status = models.CharField(...)`: Tracks whether the transaction succeeded or failed.
  * `reason = models.CharField(max_length=255, blank=True, null=True)`: Stores failure details when a transaction is declined.
  * `created_at = models.DateTimeField(auto_now_add=True)`: Records the exact transaction timestamp.

---

## 3. Business Logic & Chaos Injection Layer (`billing/services.py`)

Contains pure domain logic decoupled from HTTP and message brokers.

### `class PaymentDeclinedError(Exception)`
* Domain exception raised when a payment is rejected due to invalid amounts or simulated chaos failures.

### `def process_payment_transaction(order_id: UUID, amount: Decimal, simulate_delay_ms: int = 0, force_decline: bool = False) -> Payment`
* **Latency Chaos Injection (`if simulate_delay_ms > 0:`)**: Suspends execution via `time.sleep(simulate_delay_ms / 1000.0)` to emulate external gateway degradation (e.g., `2500ms` delay for Chaos Scenario A).
* **Idempotency & Concurrency Lock (`with transaction.atomic():`)**:
  * **`existing = Payment.objects.select_for_update().filter(order_id=order_id).first()`**: Acquires a row-level lock to check if the order was already processed. If found, returns the existing `Payment` (or re-raises `PaymentDeclinedError` if previously declined) without creating duplicate records.
* **Approval Path (`if not force_decline and amount > Decimal("0.00"):`)**:
  * Creates and returns a `Payment` record with `status=Payment.approved`.
* **Decline Path**:
  * Persists a `Payment` record with `status=Payment.declined` inside the atomic block so the transaction commits to PostgreSQL.
  * Raises `PaymentDeclinedError(reason)` **outside** the `transaction.atomic()` block so Django does not roll back the `DECLINED` audit record.

---

## 4. Synchronous Entry Point — REST (`billing/api/`)

### `billing/api/schemas.py`
* **`class ProcessPaymentRequest(Schema)`**: Pydantic input contract validating `order_id: UUID`, `amount: Decimal`, and optional chaos flags (`simulate_delay_ms: int = 0`, `force_decline: bool = False`).
* **`class PaymentResponse(Schema)`**: Pydantic output contract standardizing `status: str` and `message: str`.

### `billing/api/rest_api.py`
* **`@api.post("/pay", response={200: PaymentResponse, 402: PaymentResponse})`**:
  * **`def process_payment_endpoint(request: HttpRequest, payload: ProcessPaymentRequest)`**: Invokes `process_payment_transaction`. Returns `HTTP 200` on approval or catches `PaymentDeclinedError` to return `HTTP 402` (Payment Required).

---

## 5. Asynchronous Entry Point — EDA (`billing/management/commands/run_eda_worker.py`)

### `def process_payment_event(payload: dict, redis_client, channel) -> str`
Core event processor decoupled from the Pika consumer loop for isolated unit testing:
* **Atomic Idempotency Filter (`is_new_event = redis_client.set(event_id, "processing", nx=True, ex=600)`)**: Atomically checks and locks the `event_id` in Redis for 600 seconds. Returns `"DUPLICATE_IGNORED"` if the event was already seen.
* **Event Routing (`if event_type == "EstoqueReservado":`)**:
  * Parses `order_id`, `amount`, and chaos flags from `data` and invokes `process_payment_transaction`.
  * On success, publishes `PagamentoAprovado` to the `ecommerce_events` exchange with `delivery_mode=2`, updates Redis status to `"completed"`, and returns `"PAYMENT_APPROVED_PUBLISHED"`.
* **Saga Rollback Trigger (`except PaymentDeclinedError as e:`)**:
  * Publishes a `CompensarEstoque` event containing the `order_id` to trigger compensating stock restoration in `module_storage`.
  * Updates Redis status to `"declined_compensated"` and returns `"SAGA_COMPENSATION_PUBLISHED"`.
* **Critical Failure Recovery (`except Exception as e:`)**:
  * Deletes the `event_id` key from Redis (`redis_client.delete(event_id)`) and re-raises the exception so the broker can requeue the message.

### `class Command(BaseCommand)`
* CLI entry point (`python manage.py run_eda_worker`). Connects to Redis (`6379`) and RabbitMQ (`5672`), binds durable queue `payment_queue` to the `ecommerce_events` fanout exchange with `prefetch_count=1`, and manages manual `basic_ack` / `basic_nack` acknowledgments.

---

## 6. Automated Test Suite (`billing/tests/`)

To execute all 9 automated tests (requires `postgres-db_payment` container running):
```bash
python manage.py test
```

### `billing/tests/test_rest_api.py` (`class PaymentRestApiTests`)
* **`test_payment_approved_success`**: Verifies `HTTP 200` response and `APPROVED` record persistence for valid orders.
* **`test_payment_declined_chaos`**: Verifies `HTTP 402` response and `DECLINED` record persistence when `force_decline=True`.
* **`test_payment_simulated_latency`**: Injects `simulate_delay_ms=200` and asserts elapsed execution time is `>= 200ms`.
* **`test_payment_invalid_amount_declined`**: Verifies `HTTP 402` response and `DECLINED` record persistence when `amount` is negative (`"-10.00"`).
* **`test_payment_idempotency_same_order_id`**: Sends two identical `POST` requests with the same `order_id`; asserts both return `HTTP 200` while only `1` row exists in PostgreSQL.

### `billing/tests/test_eda_worker.py` (`class PaymentEdaWorkerTests`)
* **`test_eda_reserved_stock_approves_payment`**: Simulates `EstoqueReservado`; asserts `"PAYMENT_APPROVED_PUBLISHED"`, database persistence, and `PagamentoAprovado` publication.
* **`test_eda_declined_triggers_saga_compensation`**: Simulates `EstoqueReservado` with `force_decline=True`; asserts `"SAGA_COMPENSATION_PUBLISHED"` and verifies `CompensarEstoque` is published with the target `order_id`.
* **`test_eda_idempotency_blocks_duplicate`**: Simulates an existing Redis lock (`set.return_value = False`); asserts `"DUPLICATE_IGNORED"`, zero database writes, and zero broker publications.
* **`test_eda_critical_error_deletes_redis_lock_for_requeue`**: Simulates a malformed payload raising `ValueError`; asserts `redis_client.delete(event_id)` is called to prevent deadlocks on requeue.
