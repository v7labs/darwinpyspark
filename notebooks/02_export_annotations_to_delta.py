# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Pull Darwin annotations into a typed Delta table
# MAGIC
# MAGIC Triggers a Darwin export release (or reuses one), waits until it's generated, downloads
# MAGIC the zip, parses Darwin JSON 2.0 with **darwin-py's own parser**, and MERGEs one row per
# MAGIC annotation into a Delta table. Re-running is idempotent.

# COMMAND ----------

# MAGIC %pip install --quiet "darwin-py>=3.4" "numpy<2"
dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("darwin_base_url", "https://darwin.v7labs.com", "Darwin base URL")
dbutils.widgets.text("team_slug", "", "Darwin team slug")
dbutils.widgets.text("dataset_slug", "databricks-sync", "Darwin dataset slug")
dbutils.widgets.text("release_name", "", "Release name (empty = create new)")
dbutils.widgets.text(
    "target_table",
    "main.v7_darwin.annotations",
    "Target Delta table (catalog.schema.table)",
)
dbutils.widgets.text("secret_scope", "v7-darwin", "Secret scope")
dbutils.widgets.text("secret_key", "darwin-api-key", "Secret key")

import os
import uuid

os.environ["DARWIN_BASE_URL"] = dbutils.widgets.get("darwin_base_url")

TEAM = dbutils.widgets.get("team_slug")
DATASET = dbutils.widgets.get("dataset_slug")
RELEASE_NAME = dbutils.widgets.get("release_name") or f"dbx-{uuid.uuid4().hex[:8]}"
TARGET_TABLE = dbutils.widgets.get("target_table")
API_KEY = dbutils.secrets.get(
    dbutils.widgets.get("secret_scope"), dbutils.widgets.get("secret_key")
)

assert TEAM, "team_slug widget is required"
assert os.environ["DARWIN_BASE_URL"], "darwin_base_url widget is required"

# COMMAND ----------

from darwin.client import Client

client = Client.from_api_key(API_KEY)
dataset = client.get_remote_dataset(f"{TEAM}/{DATASET}")

if not dbutils.widgets.get("release_name"):
    # dataset.export() only includes completed items; export everything not
    # archived/errored so in-progress annotations sync too (fiftyone-style filter)
    client.api_v2.export_dataset(
        name=RELEASE_NAME,
        format="darwin_json_2",
        include_authorship=True,
        include_token=False,
        dataset_slug=DATASET,
        filters={"not_statuses": ["archived", "error"]},
        annotation_class_ids=None,
        team_slug=TEAM,
    )
    print(f"Triggered export release: {RELEASE_NAME}")
else:
    print(f"Reusing release: {RELEASE_NAME}")

# COMMAND ----------

# MAGIC %md ## Wait for the release to be generated
# MAGIC (`get_release` raises NotFound until the export is ready — upstream helper candidate)

# COMMAND ----------

import time

from darwin.exceptions import NotFound

TIMEOUT_S = 10 * 60
POLL_INTERVAL_S = 10

deadline = time.time() + TIMEOUT_S
release = None
while release is None:
    try:
        release = dataset.get_release(RELEASE_NAME)
    except NotFound:
        if time.time() > deadline:
            raise TimeoutError(f"Release {RELEASE_NAME} not ready after {TIMEOUT_S}s")
        print("Release not ready yet...")
        time.sleep(POLL_INTERVAL_S)

print(f"Release ready: {RELEASE_NAME}")

# COMMAND ----------

import tempfile
import zipfile
from pathlib import Path

workdir = Path(tempfile.mkdtemp(prefix="darwin_export_"))
zip_path = workdir / "release.zip"
release.download_zip(zip_path)
with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(workdir / "extracted")

json_files = sorted((workdir / "extracted").rglob("*.json"))
print(f"{len(json_files)} annotation files in export")

# COMMAND ----------

# MAGIC %md ## Parse with darwin-py and flatten: one row per annotation

# COMMAND ----------

import json
from datetime import datetime

from darwin.utils import parse_darwin_json

