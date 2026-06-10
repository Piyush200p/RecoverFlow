"""
RecoverFlow AI — Block 6: Gemini AI Text Generation & Personalization
=======================================================================
Generates personalized WhatsApp recovery messages using Google's
Gemini 1.5 Flash model.

Message strategy varies by recovery step:
  Step 1 (30 min):  Friendly reminder — "Hey, you left something behind!"
  Step 2 (6 hrs):   Scarcity/urgency — "Items are selling fast..."
  Step 3 (24 hrs):  Last chance — "Final reminder before we release your cart"

Each message is tailored to:
  • Customer name
  • Specific items in cart
  • Store brand tone (casual, luxury, urgent, playful)
  • Recovery checkout URL
"""

import logging
from typing import Optional

import google.generativeai as genai

from config import get_settings

logger = logging.getLogger("recoverflow.ai_engine")
settings = get_settings()

# ── Configure Gemini ─────────────────────────────────────────
if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)

# ── Model Configuration ─────────────────────────────────────
MODEL_NAME = "gemini-1.5-flash"

GENERATION_CONFIG = {
    "temperature": 0.8,
    "top_p": 0.9,
    "top_k": 40,
    "max_output_tokens": 300,
}

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


# ═════════════════════════════════════════════════════════════
#  STEP-BASED PROMPT STRATEGIES
# ═════════════════════════════════════════════════════════════

STEP_STRATEGIES = {
    1: {
        "name": "Friendly Reminder",
        "instruction": (
            "Write a warm, friendly WhatsApp message reminding the customer "
            "they left items in their cart. Be conversational and helpful, "
            "not pushy. Make them feel like you're looking out for them."
        ),
        "emoji_style": "warm and inviting (👋, 🛍️, ✨)",
    },
    2: {
        "name": "Scarcity & Urgency",
        "instruction": (
            "Write a WhatsApp message creating gentle urgency. Mention that "
            "items in their cart are popular and stock is limited. Use social "
            "proof language like 'other customers are eyeing these too'. "
            "Be persuasive but not aggressive."
        ),
        "emoji_style": "urgent but friendly (⏰, 🔥, 💨)",
    },
    3: {
        "name": "Last Chance",
        "instruction": (
            "Write a final WhatsApp reminder. This is the last message they'll "
            "receive. Create a sense of closing — 'we're holding your cart but "
            "not for much longer'. If appropriate, hint at potential savings. "
            "Keep it respectful and make it easy to complete checkout."
        ),
        "emoji_style": "closing and decisive (⏳, 💎, 🎯)",
    },
}


# ═════════════════════════════════════════════════════════════
#  TONE DESCRIPTORS
# ═════════════════════════════════════════════════════════════

TONE_DESCRIPTORS = {
    "friendly": "warm, casual, conversational — like a helpful friend texting",
    "casual": "relaxed, approachable, uses informal language and slang naturally",
    "urgent": "direct, time-sensitive, action-oriented — creates FOMO without being aggressive",
    "luxury": "elegant, refined, premium — makes the customer feel valued and exclusive",
    "playful": "fun, witty, uses clever wordplay — makes shopping feel exciting",
    "professional": "polished, trustworthy, straightforward — builds confidence",
}


# ═════════════════════════════════════════════════════════════
#  CORE FUNCTION: Generate Recovery Message
# ═════════════════════════════════════════════════════════════

