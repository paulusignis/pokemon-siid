"""
API Lambda handler — serves the ID analysis result to the frontend.

Triggered by: API Gateway HTTP GET /api/analysis

Query parameters:
  force_refresh=true  — bypass cache, always scrape fresh

Cache strategy:
  1. Read DynamoDB item with pk="latest"
  2. If missing OR older than CACHE_TTL_SECONDS: invoke Scraper Lambda synchronously
  3. Return result with CORS headers
"""

from __future__ import annotations

import json
import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CACHE_TABLE_NAME = os.environ["CACHE_TABLE_NAME"]
SCRAPER_FUNCTION_NAME = os.environ["SCRAPER_FUNCTION_NAME"]
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "300"))

dynamodb = boto3.resource("dynamodb")
cache_table = dynamodb.Table(CACHE_TABLE_NAME)

lambda_client = boto3.client("lambda")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _ok(body: dict) -> dict:
    return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps(body)}


def _error(status: int, code: str, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps({"error": code, "message": message}),
    }


def _get_cache() -> dict | None:
    """Return the cached DynamoDB item, or None if missing."""
    resp = cache_table.get_item(Key={"pk": "latest"})
    return resp.get("Item")


def _invoke_scraper() -> dict | None:
    """
    Invoke the Scraper Lambda synchronously.
    Returns the parsed payload on success, None on failure.
    """
    logger.info("Invoking scraper Lambda: %s", SCRAPER_FUNCTION_NAME)
    resp = lambda_client.invoke(
        FunctionName=SCRAPER_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps({"source": "api-lambda"}),
    )
    result = json.loads(resp["Payload"].read())
    if result.get("status") == "success":
        return result.get("payload")
    logger.error("Scraper returned error: %s", result)
    return None


def lambda_handler(event, context):
    # Parse query string params
    qs = event.get("queryStringParameters") or {}
    force_refresh = qs.get("force_refresh", "false").lower() == "true"

    now = int(time.time())
    cached = _get_cache()

    # Determine if cache is fresh enough
    cache_is_fresh = (
        cached is not None
        and not force_refresh
        and cached.get("scrape_status") == "success"
        and (now - int(cached.get("timestamp_epoch", 0))) < CACHE_TTL_SECONDS
    )

    if cache_is_fresh:
        age = now - int(cached["timestamp_epoch"])
        logger.info("Returning cached data (age: %ds)", age)
        payload = json.loads(cached["data"])
        payload["cache_age_seconds"] = age
        payload["data_source"] = "cache"
        return _ok(payload)

    # Cache is stale or missing — trigger live scrape
    logger.info("Cache stale or missing (force_refresh=%s); invoking scraper", force_refresh)
    payload = _invoke_scraper()

    if payload is None:
        # Try to return stale data rather than a hard error
        if cached and cached.get("scrape_status") == "success":
            age = now - int(cached["timestamp_epoch"])
            logger.warning("Live scrape failed; returning stale cache (age: %ds)", age)
            stale_payload = json.loads(cached["data"])
            stale_payload["cache_age_seconds"] = age
            stale_payload["data_source"] = "stale_cache"
            return _ok(stale_payload)

        return _error(503, "data_unavailable",
                      "No cached data available and live scrape failed")

    payload["cache_age_seconds"] = 0
    payload["data_source"] = "live"
    return _ok(payload)
