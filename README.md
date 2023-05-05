# V7 DarwinPyspark

`DarwinPyspark` is the official library for managing data in Databricks and seamlessly sending that data to be managed and used in [V7](https://darwin.v7labs.com). It provides an easy-to-use interface for interacting with V7's API, allowing users to upload and download datasets, as well as perform various operations on the data.

## Features
- Upload data from a PySpark DataFrame to V7
- Download data from V7 and load it into a PySpark DataFrame
- Handle data registration, uploading, and confirmation with V7
- Efficiently manage large datasets and data exports

## Installation

```
pip install darwinpyspark
```

## Usage
This framework is designed to be used alongside our python SDK, see examples of darwin-py in our docs [here](https://docs.v7labs.com/docs/use-the-darwin-python-library-to-manage-your-data).

To get started with DarwinPyspark, you'll first need to create a DarwinPyspark instance with your V7 API key, team slug, and dataset slug:

```python
from darwinpyspark import DarwinPyspark

API_KEY = "your_api_key"
team_slug = "your_team_slug"
dataset_slug = "your_dataset_slug"

dp = DarwinPyspark(API_KEY, team_slug, dataset_slug)
```

### Uploading Data
To upload a PySpark DataFrame to V7, use the upload_items method:
```python
# Assume `df` is your PySpark DataFrame with columns 'object_url' and 'file_name'
dp.upload_items(df)
```
The upload_items method takes a PySpark DataFrame with columns 'object_url' (accessible open or presigned URL for the image) and 'file_name' (the name you want the file to be listed as in V7).

Now, users would interact with this data in the V7 platform - e.g. create ML workflows, annotate files such as images, videos, dicoms or test model performance etc.

### Downloading Data
To download data from V7 as a PySpark DataFrame, use the download_export method:
```python
export_name = "your_export_name"
export_df = dp.download_export(export_name)
```

## License
DarwinPyspark is released under the [MIT License](https://opensource.org/license/mit/).
