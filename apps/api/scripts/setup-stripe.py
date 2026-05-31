#!/usr/bin/env python3
"""Create Stripe Products and Prices for Beam billing plans.

Usage:
    STRIPE_SECRET_KEY=sk_test_xxx python apps/api/scripts/setup-stripe.py

After running, copy the printed env var values into your .env file (or Railway
environment variables panel).
"""

import os
import sys

try:
    import stripe
except ImportError:
    print("ERROR: stripe package not installed. Run: pip install stripe>=8.0.0")
    sys.exit(1)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
if not stripe.api_key:
    print("ERROR: STRIPE_SECRET_KEY environment variable is required.")
    sys.exit(1)

PLANS = [
    {
        "name": "Beam Pro",
        "description": "50 identified visitors/mo, social enrichment, AI drafts",
        "prices": [
            {"nickname": "Pro Monthly", "unit_amount": 1900, "interval": "month", "env_key": "STRIPE_PRICE_PRO_MONTHLY"},
            {"nickname": "Pro Yearly",  "unit_amount": 15000, "interval": "year",  "env_key": "STRIPE_PRICE_PRO_YEARLY"},
        ],
    },
    {
        "name": "Beam Max",
        "description": "Unlimited identified visitors, priority identification, team seats, API access",
        "prices": [
            {"nickname": "Max Monthly", "unit_amount": 4900, "interval": "month", "env_key": "STRIPE_PRICE_MAX_MONTHLY"},
            {"nickname": "Max Yearly",  "unit_amount": 39000, "interval": "year",  "env_key": "STRIPE_PRICE_MAX_YEARLY"},
        ],
    },
]


def create_or_find_product(name: str, description: str) -> str:
    """Return existing product ID if one with the same name exists, else create."""
    existing = stripe.Product.search(query=f'name:"{name}"', limit=1)
    if existing.data:
        product_id: str = existing.data[0]["id"]
        print(f"  Found existing product: {name} ({product_id})")
        return product_id

    product = stripe.Product.create(
        name=name,
        description=description,
    )
    product_id = product["id"]
    print(f"  Created product: {name} ({product_id})")
    return product_id


def create_price(product_id: str, nickname: str, unit_amount: int, interval: str) -> str:
    """Create a Stripe Price and return its ID."""
    price = stripe.Price.create(
        product=product_id,
        currency="usd",
        unit_amount=unit_amount,
        recurring={"interval": interval},
        nickname=nickname,
    )
    price_id: str = price["id"]
    print(f"    Created price: {nickname} ${unit_amount / 100:.2f}/{interval} ({price_id})")
    return price_id


def main() -> None:
    print("Setting up Stripe products and prices for Beam...\n")

    env_output: list[str] = []

    for plan in PLANS:
        print(f"Plan: {plan['name']}")
        product_id = create_or_find_product(plan["name"], plan["description"])

        for price_spec in plan["prices"]:
            price_id = create_price(
                product_id=product_id,
                nickname=price_spec["nickname"],
                unit_amount=price_spec["unit_amount"],
                interval=price_spec["interval"],
            )
            env_output.append(f"{price_spec['env_key']}={price_id}")

        print()

    print("─" * 60)
    print("Add these to your .env file (or Railway env vars):\n")
    for line in env_output:
        print(line)
    print()
    print("Done. Run your server and billing will use these Price IDs.")


if __name__ == "__main__":
    main()
