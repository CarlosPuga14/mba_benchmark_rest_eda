"""
Defines the data format that gateway_checkout will send and the response expected from the stock service
"""
from uuid import UUID
from ninja import Schema

class ReservestockRequest(Schema):
    order_id:UUID
    sku:str
    quantity:int = 1


class StockResponse(Schema):
    status:str
    message:str