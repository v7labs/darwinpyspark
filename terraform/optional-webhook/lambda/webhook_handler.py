"""Darwin webhook-stage receiver: validates the shared secret and lands the
payload in the landing bucket for Auto Loader ingestion (notebook 03)."""

import base64
import json
import os
import time
import uuid

import boto3

s3 = boto3.client("s3")

LANDING_BUCKET = os.environ["LANDING_BUCKET"]
AUTH_TOKEN = os.environ["AUTH_TOKEN"]


def handler(event, _context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("authorization") != AUTH_TOKEN:
        return {"statusCode": 403, "body": "forbidden"}

    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "invalid json"}

    item = payload.get("item") or {}
    item_id = (
        item.get("source_info", {}).get("item_id") or item.get("id") or uuid.uuid4().hex
    )
    key = (
        f"webhook/{time.strftime('%Y/%m/%d')}/{item_id}-{int(time.time() * 1000)}.json"
    )

    s3.put_object(
        Bucket=LANDING_BUCKET,
        Key=key,
        Body=json.dumps(payload).encode("utf-8"),
        ContentType="application/json",
    )
    return {"statusCode": 200, "body": json.dumps({"stored": key})}
