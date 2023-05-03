from setuptools import setup, find_packages

setup(
    name="darwinpyspark",
    version="0.0.1",
    author="Harry Hands",
    author_email="harry.hands@v7labs.com",
    description="A package for interacting with the V7 platform via Pyspark",
    url="https://github.com/v7labs/databricks",
    packages=find_packages(),
    install_requires=[
        "requests"
    ]
)