rows = []
for jf in json_files:
    af = parse_darwin_json(jf)
    if af is None:
        continue
    # darwin-py's typed parse drops per-annotation updated_at — take it from the raw JSON
    raw_by_id = {
        a.get("id"): a for a in json.loads(jf.read_text()).get("annotations", [])
    }
    item_id = getattr(af, "item_id", None)
    for ann in af.annotations:
        main_type = getattr(
            getattr(ann, "annotation_class", None), "annotation_type", None
        )
        class_name = getattr(getattr(ann, "annotation_class", None), "name", None)
        ann_id = (
            getattr(ann, "id", None)
            or f"{item_id or af.filename}:{class_name}:{len(rows)}"
        )
        raw_ann = raw_by_id.get(ann_id, {})
        data_json = json.dumps(ann.data, default=str, sort_keys=True)
        # properties from the raw export JSON (clean dicts; the typed objects repr badly)
        properties_json = json.dumps(raw_ann.get("properties"), sort_keys=True)
        updated_at_raw = raw_ann.get("updated_at")
        rows.append(
            {
                "item_id": item_id,
                "item_name": af.filename,
                "item_path": getattr(af, "remote_path", None),
                "annotation_id": ann_id,
                "class_name": class_name,
                "annotation_type": main_type,
                "slot_names": list(getattr(ann, "slot_names", []) or []),
                "data_json": data_json,
                "properties_json": properties_json,
                "annotators": [
                    a.name for a in (getattr(ann, "annotators", None) or [])
                ],
                "reviewers": [r.name for r in (getattr(ann, "reviewers", None) or [])],
                "annotation_updated_at": (
                    datetime.fromisoformat(updated_at_raw) if updated_at_raw else None
                ),
                "release_name": RELEASE_NAME,
                "source_file": jf.name,
            }
        )

print(f"{len(rows)} annotations parsed")

# COMMAND ----------

from pyspark.sql.types import (
    ArrayType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

schema = StructType(
    [
        StructField("item_id", StringType()),
        StructField("item_name", StringType()),
        StructField("item_path", StringType()),
        StructField("annotation_id", StringType()),
        StructField("class_name", StringType()),
        StructField("annotation_type", StringType()),
        StructField("slot_names", ArrayType(StringType())),
        StructField("data_json", StringType()),
        StructField("properties_json", StringType()),
        StructField("annotators", ArrayType(StringType())),
        StructField("reviewers", ArrayType(StringType())),
        StructField("annotation_updated_at", TimestampType()),
        StructField("release_name", StringType()),
        StructField("source_file", StringType()),
    ]
)

from pyspark.sql import functions as F

df = spark.createDataFrame(rows, schema=schema).withColumn(
    "ingested_at", F.current_timestamp()
)
display(df.limit(10))

# COMMAND ----------

# MAGIC %md ## MERGE into the target Delta table (idempotent on item_id + annotation_id)

# COMMAND ----------

from delta.tables import DeltaTable

if not spark.catalog.tableExists(TARGET_TABLE):
    df.write.format("delta").saveAsTable(TARGET_TABLE)
    print(f"Created {TARGET_TABLE} with {df.count()} rows")
else:
    # Update only annotations whose Darwin updated_at is newer — unchanged rows
    # keep their original ingested_at/release_name.
    (
        DeltaTable.forName(spark, TARGET_TABLE)
        .alias("t")
        .merge(
            df.alias("s"),
            "t.item_id <=> s.item_id AND t.annotation_id = s.annotation_id",
        )
        # NOTE: if a future notebook version adds columns, DROP + recreate the table
        # (or ALTER TABLE ADD COLUMNS) — serverless lacks withSchemaEvolution/autoMerge
        .whenMatchedUpdateAll(
            condition="s.annotation_updated_at IS DISTINCT FROM t.annotation_updated_at"
        )
        .whenNotMatchedInsertAll()
        .execute()
    )
    print(f"Merged {df.count()} rows into {TARGET_TABLE} (only changed rows updated)")

display(
    spark.sql(
        f"SELECT class_name, annotation_type, count(*) AS n FROM {TARGET_TABLE} GROUP BY 1, 2"
    )
)
