"""Webhook system — HMAC-SHA256 signing, dispatch, and management (TASK-043).

Provides:
- WebhookEndpoint + WebhookDelivery Beanie models
- HMAC-SHA256 signing (verifiable by third parties)
- Async dispatch with retry + delivery logging
- CRUD API for endpoint management
"""
