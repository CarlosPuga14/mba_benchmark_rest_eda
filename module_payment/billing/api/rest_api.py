from django.http import HttpRequest
from ninja import NinjaAPI 
from billing.services import PaymentDeclinedError, process_payment_transaction
from .schemas import PaymentResponse, ProcessPaymentRequest


api = NinjaAPI(title="Payment Microsservice - REST API")


@api.post("/pay", response={200: PaymentResponse, 402:PaymentResponse})
def process_payment_endpoint(request:HttpRequest, payload:ProcessPaymentRequest):
    try:
        process_payment_transaction(payload.order_id, payload.amount, payload.simulate_delay_ms, payload.force_decline)

        endpoint_resposne = {
            "status": "APPROVED",
            "message": "Payment approved successfully"
        }

        return 200, endpoint_resposne

    except PaymentDeclinedError as e:
        endpoint_resposne = {
            "status": "DECLINED",
            "message": str(e)
        }

        return 402, endpoint_resposne