def generate_personalized_recovery_message(
    store_name: str,
    tone: str,
    customer_name: str,
    items: list,
    checkout_url: str = "",
    step: int = 1,
    is_cart_recovery: bool = False,
    customer_segment: Optional[str] = None,
) -> str:
    """
    Generates a personalized WhatsApp recovery message using Gemini.

    Args:
        store_name: The merchant's store name (e.g., "FashionHub")
        tone: Brand voice tone (friendly, casual, urgent, luxury, playful)
        customer_name: Customer's first name or "there"
        items: List of cart items [{title, quantity, price}, ...]
        checkout_url: The Shopify abandoned checkout recovery URL / cart permalink
        step: Recovery step number (1, 2, or 3)
        is_cart_recovery: If True, generate message for cart abandonment recovery
        customer_segment: The customer's AI classification segment

    Returns:
        A formatted WhatsApp message string ready for dispatch.
    """
    # ── Format cart items ────────────────────────────────────
    if items:
        items_formatted = "\n".join(
            [
                f"  • {item.get('quantity', 1)}x {item.get('title', 'Item')}"
                + (f" — ₹{item.get('price', '?')}" if item.get("price") else "")
                for item in items[:5]  # Cap at 5 items to keep message short
            ]
        )
        if len(items) > 5:
            items_formatted += f"\n  ... and {len(items) - 5} more items"
    else:
        items_formatted = "  • Your selected products"

    # ── Get step strategy ────────────────────────────────────
    if is_cart_recovery:
        strategy = {
            "name": "Cart Abandonment Reminder",
            "instruction": (
                "Write a premium, friendly WhatsApp message reminding the customer "
                "they added products to their cart but did not start checkout yet. "
                "Be polite, inviting, and make them feel welcome to complete their order. "
                "Keep it exclusive and high-end."
            ),
            "emoji_style": "premium and inviting (🛍️, ✨, 💎)",
        }
    else:
        strategy = STEP_STRATEGIES.get(step, STEP_STRATEGIES[1])
        
    tone_desc = TONE_DESCRIPTORS.get(tone, TONE_DESCRIPTORS["friendly"])

    # ── Handle Customer Segment Instructions ─────────────────
    segment_instructions = ""
    if customer_segment:
        seg_upper = customer_segment.upper()
        if seg_upper == "FIRST_TIME":
            segment_instructions = (
                "- CUSTOMER TYPE: First-Time Customer. Write with a warm, friendly welcome tone. "
                "Welcome them to the brand's family."
            )
        elif seg_upper == "RETURNING":
            segment_instructions = (
                "- CUSTOMER TYPE: Returning Customer. Write a personalized reminder. "
                "Acknowledge their continued trust and welcome them back."
            )
        elif seg_upper == "VIP":
            segment_instructions = (
                "- CUSTOMER TYPE: VIP Customer. Write with a premium, exclusive, and highly appreciative tone. "
                "Thank them for being a valued loyal member and prioritize service."
            )
        elif seg_upper == "HIGH_VALUE":
            segment_instructions = (
                "- CUSTOMER TYPE: High Cart Value Customer. Create a sense of urgency and exclusivity. "
                "Focus on the high demand and limited availability of these premium items."
            )
        elif seg_upper == "DISCOUNT_ORIENTED":
            segment_instructions = (
                "- CUSTOMER TYPE: Discount-Oriented Customer. Emphasize that they have a discount code/savings "
                "applied, making it a great deal to complete their purchase."
            )
        elif seg_upper == "LIKELY_TO_PURCHASE":
            segment_instructions = (
                "- CUSTOMER TYPE: Likely-To-Purchase Customer. Write a conversational, highly persuasive message "
                "focusing on how perfect these items are for them."
            )

    # ── Build the prompt ─────────────────────────────────────
    prompt = f"""You are an expert e-commerce copywriter writing WhatsApp recovery messages.

CONTEXT:
- Store Name: {store_name}
- Customer Name: {customer_name}
- Recovery Step: {"Cart Abandonment" if is_cart_recovery else f"{step}/3 — {strategy['name']}"}
- Brand Voice: {tone} — {tone_desc}
{segment_instructions if segment_instructions else ""}

ITEMS LEFT IN CART:
{items_formatted}

CART/CHECKOUT LINK: {checkout_url or "[link]"}

TASK:
{strategy['instruction']}

STRICT RULES:
1. Keep the message under 250 characters (WhatsApp best practice).
2. Use emojis sparingly — style: {strategy['emoji_style']}.
3. Do NOT use any markdown formatting (no *, #, **, etc.).
4. Do NOT include headers, subject lines, or greetings like "Subject:".
5. Do NOT mention "RecoverFlow" or any automation tool.
6. The message must appear to come directly from "{store_name}".
7. End with the cart/checkout link on its own line.
8. Address the customer by name: "{customer_name}".
9. Write in a single flowing message — no bullet points or lists.
10. The message must work as a standalone WhatsApp text bubble.

Write ONLY the message text, nothing else."""

    # ── Call Gemini API ──────────────────────────────────────
    try:
        if not settings.GEMINI_API_KEY:
            logger.warning("Gemini API key not configured, using fallback template")
            return _fallback_message(store_name, customer_name, items, checkout_url, step, is_cart_recovery)

        model = genai.GenerativeModel(
            MODEL_NAME,
            generation_config=GENERATION_CONFIG,
            safety_settings=SAFETY_SETTINGS,
        )

        response = model.generate_content(prompt)

        if response and response.text:
            message = _clean_message(response.text.strip())
            logger.info(
                f"Gemini generated {'cart' if is_cart_recovery else f'step {step}'} message for {store_name}: "
                f"{len(message)} chars"
            )
            return message
        else:
            logger.warning(
                f"Gemini returned empty response for {'cart' if is_cart_recovery else f'step {step}'}, "
                f"using fallback"
            )
            return _fallback_message(store_name, customer_name, items, checkout_url, step, is_cart_recovery)

    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return _fallback_message(store_name, customer_name, items, checkout_url, step, is_cart_recovery)


