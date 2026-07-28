# 硬體探測

`scripts/probe_hardware.sh` 產生 `hardware.json`,是整個專案唯一的硬體事實來源。

## 偵測順序

順序本身就是設計的一部分:

```
1. export PATH+=/usr/local/cuda/bin     ← 必須最先做
2. Jetson?  (/etc/nv_tegra_release)     ← 必須在 nvidia-smi 之前
3. CUDA?    (nvcc)
4. 獨顯?    (nvidia-smi)                 ← 只有非 Jetson 才問
5. ffmpeg / OpenBLAS
6. 麥克風
7. 推導能力矩陣
```

### 為什麼 PATH 要先加

Jetson 的 `nvcc` 在 `/usr/local/cuda/bin`,而**非互動式 SSH 不會 source 那份
把它加進 PATH 的 profile**。也就是說:人坐在機器前面跑探測會偵測到 CUDA,從別台
機器 SSH 過來跑同一支腳本卻偵測不到。這是最容易被誤判成「腳本壞了」的坑。

### 為什麼 Jetson 要排在 nvidia-smi 前面

**JetPack 沒有 `nvidia-smi`。** 一支「先找 nvidia-smi,找不到就當作沒有 GPU」的
腳本,會把每一台 Jetson 都判成純 CPU 機器,然後編出一個慢上數十倍的執行檔 ——
而且不會報錯。

Jetson 用統一記憶體,GPU 與系統共用同一塊 RAM,所以 `gpu_vram_gb` 直接取
`total_memory_gb`,不去問任何 GPU 專用的 API。

## CUDA 架構對照

Jetson 的 GPU 架構從 SoC 型號推得,明確傳給 CMake 而不是讓它自己猜:

| SoC | 裝置 | `CMAKE_CUDA_ARCHITECTURES` |
| --- | --- | --- |
| t234 | Orin / Orin NX / Orin Nano | 87 |
| t194 | AGX Xavier / Xavier NX | 72 |
| t186 | TX2 | 62 |
| t210 | Nano / TX1 | 53 |

獨顯不指定,交給 CMake 依實際裝置決定。

### Xavier 專屬:關閉 CUDA VMM

`sm_72` 額外帶 `-DGGML_CUDA_NO_VMM=ON`。Xavier 在多模態(音訊/影像)推理時,
ggml 的 CUDA 虛擬記憶體管理會觸發 OOM 崩潰。關掉它在這個規模下沒有可量測的代價。

## 麥克風

探測會記錄一個建議裝置,但**執行時仍會實測**(見 ARCHITECTURE.md)。探測的偏好序:

1. 名稱含 `MIC_KEYWORD`(預設 `C525`)的 `sysdefault` PCM
2. 任何非 `APE` 的 `sysdefault:CARD=*`
3. `default`

`APE` 是 Jetson 內建的 Tegra 音訊處理器。它會出現在 `arecord -L` 且開得起來,
但通常沒接任何輸入,選到它會得到一條永遠平的音壓線。

換麥克風時:

```bash
arecord -L                                  # 看實際名稱
# 在 .env 設定 MIC_DEVICE= 或 MIC_KEYWORD=
python3 -m breeze_hub.calibrate --write     # 重新校正門檻
```

## 能力矩陣

```
breeze_asr            : 恆為 true
realtime_vad          : 有可用錄音裝置
whisperx_diarization  : CUDA 且 VRAM >= 7 GB
gemma_e2b_multimodal  : CUDA 且 VRAM >= 7 GB
```

`breeze_asr` 寫死為 true 是整個設計的軸心:whisper.cpp 永遠有 CPU 路徑,所以
核心產品在任何機器上都成立,其他引擎才是硬體換來的。

7 GB 這個門檻來自實測 —— 低於此值跑 WhisperX 的講者分離會 OOM。

## 已驗證狀態

| 平台 | 狀態 |
| --- | --- |
| Jetson AGX Xavier, JetPack 5.1.5 / L4T R35.6.2, CUDA 11.4, 14 GB | 參考機,探測與服務實測通過 |
| 其他 Jetson / 桌機獨顯 / 純 CPU | 邏輯依規格撰寫,尚未在實機驗證 |

未驗證的部分照實標示。歡迎回報實測結果。
