import json
import uuid 
from unittest.mock import MagicMock
from django.test import TestCase
from billing.management.commands.run_eda_worker import process_payment_event
from billing.models import Payment


class PaymentEDAWorkerTests(TestCase):

    def setUp(self):
        self.mock_channel = MagicMock()
        self.mock_redis = MagicMock()
        self.mock_redis.set.return_value = True


    def test_eda_reserved_stock_approves_payment(self):
        """
        It must approve payment and publish PaymentApproved
        """
        order_uuid = uuid.uuid4()
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "ReservedStock",
            "data": {
                "order_id": str(order_uuid),
                "amount": "250.00"
            }
        }

        result = process_payment_event(payload, self.mock_redis, self.mock_channel)

        self.assertEqual(result, "PAYMENT_APPROVED_PUBLISHED")
        self.assertTrue(Payment.objects.filter(order_id=order_uuid, status="APPROVED").exists())

        # checks next published event
        published_body = json.loads(self.mock_channel.basic_publish.call_args[1]["body"])
        self.assertEqual(published_body["event_type"], "PaymentApproved")


    def test_eda_declined_triggers_saga_compensation(self):
        """
        It must publish CompensateStock when the payment is declined
        """        
        order_uuid = uuid.uuid4()
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "ReservedStock",
            "data": {
                "order_id": str(order_uuid),
                "amount": "250.00",
                "force_decline": True
            }
        }

        result = process_payment_event(payload, self.mock_redis, self.mock_channel)

        self.assertEqual(result, "SAGA_COMPENSATION_PUBLISHED")
        published_body = json.loads(self.mock_channel.basic_publish.call_args[1]["body"])
        self.assertEqual(published_body["event_type"], "CompensateStock")
        self.assertEqual(published_body["data"]["order_id"], str(order_uuid))


    def test_eda_idempotency_blocks_duplicate(self):
        """
        It must ignore duplicate event through atomic blocking
        """
        order_uuid = uuid.uuid4()
        self.mock_redis.set.return_value = False
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "ReservedStock",
            "data": {
                "order_id": str(order_uuid),
                "amount": "250.00"
            }
        }

        result = process_payment_event(payload, self.mock_redis, self.mock_channel)

        self.assertEqual(result, "DUPLICATE_IGNORED")
        self.assertEqual(Payment.objects.count(), 0)
        self.mock_channel.basic_publish.assert_not_called()


    def test_eda_critical_error_deletes_redis_lock_for_requeue(self):
        """
        It must remove the Redis lock if an unexpected error occurs to allow reprocessing
        """
        event_id = str(uuid.uuid4())
        payload = {
            "event_id": event_id,
            "event_type": "ReservedStock",
            "data": {
                "order_id": "INVALID_SKU",
                "amount": "250.00"
            }
        }

        with self.assertRaises(ValueError):
            process_payment_event(payload, self.mock_redis, self.mock_channel)

        # ensures that the key has been deleted in Redis to prevent blocking RabbitMQ message redelivery
        self.mock_redis.delete.assert_called_once_with(event_id)
        self.mock_channel.basick_publish.assert_not_called()