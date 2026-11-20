# Stock Microservice (`module_storage`)

Stock module, developed for the comparative benchmark between REST and EDA architectures (Final Thesis — MBA in Software Engineering, USP/Esalq).

---

## 1. Overview and Configuration (`config/`)

* **`config/settings.py`**
  * **`INSTALLED_APPS`**: Registers the local `'stock'` application to enable ORM mapping and custom management commands.
  * **`DATABASES['default']`**: Configures the `django.db.backends.postgresql` connector, pointing exclusively to the isolated `db_storage` database at host `127.0.0.1` and port `5433` (container `postgres-storage`), ensuring compliance with the *Database-per-Service* pattern.

* **`config/urls.py`**
  * **`urlpatterns`**: Maps the `path("api/storage/", api.urls)` prefix, connecting the Django Ninja instance to the main Django router.

---

## 2. Persistence Layer (`stock/models/`)

The data layer has been modularized into a Python package to separate entity responsibilities.

### `stock/models/__init__.py`

* **Lines 1–2**: Imports `Product` and `StockReservation` from their internal submodules.
* **Line 4 (`__all__`)**: Exposes both classes at the `stock.models` package level, allowing Django's `makemigrations` command to detect the models automatically.

### `stock/models/product.py`

* **`class Product(models.Model)`**: Represents the product catalog and the physical stock balance.
  * `sku = models.CharField(max_length=50, unique=True, primary_key=True)`: Defines the product's SKU as a unique textual primary key.
  * `name = models.CharField(max_length=150)`: Stores the product's name.
  * `available_quantity = models.IntegerField(default=0)`: Stores the current available stock quantity.
  * `def __str__(self)`: Returns a human-readable representation (`SKU - Qty: X`) for logging and debugging.

### `stock/models/stock_reservation.py`

* **`class StockReservation(models.Model)`**: An audit and state-management table required to implement logical rollbacks in the Saga Pattern.
  * `STATUS_CHOICES`: Defines the two possible reservation states (`RESERVED` for active reservations and `COMPENSATED` for reversed reservations).
  * `order_id = models.UUIDField(unique=True)`: Stores the unique identifier of the order originating from Checkout, preventing duplicate reservations for the same order.
  * `product = models.ForeignKey(Product, on_delete=models.CASCADE)`: Links the reservation to its corresponding product.
  * `quantity = models.IntegerField(default=1)`: Records the exact quantity reserved within the transaction.
  * `status = models.CharField(...)`: Indicates whether the reservation is active or has been compensated.
  * `created_at = models.DateTimeField(auto_now_add=True)`: Records the exact timestamp of the operation.

---

## 3. Business Logic Layer (`stock/services.py`)

Contains the core business logic, fully decoupled from HTTP protocols and messaging infrastructure.

### `class OutOfStockError(Exception)`

* A custom domain exception raised when the requested quantity exceeds the product's `available_quantity`.

### `def reserve_stock_strict(order_id: UUID, sku: str, quantity: int = 1) -> bool`

Executes an stock deduction while ensuring strong consistency under high concurrency (Chaos Engineering Scenario C):

* **`with transaction.atomic():`**: Opens an ACID transaction in PostgreSQL. If any operation fails, all changes are rolled back.
* **`product = Product.objects.select_for_update().get(sku=sku)`**: Executes a `SELECT ... FOR UPDATE` query against the database. This creates a pessimistic row-level lock, forcing concurrent requests for the same SKU to wait until the current transaction completes.
* **`if product.available_quantity < quantity:`**: Checks the updated stock balance. If insufficient, raises `OutOfStockError`.
* **`product.available_quantity -= quantity` / `product.save()`**: Deducts the requested quantity and persists the updated balance.
* **`StockReservation.objects.create(...)`**: Creates the reservation record with `RESERVED` status and returns `True`.

### `def compensate_stock_saga(order_id: UUID) -> bool`

Executes the compensation action (logical rollback) when a subsequent step in the distributed workflow fails:

* **`with transaction.atomic():`**: Ensures atomicity when restoring the stock balance.
* **`reservation = StockReservation.objects.select_for_update().filter(order_id=order_id, status="RESERVED").first()`**: Searches for the active reservation while locking its row to prevent duplicate compensations. If no active reservation is found (or it has already been compensated), returns `False`.
* **`product = Product.objects.select_for_update().get(...)`**: Locks the corresponding product, restores the reserved quantity (`+= reservation.quantity`), and saves the updated balance.
* **`reservation.status = "COMPENSATED"` / `reservation.save()`**: Marks the reservation as compensated for auditing purposes and returns `True`.

---

## 4. Synchronous Entry Point — REST (`stock/api/`)

### `stock/api/schemas.py`

* **`class ReserveStockRequest(Schema)`**: A Pydantic contract that automatically validates the JSON received by the HTTP endpoint (`order_id: UUID`, `sku: str`, `quantity: int = 1`).
* **`class StockResponse(Schema)`**: A Pydantic contract that standardizes the JSON response (`status: str`, `message: str`).

### `stock/api/rest_api.py`

* **`api = NinjaAPI(...)`**: Instantiates the high-performance API router and automatically generates OpenAPI/Swagger documentation.
* **`@api.post("/reserve", response={200: StockResponse, 400: StockResponse})`**:
  * **`def reserve_stock_endpoint(request: HttpRequest, payload: ReserveStockRequest)`**: Receives the validated payload and invokes `reserve_stock_strict`.
  * **`return 200, ...`**: Returns a success response if the reservation is completed successfully.
  * **`except Product.DoesNotExist:`**: Catches invalid SKUs and returns `HTTP 400` (`status: "ERROR"`).
  * **`except OutOfStockError as e:`**: Catches insufficient stock errors and returns `HTTP 400` (`status: "OUT_OF_STOCK"`).

