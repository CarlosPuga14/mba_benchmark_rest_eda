import json
import uuid

from unittest.mock import MagicMock
from django.test import TestCase
from inventory.management.commands.run_eda_worker import process_storage_event
from inventory.models import Product, StockReservation


class StorageEDAWorkTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            sku="MOUSE-01",
            name="Mouse sem fio",
            available_quantity=10
        )

        self.mock_channel = MagicMock()
        self.mock_redis = MagicMock()

        # default: key does not exists in Redis
        self.mock_redis.set.return_value = True


    def test_eda_order_created_successfully(self):
        """
        It must reserve stock and publish StockReserved
        """
        order_uuid = uuid.uuid4()
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "OrderCreated",
            "data": {
                "order_id": str(order_uuid),
                "sku": "MOUSE-01",
                "quantity": 3
            }
        }

        result = process_storage_event(payload, self.mock_redis, self.mock_channel)

        self.assertEqual(result, "RESERVED_PUBLISHED")
        
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 7)
        self.mock_channel.basic_publish.assert_called_once()


    def test_eda_idempotency_blocks_duplicate(self):
        """
        It must ignore event if event_id already exists in Redis
        """
        # now the key exists
        self.mock_redis.set.return_value = False 

        order_uuid = uuid.uuid4()
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "OrderCreated",
            "data": {
                "order_id": str(order_uuid),
                "sku": "MOUSE-01",
                "quantity": 3
            }
        }

        result = process_storage_event(payload, self.mock_redis, self.mock_channel)

        self.assertEqual(result, "DUPLICATE_IGNORED")
        
        # ensures that stock has not been modified
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 10)
        self.mock_channel.basic_publish.assert_not_called()


    def test_eda_compensate_stock_saga_rollback(self):
        """
        It must return the item to the stock when receive CompensateStock
        """
        order_uuid = uuid.uuid4()

        # simulate a previous reservation
        self.product.available_quantity = 8
        self.product.save()
        StockReservation.objects.create(
            order_id= order_uuid,
            product= self.product,
            quantity=2,
            status=StockReservation.reserved
        )

        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "CompensateStock",
            "data": {"order_id": str(order_uuid)}
        }

        result = process_storage_event(payload, self.mock_redis, self.mock_channel)

        self.assertEqual(result, StockReservation.compensated)

        # ensures that stock has been updated back to the old value
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 10)

        reservation = StockReservation.objects.get(order_id=order_uuid)
        self.assertEqual(reservation.status, StockReservation.compensated)


    def test_eda_duplicate_compensation_does_not_inflate_stock(self):
        """
        It must not add storage twice if CompensateStock arrives again
        """
        order_uuid = uuid.uuid4()
        
        self.product.available_quantity = 8
        self.product.save()

        StockReservation.objects.create(order_id=order_uuid, product=self.product, quantity=2, status=StockReservation.reserved)

        # first compensation (it should return 2 unities to storage -> quantity = 10)
        payload1 = {
            "event_id": str(uuid.uuid4()),
            "event_type": "CompensateStock",
            "data": {"order_id": str(order_uuid)}
        }

        process_storage_event(payload1, self.mock_redis, self.mock_channel)

        # second compensation (it should NOT return 2 unities to storage -> quantity = 10)
        payload2 = {
            "event_id": str(uuid.uuid4()),
            "event_type": "CompensateStock",
            "data": {"order_id": str(order_uuid)}
        }

        process_storage_event(payload2, self.mock_redis, self.mock_channel)

        self.product.refresh_from_db()
        self.assertEqual(self.product.available_quantity, 10)


    def test_eda_out_of_stock_publishes_failure_event(self):
        """
        It must publish StockReservationFailure when there's insufficient balance
        """
        order_uuid = uuid.uuid4()
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "OrderCreated",
            "data": { 
                "order_id": str(order_uuid),
                "sku": "MOUSE-01",
                "quantity": 50
            }
        }

        result = process_storage_event(payload, self.mock_redis, self.mock_channel)

        self.assertEqual(result, "TRANSACTION_FAILURE_PUBLISHED")
        published_body = json.loads(self.mock_channel.basic_publish.call_args.kwargs["body"])
        self.assertEqual(published_body[ "event_type"], "ReserveStockFailed")
