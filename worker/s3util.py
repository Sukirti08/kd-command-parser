"""Tiny S3 helpers (SeaweedFS S3 gateway). Credentials: AWS_* env vars only."""
from __future__ import annotations

import os

import boto3
from botocore.exceptions import ClientError


def client(endpoint: str | None = None):
    return boto3.client(
        "s3",
        endpoint_url=endpoint or os.environ.get("S3_ENDPOINT", "http://localhost:8333"),
        region_name="us-east-1",
    )


def split(uri: str) -> tuple[str, str]:
    """'s3://bucket/key' or 'bucket/key' -> (bucket, key)."""
    uri = uri[5:] if uri.startswith("s3://") else uri
    bucket, _, key = uri.partition("/")
    return bucket, key


def get_text(uri: str, s3=None) -> str | None:
    s3 = s3 or client()
    bucket, key = split(uri)
    try:
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def put_bytes(uri: str, data: bytes, s3=None) -> None:
    s3 = s3 or client()
    bucket, key = split(uri)
    s3.put_object(Bucket=bucket, Key=key, Body=data)


def list_keys(uri_prefix: str, s3=None) -> list[str]:
    s3 = s3 or client()
    bucket, prefix = split(uri_prefix)
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", [])]
    return sorted(keys)
