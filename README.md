# 3D Mesh Batch Studio

A standalone Windows batch queue and memory watchdog for **ComfyUI** image-to-3D mesh workflows (`.glb`).

## Features
- **Zero-Dependency Windows GUI:** Built entirely with Python's standard library (`tkinter`, `urllib`, `ctypes`).
- **Auto-Detection:** Connects to an active ComfyUI server (`8188`, `8189`, `8190`, `8000`) or boots your local ComfyUI launcher (`Start ComfyUI FlashAttention.bat` / `run_nvidia_gpu.bat`).
- **Dynamic Node Mapping:** Automatically locates `LoadImage` and 3D save nodes (`Save3DAdvanced`, `Save3D`, `SaveGLTF`) from any ComfyUI API JSON.
- **Crash-Proof Resume:** Skips any reference image that already has a matching `.glb` in the output folder.
- **RAM Watchdog & Crash Recovery:** Flushes ComfyUI's CPU cache (`/free`) after every mesh while keeping weights warm in VRAM. Automatically sweeps dead console windows and restarts ComfyUI if system RAM exceeds 80% or if a generation crashes mid-mesh.

## Quick Start
1. Download `mesh_batch_studio.exe` from the **Releases** page on the right.
2. Select your **ComfyUI Root**, **Input Images**, **Output Meshes**, and **API Workflow JSON**.
3. Click **Start Batch Generation**.

*(Recommended: Add `--cache-none` to your ComfyUI startup `.bat` file for optimal RAM stability during large batches.)*

## Building from Source
```cmd
pip install pyinstaller
pyinstaller --noconfirm mesh_batch_studio.spec
