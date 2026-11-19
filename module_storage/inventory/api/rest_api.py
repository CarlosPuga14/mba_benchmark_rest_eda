"""
Implements the synchronous POST/reserve endpoint. It calls the reserve_inventory_strict function
and handles the possible business errors
"""
from django.http import HttpRequest
from ninja import NinjaAPI

from inventory.models import Product
from inventory.services import OutOfinventoryError, reserve_inventory_strict
from .schemas import ReserveinventoryRequest, InventoryResponse

api = NinjaAPI(title="Storage Microservice - REST API")

@api.post("/reserve", response={200: InventoryResponse, 400: InventoryResponse})
def reserve_inventory_endpoint(request:HttpRequest, payload:ReserveinventoryRequest):
    try:
        reserve_inventory_strict(order_id=payload.order_id, sku=payload.sku, quantity=payload.quantity)

        endpoint_response = {
            "status": "SUCCESS",
            "message": "inventory successfully reserved"
        }

        return 200, endpoint_response

    except Product.DoesNotExist:
        endpoint_response = {
            "status": "ERROR",
            "message": "Product not found"
        }

        return 400, endpoint_response

    except OutOfinventoryError as e:
        endpoint_response = {
            "status": "OUT_OF_inventory",
            "message": str(e)
        }

        return 400, endpoint_response