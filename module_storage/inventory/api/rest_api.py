"""
Implements the synchronous POST/reserve endpoint. It calls the reserve_stock_strict function
and handles the possible business errors
"""
from django.http import HttpRequest
from ninja import NinjaAPI

from inventory.models import Product
from inventory.services import OutOfstockError, reserve_stock_strict
from .schemas import ReservestockRequest, StockResponse

api = NinjaAPI(title="Storage Microservice - REST API")

@api.post("/reserve", response={200: StockResponse, 400: StockResponse})
def reserve_stock_endpoint(request:HttpRequest, payload:ReservestockRequest):
    try:
        reserve_stock_strict(order_id=payload.order_id, sku=payload.sku, quantity=payload.quantity)

        endpoint_response = {
            "status": "SUCCESS",
            "message": "stock successfully reserved"
        }

        return 200, endpoint_response

    except Product.DoesNotExist:
        endpoint_response = {
            "status": "ERROR",
            "message": "Product not found"
        }

        return 400, endpoint_response

    except OutOfstockError as e:
        endpoint_response = {
            "status": "OUT_OF_stock",
            "message": str(e)
        }

        return 400, endpoint_response