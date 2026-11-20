import time 
from decimal import Decimal
from uuid import UUID
from django.db import transaction
from .models import Payment


class PaymentDeclinedError(Exception):
    pass 


def process_payment_transaction(order_id:UUID, amount:Decimal, simulate_delay_ms:int=0, force_decline:bool=False) -> Payment:
    """
    Process financial transaction idempotently at the database level
    Allows controlled injection of latency nd failures for Chaos Engineering tests
    """
    # simulate gateway latency 
    if simulate_delay_ms > 0:
        time.sleep(simulate_delay_ms / 1000.0)

    with transaction.atomic():
        # avoid duplicated processing if the same order arrives twice
        existing = Payment.objects.select_for_update().filter(order_id=order_id).first()
        if existing:
            if existing.status == Payment.declined: # payment not approved
                raise PaymentDeclinedError(existing.reason or "Payment declined") # raising error 

            return existing # returns payment if it already exists

        if not force_decline and amount > Decimal("0.00"):
            return Payment.objects.create(
                order_id=order_id,
                amount=amount,
                status=Payment.approved
            ) # returns new payment otherwise

        reason = "Transaction declined by issuer or invalid amount"

        Payment.objects.create(
            order_id=order_id,
            amount=amount,
            status=Payment.declined,
            reason=reason
        )

    raise PaymentDeclinedError(reason) # raise error if force_decline or amount < 0