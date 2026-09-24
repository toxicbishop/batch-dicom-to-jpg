#!/usr/bin/env python3
"""
High-Performance CPU-Friendly DICOM to JPEG Converter
-----------------------------------------------------
- Uses modality LUT (RescaleSlope / Intercept) and VOI LUT (WindowCenter / WindowWidth)
  to ensure correct CT / X-ray diagnostic contrast.
- Multi-core CPU parallel processing (leaves 1 core free for system responsiveness).
- Replaces underscores (_) with hyphens (-) in all output filenames.
- Supports both batch conversion of folders and single file conversion.
- Resume capability (skips already converted files).
"""

import os
import sys
import argparse
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pydicom
from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut
from PIL import Image


def is_color(ds: pydicom.Dataset) -> bool:
    """Check if the DICOM file contains color image data."""
    photometric = getattr(ds, "PhotometricInterpretation", "")
    return photometric in ["RGB", "YBR_FULL", "YBR_FULL_422", "YBR_PARTIAL_422"]


def get_windowed_image(ds: pydicom.Dataset, pixel_array: np.ndarray) -> np.ndarray:
    """
    Applies Modality LUT (converts to Hounsfield Units for CT) and VOI LUT (windowing).
    Normalizes to 8-bit [0, 255] uint8.
    """
    try:
        pixel_array = apply_modality_lut(pixel_array, ds)
    except Exception as e:
        # Fallback to manual rescale if available
        slope = float(getattr(ds, "RescaleSlope", 1.0))
        intercept = float(getattr(ds, "RescaleIntercept", 0.0))
        if slope != 1.0 or intercept != 0.0:
            pixel_array = pixel_array.astype(np.float32) * slope + intercept

    try:
        pixel_array = apply_voi_lut(pixel_array, ds)
    except Exception as e:
        # Fallback to manual windowing if available
        wc = getattr(ds, "WindowCenter", None)
        ww = getattr(ds, "WindowWidth", None)
        if wc is not None and ww is not None:
            if hasattr(wc, "__iter__"):
                wc = wc[0]
            if hasattr(ww, "__iter__"):
                ww = ww[0]
            wc, ww = float(wc), float(ww)
            img_min = wc - ww / 2.0
            img_max = wc + ww / 2.0
            pixel_array = np.clip(pixel_array, img_min, img_max)

    # Normalize to 0-255 for 8-bit grayscale
    pixel_array = pixel_array.astype(np.float32)
    p_min = float(np.min(pixel_array))
    p_max = float(np.max(pixel_array))
    if p_max != p_min:
        pixel_array = (pixel_array - p_min) / (p_max - p_min) * 255.0
    else:
        pixel_array = np.zeros(pixel_array.shape, dtype=np.float32)

    # Handle MONOCHROME1 inversion (0 should be white, 255 black in raw, so invert)
    if getattr(ds, "PhotometricInterpretation", "").strip() == "MONOCHROME1":
        pixel_array = 255.0 - pixel_array

    return np.clip(pixel_array, 0, 255).astype(np.uint8)


def dcm2jpg(dcm_path: str, jpg_path: str, quality: int = 95) -> None:
    """Converts a single DICOM file to JPEG."""
    ds = pydicom.dcmread(dcm_path, force=True)

    if not hasattr(ds, "pixel_array") and "PixelData" not in ds:
        raise ValueError(f"DICOM file '{dcm_path}' does not contain pixel data.")

    pixel_array = ds.pixel_array

    if is_color(ds):
        photometric = getattr(ds, "PhotometricInterpretation", "")
        if photometric.startswith("YBR"):
            from pydicom.pixel_data_handlers.util import convert_color_space
            pixel_array = convert_color_space(pixel_array, photometric, "RGB")
        img = Image.fromarray(pixel_array)
        if img.mode != "RGB":
            img = img.convert("RGB")
    else:
        # Multi-frame grayscale
        if pixel_array.ndim == 3 and pixel_array.shape[0] > 1:
            base_path = Path(jpg_path)
            for idx, frame in enumerate(pixel_array):
                frame_8bit = get_windowed_image(ds, frame)
                frame_img = Image.fromarray(frame_8bit).convert("L")
                frame_out = base_path.parent / f"{base_path.stem}-frame-{idx:04d}.jpg"
                frame_img.save(frame_out, format="JPEG", quality=quality)
            return

        windowed = get_windowed_image(ds, pixel_array)
        img = Image.fromarray(windowed).convert("L")

    img.save(jpg_path, format="JPEG", quality=quality)


def process_single_task(args_tuple):
    """Worker task executed in parallel across CPU cores."""
    dcm_path_str, output_dir_str, quality, overwrite, preserve_subdirs, input_base_str = args_tuple
    dcm_path = Path(dcm_path_str)
    output_dir = Path(output_dir_str)
    input_base = Path(input_base_str) if input_base_str else None

    # Replace '_' with '-' in subfolder structure
    if preserve_subdirs and input_base:
        try:
            rel_dir = dcm_path.parent.relative_to(input_base)
            sanitized_rel_parts = [part.replace("_", "-") for part in rel_dir.parts]
            target_dir = output_dir.joinpath(*sanitized_rel_parts)
        except ValueError:
            target_dir = output_dir
    else:
        target_dir = output_dir

    target_dir.mkdir(parents=True, exist_ok=True)

    # Replace '_' with '-' in the filename stem
    base_stem = dcm_path.stem.replace("_", "-")
    out_jpg = target_dir / f"{base_stem}.jpg"

    if not overwrite and out_jpg.exists():
        return {"status": "skipped", "path": str(dcm_path), "msg": "Already exists"}

    try:
        dcm2jpg(str(dcm_path), str(out_jpg), quality=quality)
        return {"status": "success", "path": str(dcm_path), "saved": str(out_jpg)}
    except Exception as e:
        return {"status": "error", "path": str(dcm_path), "msg": str(e)}