# ═════════════════════════════════════════════════════════════
#  POST-PROCESSING
# ═════════════════════════════════════════════════════════════

def _clean_message(text: str) -> str:
    """
    Cleans Gemini output to ensure it's WhatsApp-safe.
    Strips markdown artifacts and ensures proper formatting.
    """
    # Remove any markdown formatting that slipped through
    text = text.replace("**", "").replace("__", "")
    text = text.replace("##", "").replace("# ", "")

    # Remove surrounding quotes if present
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        text = text[1:-1]

    # Remove any "Subject:" or "Message:" prefixes
    for prefix in ["Subject:", "Message:", "Text:", "WhatsApp Message:"]:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()

    # Truncate to 1024 chars (WhatsApp text message limit)
    if len(text) > 1024:
        text = text[:1021] + "..."

    return text.strip()


# ═════════════════════════════════════════════════════════════
#  FALLBACK TEMPLATES
# ═════════════════════════════════════════════════════════════

def _fallback_message(
    store_name: str,
    customer_name: str,
    items: list,
    checkout_url: str,
    step: int,
    is_cart_recovery: bool = False,
) -> str:
    """
    Pre-written fallback templates used when Gemini is unavailable.
    These ensure message delivery is never blocked by AI failures.
    """
    items_text = ", ".join(
        [f"{item.get('quantity', 1)}x {item.get('title', 'item')}" for item in items[:3]]
    )
    if not items_text:
        items_text = "your selected items"

    link = checkout_url or "[Complete your order]"

    if is_cart_recovery:
        return (
            f"Hey {customer_name}! 🛍️\n\n"
            f"We noticed you added some items to your cart at {store_name}: "
            f"{items_text}.\n\n"
            f"They are waiting for you! Reopen your cart here:\n"
            f"{link}"
        )

    templates = {
        1: (
            f"Hey {customer_name}! 👋\n\n"
            f"You left some great items in your cart at {store_name}: "
            f"{items_text}.\n\n"
            f"They're still waiting for you! Complete your order here:\n"
            f"{link}"
        ),
        2: (
            f"Hi {customer_name}! ⏰\n\n"
            f"Just a heads up — the items in your {store_name} cart are "
            f"popular and selling fast: {items_text}.\n\n"
            f"Don't miss out! Grab them before they're gone:\n"
            f"{link}"
        ),
        3: (
            f"Hi {customer_name} 💎\n\n"
            f"This is your final reminder from {store_name}. "
            f"We've been holding {items_text} in your cart, "
            f"but we can't keep them reserved much longer.\n\n"
            f"Complete your purchase now:\n"
            f"{link}"
        ),
    }

    return templates.get(step, templates[1])


