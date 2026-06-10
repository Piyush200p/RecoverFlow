import httpx
import sys

def main():
    checkout_id = "test_chk_998811"
    if len(sys.argv) > 1:
        checkout_id = sys.argv[1]

    url = "http://localhost:8000/webhooks/checkout-abandonment"
    headers = {
        "X-Shopify-Shop-Domain": "recoverflow-dev.myshopify.com",
        "X-Webhook-Topic": "checkouts/create",
        "Content-Type": "application/json"
    }
    payload = {
        "id": checkout_id,
        "email": "tester@example.com",
        "total_price": "2999.00",
        "currency": "INR",
        "abandoned_checkout_url": f"https://recoverflow-dev.myshopify.com/checkouts/ac/{checkout_id}",
        "customer": {
            "first_name": "John",
            "last_name": "Doe",
            "phone": "+919893347027"
        },
        "line_items": [
            {
                "title": "Premium Coffee Beans Blend",
                "quantity": 2,
                "price": "1499.50",
                "sku": "COFFEE-PREM-01"
            }
        ]
    }

    print(f"Sending simulated checkout webhook (ID: {checkout_id}) to {url}...")
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Failed to send request: {e}")

if __name__ == "__main__":
    main()
