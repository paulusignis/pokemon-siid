"""Unit tests for backend/api/handler.py — uses moto to mock DynamoDB + Lambda."""
import sys
import os
import json
import time

import boto3
import pytest

# Single place to configure the AWS region used across all tests
AWS_REGION = "us-west-2"

# Provide required env vars before importing the handler
os.environ["CACHE_TABLE_NAME"] = "pokemon-siid-cache"
os.environ["SCRAPER_FUNCTION_NAME"] = "pokemon-siid-scraper"
os.environ["CACHE_TTL_SECONDS"] = "300"
os.environ["AWS_DEFAULT_REGION"] = AWS_REGION
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))


SAMPLE_PAYLOAD = {
    "timestamp": "2024-01-15T14:30:00+00:00",
    "pairings_url": "https://example.com",
    "divisions": {
        "MA": {
            "player_count": 2,
            "current_round_pairings": [],
        }
    },
}


def make_event(force_refresh=False):
    qs = {"force_refresh": "true"} if force_refresh else {}
    return {"queryStringParameters": qs}


@pytest.fixture(autouse=True)
def aws_mocks():
    """Start moto mocks for DynamoDB and Lambda before each test."""
    from moto import mock_aws
    with mock_aws():
        # Create the DynamoDB table
        ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
        ddb.create_table(
            TableName="pokemon-siid-cache",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        # Create a stub Lambda function so boto3 doesn't error on invoke
        lam = boto3.client("lambda", region_name=AWS_REGION)
        lam.create_function(
            FunctionName="pokemon-siid-scraper",
            Runtime="python3.12",
            Role="arn:aws:iam::123456789012:role/test",
            Handler="handler.lambda_handler",
            Code={"ZipFile": b"fake"},
        )

        yield ddb


def _put_cache(ddb, age_seconds=10, status="success"):
    """Helper: put a cache item with given age into DynamoDB."""
    now = int(time.time())
    table = ddb.Table("pokemon-siid-cache")
    table.put_item(Item={
        "pk": "latest",
        "timestamp": "2024-01-15T14:30:00+00:00",
        "timestamp_epoch": now - age_seconds,
        "ttl": now + 3600,
        "pairings_url": "https://example.com",
        "data": json.dumps(SAMPLE_PAYLOAD),
        "scrape_status": status,
    })


class TestApiHandler:
    def test_fresh_cache_returned_without_scraping(self, aws_mocks):
        """Fresh cache should be returned and Lambda should NOT be invoked."""
        _put_cache(aws_mocks, age_seconds=30)  # 30s old, TTL is 300s

        import importlib
        import handler as h
        importlib.reload(h)

        response = h.lambda_handler(make_event(), None)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["data_source"] == "cache"
        assert body["cache_age_seconds"] >= 30

    def test_stale_cache_triggers_scrape(self, aws_mocks, monkeypatch):
        """Stale cache should trigger Scraper Lambda invoke."""
        _put_cache(aws_mocks, age_seconds=400)  # older than 300s TTL

        import importlib
        import handler as h
        importlib.reload(h)

        scraper_called = []

        def mock_invoke_scraper():
            scraper_called.append(True)
            return SAMPLE_PAYLOAD

        monkeypatch.setattr(h, "_invoke_scraper", mock_invoke_scraper)

        response = h.lambda_handler(make_event(), None)
        assert response["statusCode"] == 200
        assert len(scraper_called) == 1
        body = json.loads(response["body"])
        assert body["data_source"] == "live"

    def test_empty_cache_triggers_scrape(self, aws_mocks, monkeypatch):
        """No cache item should trigger Scraper Lambda invoke."""
        import importlib
        import handler as h
        importlib.reload(h)

        scraper_called = []

        def mock_invoke_scraper():
            scraper_called.append(True)
            return SAMPLE_PAYLOAD

        monkeypatch.setattr(h, "_invoke_scraper", mock_invoke_scraper)

        response = h.lambda_handler(make_event(), None)
        assert response["statusCode"] == 200
        assert len(scraper_called) == 1

    def test_503_when_no_cache_and_scrape_fails(self, aws_mocks, monkeypatch):
        """No cache + failed scrape → 503."""
        import importlib
        import handler as h
        importlib.reload(h)

        monkeypatch.setattr(h, "_invoke_scraper", lambda: None)

        response = h.lambda_handler(make_event(), None)
        assert response["statusCode"] == 503
        body = json.loads(response["body"])
        assert body["error"] == "data_unavailable"

    def test_stale_cache_returned_when_scrape_fails(self, aws_mocks, monkeypatch):
        """Stale cache exists + live scrape fails → return stale data (not 503)."""
        _put_cache(aws_mocks, age_seconds=400)

        import importlib
        import handler as h
        importlib.reload(h)

        monkeypatch.setattr(h, "_invoke_scraper", lambda: None)

        response = h.lambda_handler(make_event(), None)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["data_source"] == "stale_cache"

    def test_force_refresh_bypasses_fresh_cache(self, aws_mocks, monkeypatch):
        """force_refresh=true should trigger live scrape even if cache is fresh."""
        _put_cache(aws_mocks, age_seconds=10)

        import importlib
        import handler as h
        importlib.reload(h)

        scraper_called = []

        def mock_invoke_scraper():
            scraper_called.append(True)
            return SAMPLE_PAYLOAD

        monkeypatch.setattr(h, "_invoke_scraper", mock_invoke_scraper)

        response = h.lambda_handler(make_event(force_refresh=True), None)
        assert response["statusCode"] == 200
        assert len(scraper_called) == 1

    def test_cors_headers_always_present(self, aws_mocks, monkeypatch):
        """CORS headers must be present on all responses."""
        import importlib
        import handler as h
        importlib.reload(h)

        monkeypatch.setattr(h, "_invoke_scraper", lambda: None)

        response = h.lambda_handler(make_event(), None)
        assert "Access-Control-Allow-Origin" in response["headers"]
