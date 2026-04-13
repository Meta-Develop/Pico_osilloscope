# Pico Oscilloscope

Raspberry Pi Pico 2 (RP2350) を使った簡易オシロスコープ。

## Features

- **Hat Mode**: 別の Pico 2 の上に装着して全 GPIO ピンをリアルタイム監視
- **Oscilloscope Mode**: 汎用オシロスコープとして独立動作 (ADC 4ch, 12-bit, 500ksps)

## Hardware

- Raspberry Pi Pico 2 (RP2350, Dual ARM Cortex-M33 @ 150MHz)
- USB ケーブル (データ対応)
- Hat Mode: ピンヘッダーで 2 つの Pico 2 をスタック

## Quick Start

### Firmware

```bash
cd firmware
mkdir build && cd build
cmake ..
cmake --build .
```

BOOTSEL ボタンを押しながら Pico 2 を USB 接続し、生成された `.uf2` ファイルをコピー。

### PC App

```bash
cd pc_app
pip install -r requirements.txt
python src/main.py
```

## Directory Structure

```
firmware/       Pico 2 ファームウェア (C, Pico SDK)
pc_app/         PC 側アプリケーション (Python)
hardware/       基板設計 (KiCad)
docs/           ドキュメント
```

## License

MIT