# ═════════════════════════════════════════════════════════════
#  AI SEGMENTATION
# ═════════════════════════════════════════════════════════════

def _fallback_segment(orders_count: int, total_spent: float, cart_value: float, has_discounts: bool) -> str:
    """Standard rule-based segment fallback if Gemini is offline."""
    if orders_count >= 5 or total_spent >= 10000.0:
        return "VIP"
    if cart_value >= 5000.0:
        return "HIGH_VALUE"
    if has_discounts:
        return "DISCOUNT_ORIENTED"
    if orders_count == 0:
        return "FIRST_TIME"
    if orders_count > 0:
        return "RETURNING"
    return "FIRST_TIME"


def classify_customer_segment(
    orders_count: int,
    total_spent: float,
    cart_value: float,
    has_discounts: bool,
    tags: str = "",
) -> str:
    """
    Classifies a customer into one of 6 segments using Gemini 1.5 Flash.
    Falls back to a rule-based system if the API fails or is not configured.
    """
    if not settings.GEMINI_API_KEY:
        return _fallback_segment(orders_count, total_spent, cart_value, has_discounts)

    prompt = f"""You are an e-commerce data intelligence agent. Classify this customer into exactly one of these segments:
- FIRST_TIME (if orders_count is 0 or they are a new shopper with no past purchases)
- RETURNING (if orders_count > 0 and they are a regular repeat buyer but not a VIP or high-value cart)
- VIP (if orders_count >= 5 or total_spent >= 10000 or tags contain 'VIP')
- HIGH_VALUE (if current cart_value >= 5000)
- DISCOUNT_ORIENTED (if they are using a discount coupon code on this cart/checkout, or have discount/sale tags)
- LIKELY_TO_PURCHASE (if they have high spending patterns or positive indicators showing high conversion probability)

CUSTOMER METRICS:
- Orders Count: {orders_count}
- Total Spent: {total_spent}
- Current Cart Value: {cart_value}
- Has Discount Applied: {has_discounts}
- Customer Tags: {tags}

RULES:
1. Output ONLY the segment code as a plain single word (e.g. VIP, FIRST_TIME, RETURNING, HIGH_VALUE, DISCOUNT_ORIENTED, LIKELY_TO_PURCHASE).
2. Do NOT write any punctuation, explanations, or other text.
3. If multiple segments apply, pick the most premium one in this priority: VIP > DISCOUNT_ORIENTED > HIGH_VALUE > LIKELY_TO_PURCHASE > RETURNING > FIRST_TIME.

Segment Code:"""

    try:
        model = genai.GenerativeModel(
            MODEL_NAME,
            generation_config={
                "temperature": 0.1,  # Low temperature for deterministic classification
                "max_output_tokens": 10,
            },
            safety_settings=SAFETY_SETTINGS,
        )
        response = model.generate_content(prompt)
        if response and response.text:
            val = response.text.strip().upper()
            # Validate output
            valid_segments = {"FIRST_TIME", "RETURNING", "VIP", "HIGH_VALUE", "DISCOUNT_ORIENTED", "LIKELY_TO_PURCHASE"}
            if val in valid_segments:
                return val
            # Strip potential extra formatting
            for s in valid_segments:
                if s in val:
                    return s
        logger.warning("Gemini returned invalid segment name, falling back to rule-based")
        return _fallback_segment(orders_count, total_spent, cart_value, has_discounts)
    except Exception as e:
        logger.error(f"Failed to classify segment via Gemini: {e}")
        return _fallback_segment(orders_count, total_spent, cart_value, has_discounts)
