# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Stream webhook-stage results from the landing bucket into Delta
# MAGIC
# MAGIC The Darwin **webhook stage** posts a Darwin JSON 2.0 payload per item to the Lambda
# MAGIC (terraform), which lands it as a JSON object in the landing bucket. This notebook
# MAGIC ingests those files with Auto Loader into a bronze table. Run on a schedule or
# MAGIC continuously; `availableNow` processes the backlog and stops.
# MAGIC
# MAGIC This is the "annotations flow to Databricks **without V7 writing to any customer
# MAGIC bucket**" pattern (the Lambda writes under the customer's own IAM).

# COMMAND ----------

dbutils.widgets.text(
    "landing_path", "s3://CHANGE-ME-landing-bucket/webhook/", "Landing path"
)
dbutils.widgets.text(
    "target_table", "main.v7_darwin.webhook_events_bronze", "Bronze table"
)
dbutils.widgets.text(
    "checkpoint_path",
    "s3://CHANGE-ME-landing-bucket/_checkpoints/webhook_bronze",
    "Checkpoint",
)

LANDING_PATH = dbutils.widgets.get("landing_path")
TARGET_TABLE = dbutils.widgets.get("target_table")
CHECKPOINT = dbutils.widgets.get("checkpoint_path")

# COMMAND ----------

from pyspark.sql import functions as F

stream = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.schemaLocation", CHECKPOINT)
    .option("cloudFiles.inferColumnTypes", "true")
    # payload shape can evolve with Darwin releases; rescue instead of failing
    .option("cloudFiles.schemaEvolutionMode", "rescue")
    .load(LANDING_PATH)
    .withColumn("_ingested_at", F.current_timestamp())
    .withColumn("_source_file", F.col("_metadata.file_path"))
)

query = (
    stream.writeStream.format("delta")
    .option("checkpointLocation", CHECKPOINT)
    .trigger(availableNow=True)
    .toTable(TARGET_TABLE)
)
query.awaitTermination()

# COMMAND ----------

display(spark.sql(f"SELECT * FROM {TARGET_TABLE} ORDER BY _ingested_at DESC LIMIT 20"))
