"""
Defines the data format that gateway_checkout will send and the response expected from the inventory service
"""
from uuid import UUID
from ninja import Schema

class ReserveinventoryRequest(Schema):
    order_id:UUID
    sku:str
    quantity:int = 1


class InventoryResponse(Schema):
    status:str
    message:str