# Exam Analysis Suite

**Version: v0.3**

This project is a comprehensive suite for analyzing exam papers, composed of two main modules: a `preprocessor` for image handling and a `analyzer` for content analysis and knowledge graph generation.

## 📋 Version Information

- **Current Version**: v0.3 (2026-03-20)
- **Status**: 拼图测试工具稳定版 (Puzzle Test Tool Stable Version)
- **Next Features**: 拼图分类 (Puzzle Classification) 和 切片 (Slicing)

---

## Project Architecture

The suite is designed with a modular architecture:

- **`preprocessor/`**: A standalone module responsible for all image-based tasks, including perspective correction, layout analysis, and content extraction from images.
- **`analyzer/`**: A module that takes the structured output from the preprocessor, performs deeper analysis, interacts with a knowledge graph (Neo4j), and provides a web-based UI for querying.
- **`shared/`**: A shared library containing common code used by both modules, primarily for database models and session management.
- **`run_pipeline.py`**: A top-level script that orchestrates the end-to-end execution of the preprocessor and analyzer in sequence.

---

## Setup and Installation

### 1. Environment Prerequisite

**WARNING: This project strictly requires Python 3.10.**

Using any other version of Python will lead to dependency installation failures. Please ensure you have Python 3.10 installed on your system before proceeding.

### 2. Installation Steps

1.  **Create a Virtual Environment (using Python 3.10):**
    Open your terminal in the project root directory and run:
    ```powershell
    # Make sure to point to your Python 3.10 executable
    py -3.10 -m venv .venv
    ```

2.  **Activate the Virtual Environment:**
    ```powershell
    .\.venv\Scripts\Activate.ps1
    ```

3.  **Install All Dependencies:**
    Once the virtual environment is activated, install all required packages from the unified requirements file:
    ```powershell
    pip install -r requirements.txt
    ```

---

## How to Run

There are two primary ways to run this project:

### Option A: End-to-End Pipeline (Recommended)

This is the simplest way to process a new set of exam papers from start to finish.

Use the `run_pipeline.py` script and point it to your input directory:

```powershell
python run_pipeline.py --input-dir "preprocessor/my_test_images"
```

The script will automatically create a temporary workspace, run the preprocessor, feed its output to the analyzer, and save the final report.

### Option B: Run Modules Independently (for Debugging)

You can also run each module separately, which is useful for debugging specific parts of the pipeline.

**1. Running the `preprocessor`:**

Navigate to the `preprocessor` directory and use its `main.py` script. You must provide an input directory of images and an output directory for the results.

```powershell
cd preprocessor
python main.py --input-dir "path/to/your/exam_images" --output-dir "path/to/preprocessor_output"
```

**2. Running the `analyzer`:**

The `analyzer` module provides a full web service. To launch it, you must start 5 services in the correct order as detailed in its README.

Refer to the detailed instructions in [analyzer/README.md](analyzer/README.md) for launching the web UI and its backend services.

