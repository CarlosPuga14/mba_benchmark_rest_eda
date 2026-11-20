from decimal import Decimal
from uuid import UUID
from ninja import Schema


class ProcessPaymentRequest(Schema):
    order_id:UUID
    amount:Decimal
    simulate_delay_ms:int = 0
    force_decline:bool = False


class PaymentResponse(Schema):
    status:str
    message:str