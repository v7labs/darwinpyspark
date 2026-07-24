# Developer guide — end-to-end test rig

Everything needed to validate the full loop from scratch: a disposable
KMS-encrypted bucket, dummy media covering every supported type, fake
annotations (so no manual labeling is needed), and the same setup script
customers use. A colleague with the right credentials should be able to
replicate the whole flow with these scripts alone.

## Prerequisites

- An AWS account you can create S3/KMS/IAM resources in (use a dev account).
- A Darwin **test team** (never test against a customer or production team)
  with: an API key, external-storage allowance on its plan, and — for the video
  case — unprocessed video registration enabled.
- A Databricks workspace with Unity Catalog and a SQL warehouse.
- Locally: `terraform`, `aws` CLI, `databricks` CLI, `python3`, `ffmpeg`
  (for the test video).

## 1. Infrastructure (terraform)

```bash
cd terraform
terraform init
terraform apply \
  -var aws_profile=<your-dev-profile> \
  -var darwin_origin=<your-darwin-url>        # bucket CORS; defaults to prod
# outputs: source bucket name + KMS key ARN
```

This creates a bucket encrypted with a **customer-managed KMS key**, with the
bucket policy and key policy granting Darwin's external-storage role — i.e. the
exact setup an enterprise customer needs (the key-policy statement in
`terraform/main.tf` doubles as copy-paste material for customers).

`terraform/optional-webhook/` is a separate root module with a webhook-stage →
Lambda → landing-bucket pipeline for streaming sync. It is optional; the
scheduled export job is the primary sync path.

## 2. Seed test media

```bash
python3 -m venv .venv && .venv/bin/pip install pillow pydicom numpy
.venv/bin/python e2e/make_seed_data.py seed_data
aws s3 cp seed_data/ s3://<source-bucket>/data/ --recursive --profile <your-dev-profile>
```

Generates 3 images, a 4-second MP4, a single-frame DICOM, and an 8-frame
multi-slice DICOM — one file per processing pipeline.

## 3. Wire up Databricks + Darwin

- Unity Catalog: storage credential + external location for the bucket
  (Catalog → External Data; the AWS Quickstart flow generates the IAM role).
- `.env`: `cp .env.sample .env`, point `DARWIN_BASE_URL` at your **test**
  environment, `SOURCE_PATH` at `s3://<source-bucket>/data/`.
- Darwin storage integration: `./scripts/create_storage_integration.sh
  <source-bucket> <aws-region>`.
- `./scripts/setup_databricks.sh`.

## 4. Run the loop

1. Run the **`v7-darwin-register`** job → all seed items should reach
   processing status `complete` (this validates bucket policy + KMS).
2. Seed fake annotations (two bounding boxes per image, each carrying a
   `quality` single-select **property**, so properties are exercised too):

   ```bash
   .venv/bin/pip install "darwin-py>=3.4"
   DARWIN_BASE_URL=<your-darwin-url> .venv/bin/python e2e/seed_fake_annotations.py \
     <api-key> <team-slug> <dataset-slug>
   ```

3. Run **`v7-darwin-export-sync`** → the target table should contain 6 rows
   (2 per image) with `data_json`, `properties_json`, `annotation_updated_at`.
4. Run it **again** → zero rows should change (`ingested_at` untouched):
   the MERGE only updates rows whose Darwin `updated_at` moved.
5. Re-run seeding (it overwrites) or edit an annotation in Darwin, run the sync
   again → only the touched rows get a new `ingested_at`.

## Test matrix

- [ ] register: images, video, DICOM (single + multi-slice) all `complete`
- [ ] items render in the Darwin workview (presigned URLs + KMS decrypt)
- [ ] KMS negative test: remove Darwin from the key policy → rendering breaks → restore
- [ ] re-running register skips existing files (incremental)
- [ ] export → Delta: rows, properties, authorship present
- [ ] no-change re-run touches zero rows; changed annotation updates exactly one
- [ ] scheduled job runs unattended

## Cleanup

```bash
cd terraform && terraform destroy -var aws_profile=<your-dev-profile>
```

Then archive the Darwin dataset and delete the Databricks jobs/notebooks/schema.
