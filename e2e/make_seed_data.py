#!/usr/bin/env python3
"""Generate dummy seed media for the Darwin<->Databricks PoC: images, a video,
and a DICOM file — so registration/processing is exercised across media types.

Usage:
    python3 -m venv .venv && .venv/bin/pip install pillow pydicom numpy
    .venv/bin/python make_seed_data.py [outdir]
    aws s3 cp <outdir>/ s3://<source-bucket>/data/ --recursive

The MP4 requires ffmpeg on PATH (brew install ffmpeg); it is skipped with a
warning otherwise.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OUTDIR = Path(sys.argv[1] if len(sys.argv) > 1 else "seed_data")
OUTDIR.mkdir(parents=True, exist_ok=True)


def make_images(n=3):
    for i in range(n):
        img = Image.new("RGB", (640, 480), (30 + 60 * i, 90, 160))
        draw = ImageDraw.Draw(img)
        draw.rectangle(
            [80 + 40 * i, 100, 300 + 40 * i, 320], outline=(255, 255, 255), width=4
        )
        draw.ellipse(
            [350, 150 + 30 * i, 550, 350 + 30 * i], outline=(255, 220, 0), width=4
        )
        draw.text((20, 20), f"v7-darwin-e2e image {i}", fill=(255, 255, 255))
        path = OUTDIR / f"image_{i}.png"
        img.save(path)
        print(f"wrote {path}")


def make_video():
    if not shutil.which("ffmpeg"):
        print("WARNING: ffmpeg not found — skipping video (brew install ffmpeg)")
        return
    path = OUTDIR / "video_0.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=4:size=640x480:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    print(f"wrote {path}")


def make_dicom():
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import (
        ExplicitVRLittleEndian,
        SecondaryCaptureImageStorage,
        generate_uid,
    )

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    path = OUTDIR / "dicom_0.dcm"
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientName = "PoC^Dummy"
    ds.PatientID = "V7-DBX-POC"
    ds.Modality = "OT"
    ds.StudyDate = "20260724"
    ds.Rows, ds.Columns = 256, 256
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0

    yy, xx = np.mgrid[0:256, 0:256]
    ds.PixelData = ((xx + yy) % 256).astype(np.uint8).tobytes()

    ds.save_as(path, enforce_file_format=True)
    print(f"wrote {path}")


def make_multislice_dicom(n_frames=8):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import (
        ExplicitVRLittleEndian,
        MultiFrameGrayscaleByteSecondaryCaptureImageStorage,
        generate_uid,
    )

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = MultiFrameGrayscaleByteSecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    path = OUTDIR / "dicom_multislice.dcm"
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientName = "PoC^MultiSlice"
    ds.PatientID = "V7-DBX-POC-MS"
    ds.Modality = "OT"
    ds.StudyDate = "20260724"
    ds.NumberOfFrames = str(n_frames)
    ds.Rows, ds.Columns = 256, 256
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.FrameIncrementPointer = 0x00181063  # Frame Time
    ds.FrameTime = "100"

    yy, xx = np.mgrid[0:256, 0:256]
    frames = [
        (((xx + yy) // 2 + 12 * i) % 256).astype(np.uint8) for i in range(n_frames)
    ]
    ds.PixelData = np.stack(frames).tobytes()

    ds.save_as(path, enforce_file_format=True)
    print(f"wrote {path} ({n_frames} frames)")


if __name__ == "__main__":
    make_images()
    make_video()
    make_dicom()
    make_multislice_dicom()
    print(f"\nSeed data in {OUTDIR.resolve()} — upload with:")
    print(f"  aws s3 cp {OUTDIR}/ s3://<source-bucket>/data/ --recursive")
