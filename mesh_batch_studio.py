import os
import sys
import json
import time
import ctypes
import shutil
import threading
import subprocess
import urllib.request
import urllib.parse
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext

CONFIG_FILE = "batch_app_config.json"

DEFAULT_CONFIG = {
    "comfy_dir": r"C:\ComfyUI\ComfyUI",
    "ref_folder": r"C:\3D_Assets\Input_Images",
    "out_folder": r"C:\3D_Assets\Output_Meshes",
    "workflow_json": r"C:\ComfyUI\workflows\image_to_3d_batch_api.json",
}

RAM_RECYCLE_THRESHOLD = 80.0  # Recycle ComfyUI if system RAM % exceeds this


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def get_system_ram():
    """Returns (percent_used, used_gb, total_gb) via native Windows API."""
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    total_gb = stat.ullTotalPhys / (1024 ** 3)
    avail_gb = stat.ullAvailPhys / (1024 ** 3)
    used_gb = total_gb - avail_gb
    return float(stat.dwMemoryLoad), used_gb, total_gb


class MeshBatchStudio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("3D Mesh Batch Studio")
        self.geometry("800x680")
        self.minsize(680, 520)

        self.is_running = False
        self.comfy_process = None
        self.active_comfy_url = None
        self.config_data = self.load_config()
        self.build_ui()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return {**DEFAULT_CONFIG, **json.load(f)}
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        self.config_data = {
            "comfy_dir": self.comfy_dir_var.get().strip(),
            "ref_folder": self.ref_folder_var.get().strip(),
            "out_folder": self.out_folder_var.get().strip(),
            "workflow_json": self.json_path_var.get().strip(),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            self.log(f"[!] Warning: Could not save defaults: {e}")

    def build_ui(self):
        pad_opts = {'padx': 12, 'pady': 5}

        # 1. Path Configuration
        path_frame = ttk.LabelFrame(self, text=" Project Paths ", padding=12)
        path_frame.pack(fill="x", **pad_opts)

        self.comfy_dir_var = tk.StringVar(value=self.config_data["comfy_dir"])
        self.create_path_row(path_frame, "ComfyUI Root:", self.comfy_dir_var, self.browse_comfy_dir, 0)

        self.ref_folder_var = tk.StringVar(value=self.config_data["ref_folder"])
        self.create_path_row(path_frame, "Input Images:", self.ref_folder_var, self.browse_ref_folder, 1)

        self.out_folder_var = tk.StringVar(value=self.config_data["out_folder"])
        self.create_path_row(path_frame, "Output Meshes:", self.out_folder_var, self.browse_out_folder, 2)

        self.json_path_var = tk.StringVar(value=self.config_data["workflow_json"])
        self.create_path_row(path_frame, "API Workflow JSON:", self.json_path_var, self.browse_json, 3)

        # 2. Controls & Auto-status
        ctrl_frame = ttk.Frame(self, padding=8)
        ctrl_frame.pack(fill="x", **pad_opts)

        self.run_btn = ttk.Button(ctrl_frame, text="Start Batch Generation", command=self.toggle_batch)
        self.run_btn.pack(side="left", padx=4)

        self.save_btn = ttk.Button(ctrl_frame, text="Save Defaults", command=self.save_config)
        self.save_btn.pack(side="left", padx=4)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(ctrl_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side="right", fill="x", expand=True, padx=8)

        # 3. Log Console
        log_frame = ttk.LabelFrame(self, text=" Process Output ", padding=10)
        log_frame.pack(fill="both", expand=True, **pad_opts)

        self.log_widget = scrolledtext.ScrolledText(log_frame, wrap="word", height=15, font=("Consolas", 9))
        self.log_widget.pack(fill="both", expand=True)

    def create_path_row(self, parent, label_text, str_var, browse_cmd, row_idx):
        ttk.Label(parent, text=label_text).grid(row=row_idx, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, textvariable=str_var)
        entry.grid(row=row_idx, column=1, sticky="ew", padx=8, pady=4)
        btn = ttk.Button(parent, text="Browse...", command=browse_cmd)
        btn.grid(row=row_idx, column=2, sticky="e", pady=4)
        parent.columnconfigure(1, weight=1)

    def browse_comfy_dir(self):
        p = filedialog.askdirectory(initialdir=self.comfy_dir_var.get())
        if p:
            self.comfy_dir_var.set(os.path.normpath(p))

    def browse_ref_folder(self):
        p = filedialog.askdirectory(initialdir=self.ref_folder_var.get())
        if p:
            self.ref_folder_var.set(os.path.normpath(p))

    def browse_out_folder(self):
        p = filedialog.askdirectory(initialdir=self.out_folder_var.get())
        if p:
            self.out_folder_var.set(os.path.normpath(p))

    def browse_json(self):
        cur_file = self.json_path_var.get()
        init_dir = os.path.dirname(cur_file) if cur_file and os.path.exists(cur_file) else "."
        p = filedialog.askopenfilename(initialdir=init_dir, filetypes=[("JSON files", "*.json")])
        if p:
            self.json_path_var.set(os.path.normpath(p))

    def log(self, message):
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.see(tk.END)

    # =========================================================================
    # MEMORY & PROCESS MANAGEMENT
    # =========================================================================

    def purge_comfy_ram(self, server_url):
        """Flushes ComfyUI execution cache without unloading 3D models from VRAM."""
        try:
            payload = json.dumps({"unload_models": False, "free_memory": True}).encode("utf-8")
            req = urllib.request.Request(
                f"{server_url}/free",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception as e:
            self.log(f"  -> [!] RAM purge ping skipped: {e}")

    def cleanup_all_comfy_instances(self, server_url=None):
        """Terminates all ComfyUI python processes and closes any open/paused batch console windows."""
        if self.comfy_process is not None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.comfy_process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                pass
            self.comfy_process = None

        ps_cmd = (
            "Get-CimInstance Win32_Process | Where-Object { "
            "($_.Name -eq 'python.exe' -and $_.CommandLine -like '*ComfyUI*main.py*') -or "
            "($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*Start ComfyUI*') "
            "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception:
            pass

        for title_pattern in [
            "ComfyUI-Easy-Install*",
            "Select ComfyUI-Easy-Install*",
            "Administrator: ComfyUI-Easy-Install*",
        ]:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/FI", "IMAGENAME eq cmd.exe", "/FI", f"WINDOWTITLE eq {title_pattern}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                pass

        if server_url:
            try:
                port = urllib.parse.urlparse(server_url).port or 8188
                out = subprocess.check_output(
                    ["netstat", "-ano"],
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                for line in out.splitlines():
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.split()
                        if parts and parts[-1].isdigit() and int(parts[-1]) != os.getpid():
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", parts[-1]],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW
                            )
            except Exception:
                pass

    def ensure_healthy_ram(self, server_url, comfy_root):
        """Recycles ComfyUI if C++ heap fragmentation pushes RAM past threshold."""
        ram_pct, used_gb, total_gb = get_system_ram()
        if ram_pct < RAM_RECYCLE_THRESHOLD:
            return server_url

        self.log(f"\n[!] System RAM at {ram_pct:.0f}% ({used_gb:.1f}/{total_gb:.1f} GB). Recycling ComfyUI to clear heap...")
        self.cleanup_all_comfy_instances(server_url)
        time.sleep(4)

        new_url = self.launch_and_acquire_comfy(comfy_root)
        if not new_url:
            raise RuntimeError("Failed to restart ComfyUI after RAM threshold recycle.")
        return new_url

    # =========================================================================
    # AUTO-DETECTION ENGINE
    # =========================================================================

    def detect_active_comfy_url(self):
        """Scans standard ports to see if ComfyUI is already responding."""
        common_ports = [8188, 8189, 8190, 8000]
        for port in common_ports:
            url = f"http://127.0.0.1:{port}"
            try:
                req = urllib.request.Request(f"{url}/system_stats", headers={"User-Agent": "BatchApp"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status == 200:
                        return url
            except Exception:
                continue
        return None

    def launch_and_acquire_comfy(self, comfy_root):
        """Closes any dead/paused ComfyUI windows, then launches a single fresh instance."""
        self.cleanup_all_comfy_instances()
        time.sleep(2)

        parent_dir = os.path.dirname(comfy_root)

        candidates = [
            os.path.join(parent_dir, "Start ComfyUI FlashAttention.bat"),
            os.path.join(parent_dir, "Start ComfyUI KitchenAttention.bat"),
            os.path.join(parent_dir, "Start ComfyUI.bat"),
            os.path.join(parent_dir, "run_nvidia_gpu.bat"),
            os.path.join(comfy_root, "run_nvidia_gpu.bat"),
        ]
        launcher = next((c for c in candidates if os.path.exists(c)), None)

        if launcher:
            self.log(f"[*] Booting ComfyUI launcher: {launcher}")
            self.comfy_process = subprocess.Popen(
                ["cmd.exe", "/c", launcher],
                cwd=os.path.dirname(launcher),
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            embedded_py = os.path.join(parent_dir, "python_embeded", "python.exe")
            main_py = os.path.join(comfy_root, "main.py")
            if os.path.exists(embedded_py) and os.path.exists(main_py):
                self.log(f"[*] Launching via embedded python: {main_py}")
                self.comfy_process = subprocess.Popen(
                    [embedded_py, "-s", main_py, "--windows-standalone-build", "--cache-none"],
                    cwd=comfy_root,
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
            else:
                self.log("[!] Error: Could not locate Start ComfyUI batch file or embedded Python environment.")
                return None

        self.log("[*] Waiting for ComfyUI to complete startup...")
        timeout = 120
        start = time.time()
        while time.time() - start < timeout:
            if not self.is_running:
                return None
            live_url = self.detect_active_comfy_url()
            if live_url:
                self.log(f"[✓] Acquired ComfyUI service at: {live_url}")
                time.sleep(3)
                return live_url
            time.sleep(2)

        self.log("[!] Error: ComfyUI launch timed out after 120s.")
        return None

    def auto_detect_node_ids(self, workflow_dict):
        """Scans the API JSON to locate the exact node IDs for LoadImage and 3D export nodes."""
        load_id = None
        save_id = None

        export_targets = [
            "Save3DAdvanced",
            "Save3D",
            "SaveGLB",
            "SaveGLTF",
            "Hy3DExportMesh",
            "ExportMesh",
            "SaveMesh",
            "MeshToFile3D",
        ]

        for node_id, data in workflow_dict.items():
            if not isinstance(data, dict):
                continue
            class_type = data.get("class_type", "")

            if class_type == "LoadImage":
                load_id = str(node_id)
            elif any(target in class_type for target in export_targets):
                if "Save3DAdvanced" in class_type or "SaveGLB" in class_type or save_id is None:
                    save_id = str(node_id)

        return load_id, save_id

    # =========================================================================
    # BATCH WORKER
    # =========================================================================

    def toggle_batch(self):
        if self.is_running:
            self.is_running = False
            self.log("[*] Cancel requested. Halting after active mesh finishes...")
            self.run_btn.config(state="disabled")
            return

        self.save_config()
        self.is_running = True
        self.run_btn.config(text="Stop Batch")
        threading.Thread(target=self.batch_worker, daemon=True).start()

    def batch_worker(self):
        comfy_root = self.comfy_dir_var.get()
        ref_dir = self.ref_folder_var.get()
        out_dir = self.out_folder_var.get()
        json_path = self.json_path_var.get()

        comfy_input = os.path.join(comfy_root, "input")
        comfy_output = os.path.join(comfy_root, "output")

        # 1. Validate File Paths
        for label, p in [("ComfyUI Root", comfy_root), ("Input Folder", ref_dir), ("API JSON", json_path)]:
            if not os.path.exists(p):
                self.log(f"[!] Path Error: {label} not found: {p}")
                self.reset_run_state()
                return

        # 2. Parse JSON & Auto-Detect Node IDs
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                workflow = json.load(f)
        except Exception as e:
            self.log(f"[!] Failed to parse API JSON: {e}")
            self.reset_run_state()
            return

        load_id, save_id = self.auto_detect_node_ids(workflow)

        if not load_id or not save_id:
            self.log(f"[!] Node Detection Failed -> LoadImage: '{load_id}', Export3D: '{save_id}'")
            self.log("[!] Make sure the JSON is saved in API format with standard LoadImage and 3D export nodes.")
            self.reset_run_state()
            return

        self.log(f"[✓] Auto-detected workflow nodes: LoadImage [Node {load_id}] | Export3D [Node {save_id}]")

        # 3. Acquire Live ComfyUI Server
        server_url = self.detect_active_comfy_url()
        if not server_url:
            self.log("[*] No active ComfyUI instance detected. Launching process...")
            server_url = self.launch_and_acquire_comfy(comfy_root)
            if not server_url:
                self.reset_run_state()
                return
        else:
            self.log(f"[✓] Connected to live ComfyUI instance at: {server_url}")

        self.active_comfy_url = server_url

        # 4. Prepare Staging Directories
        os.makedirs(comfy_input, exist_ok=True)
        os.makedirs(comfy_output, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)

        valid_ext = ('.png', '.jpg', '.jpeg', '.webp')
        images = sorted([f for f in os.listdir(ref_dir) if f.lower().endswith(valid_ext)])
        total = len(images)
        self.log(f"[*] Found {total} reference files to process.")

        # 5. Execute Sequential Queue
        for idx, img_file in enumerate(images, 1):
            if not self.is_running:
                break

            base_name = os.path.splitext(img_file)[0]
            target_mesh = os.path.join(out_dir, f"{base_name}.glb")

            self.progress_var.set((idx - 1) / total * 100)

            if os.path.exists(target_mesh):
                self.log(f"[{idx}/{total}] Skipping (already exists): {base_name}.glb")
                continue

            # Retry up to 2 times if ComfyUI crashes mid-generation
            for attempt in range(1, 3):
                if not self.is_running:
                    break

                # Check RAM and recycle ComfyUI if heap leaks build up
                try:
                    server_url = self.ensure_healthy_ram(server_url, comfy_root)
                    self.active_comfy_url = server_url
                except Exception as e:
                    self.log(f"[!] {e}")
                    self.is_running = False
                    break

                ram_pct, used_gb, _ = get_system_ram()
                retry_tag = f" [Retry {attempt - 1}]" if attempt > 1 else ""
                self.log(f"\n[{idx}/{total}]{retry_tag} Processing: {img_file} (RAM: {used_gb:.1f} GB / {ram_pct:.0f}%)")

                # Stage image directly into ComfyUI's input
                src_img = os.path.join(ref_dir, img_file)
                staged_name = f"_batch_{idx}_{img_file}"
                staged_path = os.path.join(comfy_input, staged_name)
                shutil.copyfile(src_img, staged_path)

                # Inject parameters via detected node IDs
                workflow[load_id].setdefault("inputs", {})["image"] = staged_name
                workflow[save_id].setdefault("inputs", {})["filename_prefix"] = f"batch_{base_name}"
                start_time = time.time()

                # Submit prompt
                try:
                    payload = json.dumps({"prompt": workflow}).encode("utf-8")
                    req = urllib.request.Request(
                        f"{server_url}/prompt",
                        data=payload,
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        prompt_id = json.loads(resp.read().decode("utf-8"))["prompt_id"]
                    self.log(f"  -> Dispatched [ID: {prompt_id[:8]}...]. Generating 3D mesh...")
                except Exception as e:
                    self.log(f"  -> [!] ComfyUI Request Failed: {e}. Recycling ComfyUI...")
                    if os.path.exists(staged_path):
                        os.remove(staged_path)
                    self.cleanup_all_comfy_instances(server_url)
                    time.sleep(3)
                    server_url = self.launch_and_acquire_comfy(comfy_root)
                    if not server_url:
                        self.is_running = False
                        break
                    continue

                # Poll history for single-ticket completion (with crash detection)
                completed = False
                crashed = False
                missed_pings = 0

                while self.is_running:
                    try:
                        with urllib.request.urlopen(f"{server_url}/history/{prompt_id}", timeout=5) as resp:
                            missed_pings = 0
                            hist = json.loads(resp.read().decode("utf-8"))
                            if prompt_id in hist:
                                completed = True
                                break
                    except Exception:
                        missed_pings += 1
                        if missed_pings >= 3:
                            crashed = True
                            break
                    time.sleep(3)

                if os.path.exists(staged_path):
                    os.remove(staged_path)

                if crashed:
                    self.log("  -> [!] ComfyUI process dropped mid-mesh. Closing dead console and restarting...")
                    self.cleanup_all_comfy_instances(server_url)
                    time.sleep(3)
                    server_url = self.launch_and_acquire_comfy(comfy_root)
                    if not server_url:
                        self.is_running = False
                        break
                    continue

                # Move output asset to target location
                if completed:
                    time.sleep(1)
                    newest_glb = self.find_newest_file(comfy_output, ".glb")
                    if newest_glb and os.path.getmtime(newest_glb) >= (start_time - 5):
                        shutil.move(newest_glb, target_mesh)
                        self.log(f"  -> Delivered: {base_name}.glb")
                    else:
                        self.log(f"  -> [!] Warning: Mesh file not found in ComfyUI output.")

                    # Flush ComfyUI execution cache
                    self.purge_comfy_ram(server_url)
                    break

        self.progress_var.set(100)
        self.log("\n[Finished] All tasks complete.")
        self.reset_run_state()

    def find_newest_file(self, folder, ext):
        matches = []
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(ext):
                    p = os.path.join(root, f)
                    matches.append((p, os.path.getmtime(p)))
        if not matches:
            return None
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[0][0]

    def reset_run_state(self):
        self.is_running = False
        self.run_btn.config(text="Start Batch Generation", state="normal")


if __name__ == "__main__":
    app = MeshBatchStudio()
    app.mainloop()