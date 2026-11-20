import json
import uuid
import pika
import redis

from django.core.management.base import BaseCommand
from inventory.models import Product
from inventory.services import OutOfstockError, compensate_stock_sage, reserve_stock_strict


def process_storage_event(payload:dict, redis_client, channel) -> str:
    """
    Processes an event received from the queue. Kept separate from the Pika consumer loop 
    to enable fast, isolated, and automated testing
    """
    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    data = payload.get("data", {})

    # Strict idempotency filter in REDIS (TTL 600s)
    is_new_event = redis_client.set(event_id, "processing", nx=True, ex=600)
    if not is_new_event:
        return "DUPLICATE_IGNORED"

    try:
        order_uuid = uuid.UUID(data["order_id"])

        if event_type == "OrderCreated":
            reserve_stock_strict(order_id=order_uuid, sku=data["sku"], quantity=data.get("quantity", 1))

            next_event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "Reservedstock",
                "data": data
            }

            channel.basic_publish(
                exchange="ecommerce_events",
                rounting_keys="",
                body=json.dumps(next_event),
                properties=pika.BasicProperties(delivery_mode=2)
            )

            redis_client.setex(event_id, 600, "concluded")

            return "RESERVED_PUBLISHED"

        elif event_type == "CompensateStock":
            compensate_stock_sage(order_id=order_uuid)
            
            redis_client.setex(event_id, 600, "concluded")
            
            return "COMPENSATED"

        return "UNKNOWN_EVENT"

    except (Product.DoesNotExist, OutOfstockError) as e:
        fail_event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "ReservestockFailed",
            "data": {
                "order_id": data["order_id"],
                "reason": str(e)
            }
        }

        channel.basic_publish(
            exchange="ecommerce_events",
            rounting_keys="",
            body=json.dumps(fail_event),
            properties=pika.BasicProperties(delivery_mode=2) 
        )

        redis_client.setex(event_id, 600, "business_failure")

        return "BUSINESS_FAILURE_PUBLISHED"

    except Exception as e:
        redis_client.delete(event_id)

        raise e


class Command(BaseCommand):
    help = "Start the EDA Worker for the Storage Module (RabbitMQ + Redis)"

    def handle(self, *args, **options):
        redis_client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        connection = pika.BlockingConnection(pika.ConnectionParameters(host="127.0.0.1", port=5672))
        channel = connection.channel()

        channel.queue_declare(queue="storage_queue", durable=True)
        channel.queue_bind(exchange="ecommerce_events", queue="storage_queue")
        channel.basic_qos(prefetch_count=1)

        def callback(ch, method, properties, body):
            payload = json.loads(body)

            try:
                status = process_storage_event(payload, redis_client, ch)
                self.stdout.write(f"[EDA] Event {payload.get("event_id")} -> {status}")
                ch.basic_ack(delivery_tag=method.delivery_tag)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[CRITICAL ERROR] {str(e)}"))
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        channel.basic_consume(queue="storage_queue", on_message_callback=callback)
        self.stdout.write(self.style.SUCCESS("Storage worker EDA started..."))
        channel.start_consuming()