def find_dcm_files(input_dir: Path):
    """Finds all DICOM files recursively."""
    candidates = []
    valid_exts = {".dcm", ".ima", ".dicom", ""}
    for root, _, files in os.walk(input_dir):
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in valid_exts:
                candidates.append(p)
    return candidates


def run_batch(input_dir: Path, output_dir: Path, workers: int, quality: int, flatten: bool, overwrite: bool):
    """Runs high-throughput parallel batch conversion."""
    output_dir.mkdir(parents=True, exist_ok=True)
    dcm_files = find_dcm_files(input_dir)
    total_files = len(dcm_files)

    print("=" * 60)
    print(" DICOM TO JPG BATCH CONVERTER")
    print("=" * 60)
    print(f" Input Directory      : {input_dir}")
    print(f" Output Directory     : {output_dir}")
    print(f" Files Found          : {total_files}")
    print(f" CPU Workers          : {workers} of {os.cpu_count() or 4} cores")
    print(f" JPEG Quality         : {quality}")
    print(f" Overwrite Existing   : {overwrite}")
    print("=" * 60)

    if total_files == 0:
        print(f"No DICOM files found in '{input_dir}'.")
        return

    start_time = time.time()
    preserve_subdirs = not flatten
    tasks = [
        (str(p), str(output_dir), quality, overwrite, preserve_subdirs, str(input_dir))
        for p in dcm_files
    ]

    success_count = 0
    skipped_count = 0
    error_count = 0
    errors = []

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_single_task, task): task[0] for task in tasks}

        last_print = time.time()
        for idx, future in enumerate(as_completed(futures), 1):
            res = future.result()
            status = res.get("status")

            if status == "success":
                success_count += 1
            elif status == "skipped":
                skipped_count += 1
            elif status == "error":
                error_count += 1
                errors.append((res.get("path"), res.get("msg")))

            now = time.time()
            if now - last_print > 0.25 or idx == total_files:
                elapsed = now - start_time
                fps = idx / elapsed if elapsed > 0 else 0
                pct = (idx / total_files) * 100
                print(
                    f"\rProgress: [{idx}/{total_files}] ({pct:.1f}%) | "
                    f"Converted: {success_count} | Skipped: {skipped_count} | Errors: {error_count} | "
                    f"Speed: {fps:.1f} files/sec",
                    end="",
                    flush=True
                )
                last_print = now

    total_time = time.time() - start_time
    print("\n" + "=" * 60)
    print(" CONVERSION SUMMARY")
    print("=" * 60)
    print(f" Elapsed Time         : {total_time:.2f} seconds")
    print(f" Throughput           : {total_files / total_time:.1f} files/sec")
    print(f" Successfully Created : {success_count}")
    print(f" Skipped              : {skipped_count}")
    print(f" Errors               : {error_count}")

    if errors:
        log_file = output_dir / "conversion-errors.log"
        with open(log_file, "w", encoding="utf-8") as f:
            for path, err in errors:
                f.write(f"{path}: {err}\n")
        print(f"\n[WARNING] {error_count} error(s) written to: {log_file}")
    print("=" * 60)


def main():
    # Support single-file direct call: python convert-dcm-to-jpg.py input.dcm output.jpg
    if len(sys.argv) == 3 and not sys.argv[1].startswith("-"):
        in_file = sys.argv[1]
        out_file = sys.argv[2]
        dcm2jpg(in_file, out_file)
        print(f"Saved JPEG image to {out_file}")
        return

    # Standard CLI Parser
    parser = argparse.ArgumentParser(
        description="Fast, CPU-friendly DICOM to JPG batch converter."
    )
    parser.add_argument(
        "-i", "--input",
        type=str,
        default=None,
        help="Input folder containing .dcm files (default: auto-detects 'original dcm' or 'original-dcm')"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="./output-jpg",
        help="Output folder for .jpg files (default: ./output-jpg)"
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=None,
        help="Number of CPU workers (default: CPU cores - 1)"
    )
    parser.add_argument(
        "-q", "--quality",
        type=int,
        default=95,
        help="JPEG quality 1-100 (default: 95)"
    )
    parser.add_argument(
        "--flatten",
        action="store_true",
        help="Flatten all output images into one folder instead of preserving subdirectories"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite already converted files"
    )

    args = parser.parse_args()

    # Determine input directory (auto-detect if not passed)
    if args.input:
        input_path = Path(args.input).resolve()
    else:
        for candidate in ["original dcm", "original-dcm", "input"]:
            p = Path(candidate).resolve()
            if p.exists():
                input_path = p
                break
        else:
            input_path = Path("./original dcm").resolve()

    if not input_path.exists():
        print(f"[ERROR] Input directory '{input_path}' not found.")
        print("Please provide the path using: python convert-dcm-to-jpg.py -i <path>")
        sys.exit(1)

    output_path = Path(args.output).resolve()
    cpu_count = os.cpu_count() or 4
    workers = args.workers if args.workers and args.workers > 0 else max(1, cpu_count - 1)

    run_batch(input_path, output_path, workers, args.quality, args.flatten, args.overwrite)


if __name__ == "__main__":
    main()