---

## 5. Asynchronous Entry Point — EDA (`stock/management/commands/run_eda_worker.py`)

### `def process_storage_event(payload: dict, redis_client, channel) -> str`

The core event-processing function, decoupled from the network loop to enable isolated unit testing:

* **Metadata Extraction**: Reads `event_id`, `event_type`, and the `data` dictionary from the JSON event.
* **Atomic Idempotency Filter (`is_new_event = redis_client.set(event_id, "processando", nx=True, ex=600)`)**: Executes both the existence check (`NX`) and lock creation with a 600-second expiration (`EX`) in a single atomic operation on Redis. If the key already exists (`not is_new_event`), it prevents race conditions across concurrent workers and immediately returns `"DUPLICATE_IGNORED"` without querying PostgreSQL.
* **Routing `if event_type == "PedidoCriado":`**:
  * Converts `data["order_id"]` to `uuid.UUID` and calls `reserve_stock_strict`.
  * Builds the `next_event` dictionary with `event_type: "EstoqueReservado"` and a new `event_id`.
  * Publishes the event to RabbitMQ using `channel.basic_publish` on the `ecommerce_events` exchange with `properties=pika.BasicProperties(delivery_mode=2)` (ensuring the message is persistent on the broker).
  * Updates the Redis status to `"completed"` and returns `"RESERVED_PUBLISHED"`.

* **Routing `elif event_type == "CompensarEstoque":`**:
  * Calls `compensate_stock_saga(order_id=order_uuid)` to reverse the reservation for an order whose payment has failed.
  * Updates the Redis status to `"completed"` and returns `"COMPENSATED"`.

* **Business Failure Handling (`except (Product.DoesNotExist, OutOfStockError) as e:`)**:
  * Publishes a `FalhaReservaEstoque` event to notify the Saga orchestrator, marks the event as `"business_failure"` in Redis, and returns `"BUSINESS_FAILURE_PUBLISHED"`.

* **Critical Failure Handling (`except Exception as e:`)**:
  * Executes `redis_client.delete(event_id)` to remove the idempotency lock, allowing the message to be processed again after redelivery.

### `class Command(BaseCommand)`

* **`def handle(self, *args, **options)`**: CLI entry point executed through `python manage.py run_eda_worker`.
  * Connects to Redis (`127.0.0.1:6379`) and RabbitMQ (`127.0.0.1:5672`).
  * Declares the durable `ecommerce_events` exchange of type `fanout` and binds the durable `storage_queue` queue.
  * **`channel.basic_qos(prefetch_count=1)`**: Ensures the worker processes one message at a time before fetching the next one.
  * **`def callback(ch, method, properties, body)`**: Converts the message body from bytes to JSON, calls `process_storage_event`, and sends `ch.basic_ack` (manual message acknowledgment). In case of an unexpected error, it sends `ch.basic_nack(..., requeue=True)` to return the message to the queue.

---

## 6. Automated Test Suite (`inventory/tests/`)

To execute all 8 automated tests (requires the `postgres-storage` container running):
```bash
python manage.py test
```

### `inventory/tests/test_rest_api.py` (`class StorageRestApiTests`)
* **`setUp`**: Initializes the Django test `Client` and inserts product `NOTEBOOK-01` with `available_quantity=5` into the isolated test database.
* **`test_reserve_stock_success`**: Sends a `POST` request for `2` units; asserts HTTP `200`, verifies inventory decrements to `3`, and confirms a `RESERVED` record with the exact `UUID` exists.
* **`test_reserve_out_of_stock`**: Requests `10` units; asserts HTTP `400` (`OUT_OF_STOCK`) and ensures inventory remains unchanged at `5`.
* **`test_reserve_product_not_found`**: Sends an unregistered SKU; asserts HTTP `400` (`ERROR`).

### `inventory/tests/test_eda_worker.py` (`class StorageEdaWorkerTests`)
* **`setUp`**: Inserts product `MOUSE-01` (balance `10`) and configures `MagicMock` instances for the RabbitMQ channel and Redis client (`mock_redis.set.return_value = True`).
* **`test_eda_pedido_criado_success`**: Simulates receiving `PedidoCriado` for `3` units; asserts `"RESERVED_PUBLISHED"`, verifies inventory decrements to `7`, and confirms `basic_publish` is called once.
* **`test_eda_idempotency_blocks_duplicate`**: Configures `mock_redis.set.return_value = False` (simulating an already existing key under the atomic `SET NX` lock); asserts `"DUPLICATE_IGNORED"`, ensuring inventory remains at `10` and no event is published.
* **`test_eda_compensar_estoque_saga_rollback`**: Creates a prior reservation of `2` units (balance `8`) and dispatches `CompensarEstoque`; asserts `"COMPENSATED"`, verifies inventory returns to `10`, and confirms the reservation status updates to `COMPENSATED`.
* **`test_eda_out_of_stock_publishes_failure_event`**: Simulates `PedidoCriado` requesting `50` units when only `10` are available; asserts `"BUSINESS_FAILURE_PUBLISHED"` and verifies that a `FalhaReservaEstoque` event is published to the broker.
* **`test_eda_duplicate_compensation_does_not_inflate_stock`**: Dispatches two sequential `CompensarEstoque` events with distinct `event_id`s for the same `order_id`; ensures the inventory balance stops at `10` and is not inflated to `12`.
