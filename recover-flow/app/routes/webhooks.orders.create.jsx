/**
 * RecoverFlow AI — Webhook: orders/create
 * =========================================
 * Receives Shopify order creation events and forwards to
 * the FastAPI backend. This is critical for:
 *   1. Marking abandoned checkouts as RECOVERED
 *   2. Revoking pending Celery recovery tasks
 *   3. Logging recovered revenue for ROI dashboard
 */
import { authenticate } from "../shopify.server";

export const action = async ({ request }) => {
  const { topic, shop, payload } = await authenticate.webhook(request);

  console.log(`[RecoverFlow] Webhook received: ${topic} from ${shop}`);

  try {
    const backendUrl = process.env.RECOVERFLOW_BACKEND_URL || "http://127.0.0.1:8000";
    const response = await fetch(`${backendUrl}/webhooks/order-created`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Shopify-Shop-Domain": shop,
        "X-Webhook-Topic": topic,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      console.error(`[RecoverFlow] Backend returned ${response.status} for ${topic}`);
    }
  } catch (error) {
    console.error(`[RecoverFlow] Failed to forward webhook to backend:`, error.message);
  }

  return new Response(null, { status: 200 });
};
