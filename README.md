# DCM to JPG Converter

[![Python](https://img.shields.io/badge/Python-3.12.x-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#)
[![Code Style](https://img.shields.io/badge/Code%20Style-PEP%208-orange.svg)](#)

A fast, CPU-optimized batch converter designed to process thousands of medical DICOM (`.dcm`) images to standard JPEG format. Built with proper medical imaging pipelines (Modality LUT and VOI LUT windowing) to prevent washed-out or pure-white CT/X-ray scans.

---

## Features

- **Medical LUT Normalization**: Applies `apply_modality_lut` (Hounsfield Unit rescaling) and `apply_voi_lut` (Window Center / Window Width) to ensure clinical contrast fidelity.
- **Color and Grayscale Support**: Handles standard grayscale, inverted `MONOCHROME1`, RGB, and YBR photometric interpretations.
- **Multi-Frame Support**: Automatically extracts cine loops and multi-slice 3D datasets into sequenced JPEG frames (`-frame-0000.jpg`).
- **CPU Multi-Core Acceleration**: Leverages Python `ProcessPoolExecutor` across available CPU cores while reserving one core for operating system responsiveness.
- **Fail-Safe and Resumable**: Skips already converted files automatically on restart. Corrupt files are logged to `conversion-errors.log` without interrupting the batch.
- **Filename Sanitization**: Automatically normalizes underscores (`_`) to hyphens (`-`) across output filenames and directory paths.

---

## Prerequisites

- Python 3.12 or higher
- Windows, macOS, or Linux

---

## Installation

1. Clone or navigate to the repository directory:
   ```bash
   cd D:\Code\DCM-toJPG
   ```

2. Create and activate a virtual environment:
   - **Windows (PowerShell)**:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - **Linux / macOS**:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Usage

### Batch Mode (Recommended)

Place DICOM files inside a folder named `original dcm` or `original-dcm` in the project root, then execute:

```powershell
python convert-dcm-to-jpg.py
```

By default, outputs will be generated in `./output-jpg`.

### Custom Directories and Parameters

You can specify custom input and output paths along with performance options:

```powershell
python convert-dcm-to-jpg.py -i "D:\path\to\dicom_folder" -o "D:\path\to\output_folder" -w 8 -q 95
```

### CLI Arguments Reference

| Option | Flag | Default | Description |
| :--- | :--- | :--- | :--- |
| `--input` | `-i` | Auto-detect | Path to directory containing `.dcm` files. |
| `--output` | `-o` | `./output-jpg` | Destination directory for converted JPEG images. |
| `--workers` | `-w` | CPU Cores - 1 | Number of concurrent CPU processes to allocate. |
| `--quality` | `-q` | `95` | JPEG compression quality (1-100). |
| `--flatten` | | `False` | Save all images into one flat folder instead of preserving source hierarchy. |
| `--overwrite`| | `False` | Force re-conversion of files that already exist in destination. |

### Single File Conversion

To convert an individual file:

```powershell
python convert-dcm-to-jpg.py input.dcm output.jpg
```

---

## Directory Structure

```text
DCM-toJPG/
|-- .venv/                     # Python virtual environment (ignored by git)
|-- .vscode/                   # Editor configuration
|   `-- settings.json
|-- convert-dcm-to-jpg.py      # Primary converter script
|-- requirements.txt           # Project dependencies
|-- .gitignore                 # Excluded directories and file patterns
|-- LICENSE                    # MIT license file
`-- README.md                  # Project documentation
```

---

## License

This project is licensed under the [MIT License](LICENSE). See the [LICENSE](LICENSE) file for details.
