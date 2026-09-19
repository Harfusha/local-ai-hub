# llama.cpp SYCL on Intel GPUs

Use this optional backend only when an Intel Arc/iGPU is the inference device and an existing llama.cpp router is actually needed. Local AI Hub routes 0.5B preprocessing, 1.5B quick requests, 3B complex requests, 7B hardest reasoning, and Qwen3-VL vision to one loopback llama.cpp router. The router loads one model at a time. The Hub never installs or starts llama.cpp automatically and does not fall back to Ollama in the default policy.

NVIDIA and AMD discrete GPUs do not trigger Ollama or llama.cpp installation. AMD iGPU is not an Intel SYCL target and should use deterministic/CPU paths unless another explicitly configured backend exists. Do not set `llama_cpp.mode = "on"` on those machines. Official llama.cpp SYCL support targets Intel GPUs; its documented support includes Intel Arc and newer Intel integrated GPUs, while other-vendor GPU support is not the supported target for this backend. [SYCL backend support](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md)

## When to install it

Install llama.cpp SYCL after Local AI Hub has been installed, only on a machine where inference should use an Intel GPU. First verify the driver and device. On Windows 11, use the official Windows x64 SYCL release and check that `llama-server.exe --list-devices` lists the Intel GPU as `SYCL0` or another `SYCL*` device. The official Windows bundle includes the SYCL runtime DLLs, so a separate oneAPI installation is not required. [Official releases](https://github.com/ggml-org/llama.cpp/releases) · [Windows SYCL instructions](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md#option-1-download-the-binary-package-directly)

If the device is not listed, stop here: the Hub will not make a CPU or Vulkan server into a SYCL server. Leave `mode = "auto"`; the Hub will use deterministic/indexed operations and report the optional local-model backend as unavailable.

## Windows installation and setup

1. Download the current `Windows x64 (SYCL)` archive from the [official llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) and extract it, for example to `$env:LOCALAPPDATA\llama.cpp-sycl`. Keep the extracted DLLs beside `llama-server.exe`.
2. Make a persistent model directory and obtain trusted GGUF weight files from the model publisher. Do not install Ollama or use an Ollama cache as an implicit prerequisite:

   ```powershell
   $modelDir = Join-Path $env:LOCALAPPDATA 'llama.cpp-sycl\models'
   New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
   ```

   Place the four `qwen2.5-coder-*.gguf` files plus `qwen3-vl-4b-q4_k_m.gguf` and `qwen3-vl-4b-mmproj-q8_0.gguf` in that directory when vision is enabled. If a required file is unavailable, stop and report it; do not install a second model runtime just to obtain weights.
3. Create `models.ini` in the extracted llama.cpp directory. Stable internal aliases avoid model-tag punctuation being rewritten by the router; the Hub maps its own model tags to these aliases. The preset caps residency at one model to match the Hub scheduler:

   ```ini
   version = 1

   [*]
   n-gpu-layers = 99
   device = SYCL0
   c = 32768
   load-on-startup = false

   [hub-qwen-05]
   model = ./models/qwen2.5-coder-0.5b.gguf
   c = 16384

   [hub-qwen-15]
   model = ./models/qwen2.5-coder-1.5b.gguf
   c = 32768

   [hub-qwen-3]
   model = ./models/qwen2.5-coder-3b.gguf

   [hub-qwen-7]
   model = ./models/qwen2.5-coder-7b.gguf

   [hub-qwen-vl]
   model = ./models/qwen3-vl-4b-q4_k_m.gguf
   mmproj = ./models/qwen3-vl-4b-mmproj-q8_0.gguf
   c = 8192
   ```

   `./models/...` is relative to the server's working directory. If the machine has less than 24 GB system memory or model loading fails, reduce the `c` values and the corresponding `context_length` values in `config.toml` to the same size. The Intel SYCL guide calls out shared memory as a model-size limit. [llama.cpp router presets and model loading](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#using-multiple-models)
4. In PowerShell, verify the device and start the local model router:

   ```powershell
   $llamaDir = Join-Path $env:LOCALAPPDATA 'llama.cpp-sycl'
   Push-Location $llamaDir
   .\llama-server.exe --list-devices
   .\llama-server.exe --models-preset .\models.ini --models-max 1 --host 127.0.0.1 --port 12438 --device SYCL0 -ngl 99 --no-ui
   ```

   Leave the server running. For startup at user logon, create a hidden launcher in the user's Startup folder:

   ```powershell
   $dir = Join-Path $env:LOCALAPPDATA 'llama.cpp-sycl'
   $launcher = Join-Path $dir 'start-llama-server.vbs'
   @'
   Set shell = CreateObject("WScript.Shell")
   baseDir = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\llama.cpp-sycl")
   shell.CurrentDirectory = baseDir
   command = Chr(34) & baseDir & "\llama-server.exe" & Chr(34) & " --models-preset " & Chr(34) & baseDir & "\models.ini" & Chr(34) & " --models-max 1 --host 127.0.0.1 --port 12438 --device SYCL0 -ngl 99 --no-ui"
   shell.Run command, 0, False
   '@ | Set-Content -LiteralPath $launcher -Encoding ascii
   $startup = [Environment]::GetFolderPath('Startup')
   $wsh = New-Object -ComObject WScript.Shell
   $shortcut = $wsh.CreateShortcut((Join-Path $startup 'Local AI Hub llama.cpp SYCL.lnk'))
   $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
   $shortcut.Arguments = '"' + $launcher + '"'
   $shortcut.WorkingDirectory = $dir
   $shortcut.WindowStyle = 7
   $shortcut.Save()
   ```

   Keep the host on `127.0.0.1`; do not expose the unauthenticated local inference endpoint to the network.
5. In `~/.local-ai-hub/config.toml`, retain the default `[llama_cpp.models]` aliases and set:

   ```toml
   [llama_cpp]
   mode = "auto"
   fallback_to_ollama = false
   ```

   On a hybrid system where automatic detection cannot see the Intel device, set `mode = "on"` only after confirming this local server is the SYCL build. Keep `fallback_to_ollama = false` unless Ollama is separately and explicitly approved.
6. Verify the router before restarting the Hub:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:12438/health
   (Invoke-RestMethod http://127.0.0.1:12438/models).data | Select-Object id, status
   python tools/hubctl.py restart
   python tools/doctor.py
   ```

   `/models` must list `hub-qwen-05`, `hub-qwen-15`, `hub-qwen-3`, and `hub-qwen-7`. Hub background preprocessing uses 0.5B (`hub-qwen-05`), quick requests use 1.5B (`hub-qwen-15`), complex requests use 3B, and the hardest reasoning uses 7B. Per-model context is controlled by the preset, so do not override it with a global `-c` command-line argument. The router loads the requested model on demand and unloads others because `--models-max 1` is set. The Hub only sends inference to loopback URLs validated by config.

## Linux

Use a Linux build explicitly compiled with `GGML_SYCL=ON`, install the Intel GPU driver and the oneAPI runtime matching that build, and verify `sycl-ls` reports a `[level_zero:gpu]` device before starting the router. Then use the same preset, loopback URL, port, model aliases and `config.toml` settings. Follow the [official Linux SYCL setup](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md#linux); a Windows release archive is not a Linux runtime.

## Rollback and other GPUs

Stop the llama-server process and set `llama_cpp.mode = "off"`, or keep `mode = "auto"` and remove the Intel SYCL server. Requests then use deterministic/indexed operations and return a bounded unavailable-backend result for model work. NVIDIA/AMD dedicated GPU behavior is unchanged; no runtime is installed automatically.
