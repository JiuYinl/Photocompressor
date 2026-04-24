# Image Compressor

A desktop image compression tool built with `Tkinter + Pillow`.

## Features

- Open one local image at a time
- Adjust resolution and quality with sliders
- Preview the estimated output size based on real in-memory encoding
- Enter a target size like `300KB`, `1.5MB`, or `2048B`
- Auto-fit the closest resolution and quality to the target size
- Save the result as `JPEG` or `WEBP`

## Run

```powershell
cd D:\code\AI_agent_code\image_compressor_tool
python app.py
```

## Build A Single EXE

```powershell
cd D:\code\AI_agent_code\image_compressor_tool
python tools\generate_icon.py
python -m PyInstaller --clean ImageCompressor.spec
```

The generated `.exe` will be placed in `dist\ImageCompressor.exe`.

## Requirements

- Python 3.14+
- Pillow
- tkinter
- PyInstaller
