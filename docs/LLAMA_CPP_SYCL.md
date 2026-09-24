# llama.cpp SYCL on Intel GPUs

Use `llama_cpp.mode = "on"` when Local AI Hub should use llama.cpp instead of Ollama. Setup downloads a pinned llama.cpp build and the default Qwen 1.5B GGUF into `server.state_dir`, verifies both SHA-256 digests, and supervises a loopback router. On Windows x64 with Intel graphics it tries SYCL0, then retries once with CPU if GPU initialization fails. Supported CPU packages cover Windows x64/ARM64, macOS x64/ARM64, and Ubuntu x64/ARM64. `mode = "auto"` only checks a pre-existing loopback server; it never downloads. If `[ollama].enabled = true`, Ollama takes priority and llama.cpp is not provisioned.

Other supported platforms use the pinned CPU runtime unless the operator configures an external endpoint. Official llama.cpp SYCL support targets Intel GPUs; other-vendor GPUs are not supported by this backend. [SYCL backend support](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md)

## Managed setup

Set `ollama.enabled = false` and `llama_cpp.mode = "on"`, then run setup or restart the Hub. The installer selects the pinned platform build; on Windows Intel it uses the official SYCL bundle, which includes the SYCL runtime DLLs. The default GGUF is Qwen2.5-Coder 1.5B Q4_K_M. No model is downloaded while mode is `auto` or `off`. [Official releases](https://github.com/ggml-org/llama.cpp/releases) · [Windows SYCL instructions](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md#option-1-download-the-binary-package-directly)

If SYCL initialization fails, the managed server retries on CPU and status reports `device: none`. To use a manually managed server, leave mode at `auto` and point the configured model routes at its loopback URL.

## Advanced: external Windows router

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

## Advanced: external Linux SYCL router

Managed Linux setup currently provisions the pinned Ubuntu CPU bundle. For Intel Linux acceleration, run an external SYCL router: build or install one explicitly compiled with `GGML_SYCL=ON`, install its matching Intel driver/runtime, and verify `sycl-ls` reports a `[level_zero:gpu]` device. Point `mode="auto"` routes at its loopback URL. Follow the [official Linux SYCL setup](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md#linux); a Windows release archive is not a Linux runtime.

## Rollback and other GPUs

Set `llama_cpp.mode = "off"` to stop managed llama.cpp. `mode = "auto"` continues to use only a configured external endpoint. When mode is off and Ollama is disabled, model requests report the selected backend as disabled/unavailable. NVIDIA/AMD systems use the verified CPU bundle unless an external endpoint is selected.
