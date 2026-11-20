import json 
import uuid
import pika
import redis

from decimal import Decimal
from django.core.management.base import BaseCommand
from billing.services import PaymentDeclinedError, process_payment_transaction


def process_payment_event(payload:dict, redis_client, channel) -> str:
    """
    Processes financial events from the queue independently of the broker 
    enabling fast and isolated unit testing
    """
    event_id:str = payload.get("event_id")
    event_type:str = payload.get("event_type")
    data:dict = payload.get("data", {})

    # Atomic idempotency filter in Redis
    is_new_event = redis_client.set(event_id, "processing", nx=True, ex=600)
    if not is_new_event:
        return "DUPLICATE_IGNORED"

    try:
        if event_type == "ReservedStock":
            order_uuid = uuid.UUID(data["order_id"])
            amount = Decimal(str(data.get("amount", 0)))
            simulate_delay_ms = Decimal(str(data.get("simulate_delay_ms", 0)))
            force_decline = bool(data.get("force_decline", False))

            process_payment_transaction(order_uuid, amount, simulate_delay_ms, force_decline)

            next_event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "PaymentApproved",
                "data": data
            }

            channel.basic_publish(
                exchange="ecommerce_events",
                rounting_keys="",
                body=json.dumps(next_event),
                properties=pika.BasicProperties(delivery_mode=2)
            )

            redis_client.setex(event_id, 600, "completed")

            return "PAYMENT_APPROVED_PUBLISHED"

        return "UNKNOWN_EVENT"

    except PaymentDeclinedError as e:
        # Calls SAGA rollback from storage module
        saga_rollback_event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "CompensateStock", # here storage module is called
            "data": {
                "order_id": data["order_id"],
                "reason": str(e)
            }
        }

        channel.basic_publish(
            exchange="ecommerce_events",
            rounting_keys="",
            body=json.dumps(saga_rollback_event),
            properties=pika.BasicProperties(delivery_mode=2)
        )

        redis_client.setex(event_id, 600, "declined_compensated")

        return "SAGA_COMPENSATION_PUBLISHED"

    except Exception as e:
        redis_client.delete(event_id)

        raise e


class Command(BaseCommand):
    help = "Starts the EDA Worker for the Payment Module (RabbitMQ + Redis)"

    def handle(self, *args, **kwargs):
        redis_client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        connection = pika.BlockingConnection(pika.ConnectionParameters(host="127.0.0.1", port=5672))
        channel = connection.channel()

        channel.exchange_declare(exchange="ecommerce_events", exchange_type="fanout", durable=True)
        channel.queue_declare(queue="payment_queue", durable=True)
        channel.queue_bind(exchange="ecommerce_events", queue="payment_queue")
        channel.basic_qos(prefetch_count=1)

        def callback(ch, method, properties, body):
            payload = json.loads(body)

            try:
                status = process_payment_event(payload, redis_client, ch)
                self.stdout.write(f"[EDA Payment] Event {payload.get("event_id")} -> {status}")
                ch.basic_ack(delivery_tag=method.delivery_tag)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[CRITICAL ERROR] {str(e)}"))
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        channel.basic_consume(queue="payment_queue", on_message_callback=callback)
        self.stdout.write(self.style.SUCCESS("Payment worker EDA started..."))
        channel.start_consuming()
