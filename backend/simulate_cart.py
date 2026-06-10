import httpx
import sys

def main():
    cart_id = "test_cart_998811"
    if len(sys.argv) > 1:
        cart_id = sys.argv[1]

    url = "http://localhost:8000/webhooks/cart-abandonment"
    headers = {
        "X-Shopify-Shop-Domain": "recoverflow-dev.myshopify.com",
        "X-Webhook-Topic": "carts/create",
        "Content-Type": "application/json"
    }
    payload = {
        "token": cart_id,
        "customer": {
            "first_name": "John",
            "last_name": "Doe",
            "phone": "+919893347027"
        },
        "items": [
            {
                "title": "Premium Dark Roast Coffee",
                "variant_id": 4455667788,
                "quantity": 1,
                "price": 149900,  # 1499.00 in paise/cents
                "sku": "COFFEE-DARK-01"
            }
        ]
    }

    print(f"Sending simulated cart webhook (ID: {cart_id}) to {url}...")
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Failed to send request: {e}")

if __name__ == "__main__":
    main()
