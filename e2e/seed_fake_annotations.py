#!/usr/bin/env python3
"""Seed fake bounding-box annotations onto the registered image items via
darwin-py's importer, so the export→Delta notebook has data to pull without
manual annotation.

Usage:
    DARWIN_BASE_URL=<your-darwin-url> \
    python seed_fake_annotations.py <api_key> <team_slug> <dataset_slug>
"""

import json
import sys
import tempfile
from pathlib import Path

from darwin.client import Client
from darwin.importer import import_annotations
from darwin.importer.formats.darwin import parse_path as darwin_parser

API_KEY = sys.argv[1]
TEAM = sys.argv[2]
DATASET = sys.argv[3]
CLASS_NAME = "poc-box"

client = Client.from_api_key(API_KEY)
dataset = client.get_remote_dataset(f"{TEAM}/{DATASET}")

existing = {
    (c["name"], c["annotation_types"][0] if c.get("annotation_types") else None)
    for c in dataset.fetch_remote_classes(team_wide=True)
}
if (CLASS_NAME, "bounding_box") not in existing:
    dataset.create_annotation_class(CLASS_NAME, "bounding_box")
    print(f"created class {CLASS_NAME}")

image_items = [
    item
    for item in dataset.fetch_remote_files()
    if item.filename.lower().endswith(".png")
]
print(f"{len(image_items)} image items to annotate")

workdir = Path(tempfile.mkdtemp(prefix="fake_anns_"))

# .v7/metadata.json defines the property schema; the importer creates/updates the
# team property from it and attaches the per-annotation values below.
metadata_dir = workdir / ".v7"
metadata_dir.mkdir()
(metadata_dir / "metadata.json").write_text(
    json.dumps(
        {
            "version": "1.0",
            "classes": [
                {
                    "name": CLASS_NAME,
                    "type": "bounding_box",
                    "properties": [
                        {
                            "name": "quality",
                            "type": "single_select",
                            "description": "PoC fake quality label",
                            "required": False,
                            "granularity": "annotation",
                            "property_values": [
                                {"value": "good", "color": "rgba(0,255,0,1.0)"},
                                {"value": "bad", "color": "rgba(255,0,0,1.0)"},
                            ],
                        }
                    ],
                }
            ],
        }
    )
)


def prop(value):
    return [
        {
            "frame_index": "global",
            "name": "quality",
            "type": "single_select",
            "value": value,
        }
    ]


paths = []
for i, item in enumerate(image_items):
    payload = {
        "version": "2.0",
        "item": {"name": item.filename, "path": item.path or "/"},
        "annotations": [
            {
                "name": CLASS_NAME,
                "bounding_box": {
                    "x": 80.0 + 40 * i,
                    "y": 100.0,
                    "w": 220.0,
                    "h": 220.0,
                },
                "properties": prop("good"),
            },
            {
                "name": CLASS_NAME,
                "bounding_box": {
                    "x": 350.0,
                    "y": 150.0 + 30 * i,
                    "w": 200.0,
                    "h": 200.0,
                },
                "properties": prop("bad" if i % 2 else "good"),
            },
        ],
    }
    p = workdir / f"{Path(item.filename).stem}.json"
    p.write_text(json.dumps(payload))
    paths.append(p)

# append=False + overwrite=True → replace existing annotations non-interactively
import_annotations(
    dataset, darwin_parser, paths, append=False, overwrite=True, class_prompt=False
)
print(f"imported fake bboxes (+quality property) onto {len(paths)} items")
