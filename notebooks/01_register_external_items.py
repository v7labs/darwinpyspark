# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Register Databricks-governed files in V7 Darwin (in place, no copying)
# MAGIC
# MAGIC Lists files from an S3 external location (or UC Volume), registers them in a Darwin
# MAGIC dataset via the team's **external storage integration**, and polls until processing
# MAGIC finishes. Bytes never leave the customer bucket — Darwin reads them via presigned URLs.
# MAGIC
# MAGIC Prereqs: storage integration configured in the Darwin team (Settings → Storage) pointing
# MAGIC at the same bucket, and the Darwin API key in a Databricks secret scope.

# COMMAND ----------

# MAGIC %pip install --quiet "darwin-py>=3.4" "numpy<2"
# TODO: pin the exact version after validation
dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("darwin_base_url", "https://darwin.v7labs.com", "Darwin base URL")
dbutils.widgets.text("team_slug", "", "Darwin team slug")
dbutils.widgets.text("dataset_slug", "databricks-sync", "Darwin dataset slug")
dbutils.widgets.text("storage_name", "", "Darwin storage integration name")
dbutils.widgets.text(
    "source_path",
    "s3://YOUR-BUCKET/YOUR-PREFIX/",
    "Source path (s3:// or /Volumes/...)",
)
dbutils.widgets.text("secret_scope", "v7-darwin", "Secret scope")
dbutils.widgets.text("secret_key", "darwin-api-key", "Secret key")

import os

# Must be set before darwin-py reads its config
os.environ["DARWIN_BASE_URL"] = dbutils.widgets.get("darwin_base_url")

TEAM = dbutils.widgets.get("team_slug")
DATASET = dbutils.widgets.get("dataset_slug")
STORAGE_NAME = dbutils.widgets.get("storage_name")
SOURCE_PATH = dbutils.widgets.get("source_path").rstrip("/")
API_KEY = dbutils.secrets.get(
    dbutils.widgets.get("secret_scope"), dbutils.widgets.get("secret_key")
)

assert TEAM, "team_slug widget is required"
assert os.environ["DARWIN_BASE_URL"], "darwin_base_url widget is required"

# COMMAND ----------

from darwin.client import Client
from darwin.exceptions import NotFound

client = Client.from_api_key(API_KEY)

try:
    dataset = client.get_remote_dataset(f"{TEAM}/{DATASET}")
    print(f"Using existing dataset {TEAM}/{DATASET}")
except NotFound:
    dataset = client.create_dataset(DATASET, team_slug=TEAM)
    print(f"Created dataset {TEAM}/{DATASET}")

# COMMAND ----------

# MAGIC %md ## List files and derive storage keys
# MAGIC Storage keys are bucket-relative paths — exactly what the storage integration expects.

# COMMAND ----------

from urllib.parse import urlparse

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".tif",
    ".dcm",
    ".mp4",
    ".avi",
    ".mov",
    ".pdf",
}


def list_files_recursive(path):
    entries = []
    for info in dbutils.fs.ls(path):
        if info.isDir():
            entries.extend(list_files_recursive(info.path))
        elif os.path.splitext(info.name)[1].lower() in SUPPORTED_EXTENSIONS:
            entries.append(info.path)
    return entries


def to_storage_key(file_path):
    """s3://bucket/prefix/f.jpg -> prefix/f.jpg ; /Volumes/... paths keep their bucket-relative key."""
    parsed = urlparse(file_path)
    if parsed.scheme in ("s3", "s3a"):
        return parsed.path.lstrip("/")
    raise ValueError(
        f"Cannot derive a bucket-relative storage key from {file_path}. "
        "For UC Volumes, pass the underlying s3:// external location path instead."
    )


files = list_files_recursive(SOURCE_PATH)
storage_keys = [to_storage_key(f) for f in files]
print(f"{len(storage_keys)} files to register, e.g. {storage_keys[:3]}")

# COMMAND ----------

# MAGIC %md ## Register (chunked by 10 with retry inside darwin-py)

# COMMAND ----------

# NOTE: get_external_storage refuses read-only connections (darwin-py limitation, see README).
# This notebook therefore requires a read-write storage integration; read-only mode is phase 2.
object_store = client.get_external_storage(team_slug=TEAM, name=STORAGE_NAME)
print(object_store)

# Skip files that are already registered: mixing existing + new items in one
# register_existing batch trips a DUPLICATED_ITEM_FULL_PATH 422 on the backend
# (instead of blocking the existing ones) — and skipping is the correct
# incremental-sync behavior anyway.
existing_names = {item.filename for item in dataset.fetch_remote_files()}
new_keys = [k for k in storage_keys if k.split("/")[-1] not in existing_names]
print(
    f"{len(storage_keys) - len(new_keys)} already registered (skipped), {len(new_keys)} new"
)

# Teams with the DISABLE_UNPROCESSED_VIDEO_REGISTRATION feature can't register raw
# videos via external storage (403) — register them separately so one gated video
# doesn't fail the whole batch. Gated videos need the flag disabled or the
# register_locally_processed (read-only) path.
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov"}
video_keys = [k for k in new_keys if os.path.splitext(k)[1].lower() in VIDEO_EXTENSIONS]
other_keys = [k for k in new_keys if k not in video_keys]


def register_batch(keys, label):
    if not keys:
        return
    try:
        results = dataset.register(object_store, keys, preserve_folders=True)
        blocked = results.get("blocked_items", []) or results.get("blocked", [])
        registered = results.get("registered_items", []) or results.get(
            "registered", []
        )
        print(f"{label}: registered={len(registered)} blocked={len(blocked)}")
        for item in blocked:
            print(f"  blocked: {item}")
    except Exception as e:
        if (
            "UNPROCESSED_VIDEO_REGISTRATION" in str(e)
            or getattr(getattr(e, "response", None), "status_code", None) == 403
        ):
            print(
                f"WARNING: {label} registration forbidden for this team "
                f"(likely DISABLE_UNPROCESSED_VIDEO_REGISTRATION feature): {e}"
            )
        else:
            raise


register_batch(other_keys, "images/dicom/pdf")
register_batch(video_keys, "videos")

# COMMAND ----------

# MAGIC %md ## Poll until processing completes
# MAGIC (hand-rolled: darwin-py has no wait helper yet — upstream candidate)

# COMMAND ----------

import time
from collections import Counter

TIMEOUT_S = 15 * 60
POLL_INTERVAL_S = 10
ERROR_STATUSES = {"error", "errored", "failed"}

deadline = time.time() + TIMEOUT_S
while True:
    statuses = Counter(item.status for item in dataset.fetch_remote_files())
    print(dict(statuses))
    if any(s in ERROR_STATUSES for s in statuses):
        raise RuntimeError(f"Items failed processing: {dict(statuses)}")
    if statuses.get("processing", 0) == 0:
        break
    if time.time() > deadline:
        raise TimeoutError(
            f"Items still processing after {TIMEOUT_S}s: {dict(statuses)}"
        )
    time.sleep(POLL_INTERVAL_S)

print("All items processed.")

# COMMAND ----------

# MAGIC %md ## Item inventory (for eyeballing / joining later)

# COMMAND ----------

items = [
    (item.id, item.filename, item.path, item.status)
    for item in dataset.fetch_remote_files()
]
display(
    spark.createDataFrame(
        items, "item_id string, filename string, path string, status string"
    )
)

# COMMAND ----------

print(
    f"Open the dataset: {os.environ['DARWIN_BASE_URL']}/datasets — verify items RENDER in workview."
)
print(
    "If thumbnails don't render, check the bucket policy / KMS key policy for the V7 role."
)
