import os
import sys

# Setup local python import path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from tasks import send_whatsapp_reminder_task, send_cart_reminder_task

def trigger():
    mode = "checkout"
    if len(sys.argv) > 1:
        mode = sys.argv[1]

    if mode == "cart":
        cart_id = "cart_chk_new_445566"
        if len(sys.argv) > 2:
            cart_id = sys.argv[2]
        print(f"Triggering immediate Cart reminder Celery task for cart {cart_id}...")
        res = send_cart_reminder_task.delay(cart_id, "recoverflow-dev.myshopify.com")
        print(f"Task queued. Celery Task ID: {res.id}")
    else:
        checkout_id = "test_chk_new_456789"
        if len(sys.argv) > 2:
            checkout_id = sys.argv[2]
        print(f"Triggering immediate Checkout reminder Celery task for checkout {checkout_id}, step 1...")
        res = send_whatsapp_reminder_task.delay(checkout_id, "recoverflow-dev.myshopify.com", 1)
        print(f"Task queued. Celery Task ID: {res.id}")

if __name__ == "__main__":
    trigger()
