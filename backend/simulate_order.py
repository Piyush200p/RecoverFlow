import httpx
import sys

def main():
    checkout_id = "test_chk_998811"
    if len(sys.argv) > 1:
        checkout_id = sys.argv[1]

    order_id = "test_ord_554422"
    url = "http://localhost:8000/webhooks/order-created"
    headers = {
        "X-Shopify-Shop-Domain": "recoverflow-dev.myshopify.com",
        "X-Webhook-Topic": "orders/create",
        "Content-Type": "application/json"
    }
    payload = {
        "id": order_id,
        "checkout_id": checkout_id,
        "total_price": "2999.00",
        "currency": "INR"
    }

    print(f"Sending simulated order created (recovery) webhook for checkout {checkout_id} to {url}...")
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Failed to send request: {e}")

if __name__ == "__main__":
    main()
