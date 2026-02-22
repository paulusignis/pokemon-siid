"""
Scraper Lambda handler.

Triggered by:
  - AWS EventBridge scheduled rule (every 5 minutes)
  - Synchronous invoke from the API Lambda (when cache is stale)

On success: writes result to DynamoDB and returns it.
On scrape/parse failure: logs the error, does NOT overwrite the cache,
  and returns an error dict so the API Lambda can surface a 503.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3

from scraper import fetch_pairings, parse_pairings
from computation import compute_id_analysis

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PAIRINGS_URL = os.environ["PAIRINGS_URL"]
CACHE_TABLE_NAME = os.environ["CACHE_TABLE_NAME"]

dynamodb = boto3.resource("dynamodb")
cache_table = dynamodb.Table(CACHE_TABLE_NAME)

CACHE_TTL_SECONDS = 3600  # DynamoDB auto-expires items after 1 hour


def lambda_handler(event, context):
    logger.info("Scraper invoked. Source: %s", event.get("source", "direct"))

    try:
        html = fetch_pairings(PAIRINGS_URL)
        pairings = parse_pairings(html)

        if not pairings:
            raise ValueError("No pairings found on the page — page may be empty or format changed")

        analysis = compute_id_analysis(pairings)

        now_epoch = int(time.time())
        timestamp = datetime.fromtimestamp(now_epoch, tz=timezone.utc).isoformat()

        payload = {
            "timestamp": timestamp,
            "pairings_url": PAIRINGS_URL,
            "divisions": analysis,
        }

        cache_table.put_item(Item={
            "pk": "latest",
            "timestamp": timestamp,
            "timestamp_epoch": now_epoch,
            "ttl": now_epoch + CACHE_TTL_SECONDS,
            "pairings_url": PAIRINGS_URL,
            "data": json.dumps(payload),
            "scrape_status": "success",
        })

        logger.info("Cache updated successfully at %s", timestamp)
        return {"status": "success", "payload": payload}

    except Exception as exc:
        logger.error("Scrape failed: %s", exc, exc_info=True)
        return {
            "status": "error",
            "error": "scrape_failed",
            "message": str(exc),
        }
