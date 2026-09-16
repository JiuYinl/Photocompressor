from __future__ import annotations

import io
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk


OutputFormat = Literal["JPEG", "WEBP"]

SIZE_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMG]?B)?\s*$", re.IGNORECASE)
UNIT_MULTIPLIERS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024 * 1024,
    "GB": 1024 * 1024 * 1024,
}


def resource_path(relative_path: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path


@dataclass(slots=True)
class CompressionSettings:
    scale_percent: int
    quality: int
    output_format: OutputFormat


@dataclass(slots=True)
class ProcessedImageResult:
    width: int
    height: int
    estimated_bytes: int
    preview_image: ImageTk.PhotoImage
    encoded_bytes: bytes


@dataclass(slots=True)
class CompressionCandidate:
    settings: CompressionSettings
    width: int
    height: int
    encoded_bytes: bytes

    @property
    def estimated_bytes(self) -> int:
        return len(self.encoded_bytes)


class ImageProcessor:
    PREVIEW_MAX_SIZE = (520, 420)

    @staticmethod
    def load_image(path: Path) -> Image.Image:
        with Image.open(path) as image:
            corrected = ImageOps.exif_transpose(image)
            return corrected.copy()

    def build_processed_image(
        self,
        source_image: Image.Image,
        settings: CompressionSettings,
    ) -> ProcessedImageResult:
        candidate = self.render_candidate(source_image, settings)
        preview_image = self._create_preview_image_from_bytes(candidate.encoded_bytes)
        return ProcessedImageResult(
            width=candidate.width,
            height=candidate.height,
            estimated_bytes=candidate.estimated_bytes,
            preview_image=preview_image,
            encoded_bytes=candidate.encoded_bytes,
        )

    def render_candidate(
        self,
        source_image: Image.Image,
        settings: CompressionSettings,
        resized_cache: dict[int, Image.Image] | None = None,
    ) -> CompressionCandidate:
        resized_image = self._resize_image(source_image, settings.scale_percent, resized_cache)
        encoded_bytes = self._encode_image(resized_image, settings)
        return CompressionCandidate(
            settings=settings,
            width=resized_image.width,
            height=resized_image.height,
            encoded_bytes=encoded_bytes,
        )

    def find_closest_settings(
        self,
        source_image: Image.Image,
        target_bytes: int,
        output_format: OutputFormat,
    ) -> CompressionCandidate:
        resized_cache: dict[int, Image.Image] = {}
        best: CompressionCandidate | None = None

        for scale_percent in range(10, 101):
            low = 10
            high = 95
            checked_qualities: set[int] = set()

            while low <= high:
                quality = (low + high) // 2
                checked_qualities.add(quality)
                candidate = self.render_candidate(
                    source_image,
                    CompressionSettings(scale_percent=scale_percent, quality=quality, output_format=output_format),
                    resized_cache,
                )
                best = pick_better_candidate(best, candidate, target_bytes)

                if candidate.estimated_bytes == target_bytes:
                    return candidate
                if candidate.estimated_bytes < target_bytes:
                    low = quality + 1
                else:
                    high = quality - 1

            for quality in (low, high):
                if 10 <= quality <= 95 and quality not in checked_qualities:
                    candidate = self.render_candidate(
                        source_image,
                        CompressionSettings(scale_percent=scale_percent, quality=quality, output_format=output_format),
                        resized_cache,
                    )
                    best = pick_better_candidate(best, candidate, target_bytes)

        assert best is not None
        return best

    def _resize_image(
        self,
        image: Image.Image,
        scale_percent: int,
        resized_cache: dict[int, Image.Image] | None = None,
    ) -> Image.Image:
        safe_scale = max(10, min(100, scale_percent))
        if resized_cache is not None and safe_scale in resized_cache:
            return resized_cache[safe_scale]

        ratio = safe_scale / 100.0
        new_width = max(1, round(image.width * ratio))
        new_height = max(1, round(image.height * ratio))
        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        if resized_cache is not None:
            resized_cache[safe_scale] = resized
        return resized

    def _encode_image(self, image: Image.Image, settings: CompressionSettings) -> bytes:
        prepared_image = self._prepare_for_format(image, settings.output_format)
        buffer = io.BytesIO()

        save_options: dict[str, object] = {"quality": settings.quality}
        if settings.output_format == "JPEG":
            save_options["optimize"] = True
        else:
            save_options["method"] = 6

        prepared_image.save(buffer, format=settings.output_format, **save_options)
        return buffer.getvalue()

    def _prepare_for_format(self, image: Image.Image, output_format: OutputFormat) -> Image.Image:
        if output_format == "JPEG":
            if self._has_alpha(image):
                rgba_image = image.convert("RGBA")
                white_background = Image.new("RGBA", rgba_image.size, (255, 255, 255, 255))
                composited = Image.alpha_composite(white_background, rgba_image)
                return composited.convert("RGB")
            if image.mode != "RGB":
                return image.convert("RGB")
        return image.copy()

    @staticmethod
    def _has_alpha(image: Image.Image) -> bool:
        return image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        )

    def _create_preview_image_from_bytes(self, encoded_bytes: bytes) -> ImageTk.PhotoImage:
        with Image.open(io.BytesIO(encoded_bytes)) as image:
            preview = image.copy()
        preview.thumbnail(self.PREVIEW_MAX_SIZE, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(preview)


class ImageCompressorApp:
    UPDATE_DELAY_MS = 180

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.processor = ImageProcessor()

        self.source_path: Path | None = None
        self.source_image: Image.Image | None = None
        self.source_size_bytes = 0
        self.current_result: ProcessedImageResult | None = None
        self.pending_update_id: str | None = None

        self.scale_var = tk.IntVar(value=100)
        self.quality_var = tk.IntVar(value=85)
        self.format_var = tk.StringVar(value="JPEG")
        self.target_size_var = tk.StringVar()
        self.status_var = tk.StringVar(value="请选择一张图片开始压缩。")
        self.original_info_var = tk.StringVar(value="原图信息：未加载")
        self.adjusted_info_var = tk.StringVar(value="调整后：-")
        self.estimated_size_var = tk.StringVar(value="预计大小：-")
        self.compression_ratio_var = tk.StringVar(value="压缩比例：-")
        self.target_info_var = tk.StringVar(value="目标大小：可选，例如 300KB / 1.5MB")
        self.target_delta_var = tk.StringVar(value="目标差值：-")

        self.scale_value_var = tk.StringVar(value="100%")
        self.quality_value_var = tk.StringVar(value="85")

        self.preview_label: ttk.Label | None = None
        self.save_button: ttk.Button | None = None
        self.fit_button: ttk.Button | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.root.title("图片压缩工具")
        self.root.geometry("1040x760")
        self.root.minsize(900, 660)

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=(16, 16, 16, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(3, weight=1)

        open_button = ttk.Button(toolbar, text="选择图片", command=self.open_image)
        open_button.grid(row=0, column=0, padx=(0, 8))

        self.save_button = ttk.Button(toolbar, text="另存为", command=self.save_image, state="disabled")
        self.save_button.grid(row=0, column=1, padx=(0, 16))

        status_label = ttk.Label(toolbar, textvariable=self.status_var, anchor="w")
        status_label.grid(row=0, column=3, sticky="ew")

        main_frame = ttk.Frame(self.root, padding=(16, 8, 16, 16))
        main_frame.grid(row=1, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=0)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        controls_frame = ttk.LabelFrame(main_frame, text="压缩设置", padding=16)
        controls_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 16))
        controls_frame.columnconfigure(0, weight=1)

        ttk.Label(controls_frame, text="分辨率").grid(row=0, column=0, sticky="w")
        ttk.Label(controls_frame, textvariable=self.scale_value_var).grid(row=1, column=0, sticky="e")
        scale_slider = tk.Scale(
            controls_frame,
            from_=10,
            to=100,
            orient=tk.HORIZONTAL,
            resolution=1,
            variable=self.scale_var,
            command=self.on_slider_changed,
            length=280,
        )
        scale_slider.grid(row=2, column=0, sticky="ew", pady=(4, 12))

        ttk.Label(controls_frame, text="图片质量").grid(row=3, column=0, sticky="w")
        ttk.Label(controls_frame, textvariable=self.quality_value_var).grid(row=4, column=0, sticky="e")
        quality_slider = tk.Scale(
            controls_frame,
            from_=10,
            to=95,
            orient=tk.HORIZONTAL,
            resolution=1,
            variable=self.quality_var,
            command=self.on_slider_changed,
            length=280,
        )
        quality_slider.grid(row=5, column=0, sticky="ew", pady=(4, 12))

        ttk.Label(controls_frame, text="输出格式").grid(row=6, column=0, sticky="w")
        format_box = ttk.Combobox(
            controls_frame,
            textvariable=self.format_var,
            values=("JPEG", "WEBP"),
            state="readonly",
        )
        format_box.grid(row=7, column=0, sticky="ew", pady=(4, 12))
        format_box.bind("<<ComboboxSelected>>", self.on_format_changed)

        target_frame = ttk.LabelFrame(controls_frame, text="目标大小", padding=12)
        target_frame.grid(row=8, column=0, sticky="ew", pady=(0, 12))
        target_frame.columnconfigure(0, weight=1)

        target_entry = ttk.Entry(target_frame, textvariable=self.target_size_var)
        target_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        target_entry.bind("<KeyRelease>", self.on_target_changed)

        self.fit_button = ttk.Button(
            target_frame,
            text="自动逼近",
            command=self.fit_to_target,
            state="disabled",
        )
        self.fit_button.grid(row=0, column=1)

        ttk.Label(
            target_frame,
            text="示例：300KB、1.5MB、2048B，或直接输入 300（默认按 KB 处理）",
            justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 4))

        ttk.Label(target_frame, textvariable=self.target_info_var, justify=tk.LEFT).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        ttk.Label(target_frame, textvariable=self.target_delta_var, justify=tk.LEFT).grid(
            row=3, column=0, columnspan=2, sticky="w"
        )

        info_frame = ttk.LabelFrame(controls_frame, text="图片信息", padding=12)
        info_frame.grid(row=9, column=0, sticky="ew")
        info_frame.columnconfigure(0, weight=1)

        ttk.Label(info_frame, textvariable=self.original_info_var, justify=tk.LEFT).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        ttk.Label(info_frame, textvariable=self.adjusted_info_var, justify=tk.LEFT).grid(
            row=1, column=0, sticky="w", pady=(0, 6)
        )
        ttk.Label(info_frame, textvariable=self.estimated_size_var, justify=tk.LEFT).grid(
            row=2, column=0, sticky="w", pady=(0, 6)
        )
        ttk.Label(info_frame, textvariable=self.compression_ratio_var, justify=tk.LEFT).grid(
            row=3, column=0, sticky="w"
        )

        preview_frame = ttk.LabelFrame(main_frame, text="预览", padding=16)
        preview_frame.grid(row=0, column=1, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.preview_label = ttk.Label(
            preview_frame,
            text="这里会显示压缩后的预览图。",
            anchor="center",
            justify=tk.CENTER,
        )
        self.preview_label.grid(row=0, column=0, sticky="nsew")

    def open_image(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[
                ("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp"),
                ("所有文件", "*.*"),
            ],
        )
        if not file_path:
            return

        path = Path(file_path)
        try:
            loaded_image = self.processor.load_image(path)
        except Exception as exc:
            messagebox.showerror("打开失败", f"无法读取图片：\n{exc}")
            return

        self.source_path = path
        self.source_image = loaded_image
        self.source_size_bytes = path.stat().st_size
        self.current_result = None

        self.original_info_var.set(
            f"原图信息：{loaded_image.width} x {loaded_image.height} | {format_bytes(self.source_size_bytes)}"
        )
        self.status_var.set(f"已加载：{path.name}")
        if self.save_button is not None:
            self.save_button.configure(state="normal")
        if self.fit_button is not None:
            self.fit_button.configure(state="normal")

        self.schedule_refresh(immediate=True)

    def save_image(self) -> None:
        if self.source_path is None or self.current_result is None:
            messagebox.showwarning("无法保存", "请先选择图片，并等待预览生成完成。")
            return

        output_format = self.current_settings().output_format
        suffix = ".jpg" if output_format == "JPEG" else ".webp"
        default_name = f"{self.source_path.stem}_压缩后{suffix}"

        target_path = filedialog.asksaveasfilename(
            title="另存为",
            defaultextension=suffix,
            initialfile=default_name,
            filetypes=[
                ("JPEG 图片", "*.jpg *.jpeg"),
                ("WebP 图片", "*.webp"),
                ("所有文件", "*.*"),
            ],
        )
        if not target_path:
            return

        try:
            Path(target_path).write_bytes(self.current_result.encoded_bytes)
        except Exception as exc:
            messagebox.showerror("保存失败", f"无法保存文件：\n{exc}")
            return

        actual_size = len(self.current_result.encoded_bytes)
        self.status_var.set(f"已保存：{Path(target_path).name}")
        messagebox.showinfo(
            "保存成功",
            f"文件已保存到：\n{target_path}\n\n最终大小：{format_bytes(actual_size)}",
        )

    def fit_to_target(self) -> None:
        if self.source_image is None:
            messagebox.showwarning("未选择图片", "请先选择图片，再使用目标大小自动逼近。")
            return

        target_bytes = parse_target_size(self.target_size_var.get())
        if target_bytes is None:
            messagebox.showwarning(
                "目标大小无效",
                "请输入例如 300KB、1.5MB、2048B，或直接输入 300。",
            )
            return

        self.status_var.set("正在寻找最接近目标大小的组合……")
        self.root.update_idletasks()

        candidate = self.processor.find_closest_settings(
            self.source_image,
            target_bytes=target_bytes,
            output_format=self.current_output_format(),
        )

        self.scale_var.set(candidate.settings.scale_percent)
        self.quality_var.set(candidate.settings.quality)
        self.scale_value_var.set(f"{candidate.settings.scale_percent}%")
        self.quality_value_var.set(str(candidate.settings.quality))

        self.apply_result(
            ProcessedImageResult(
                width=candidate.width,
                height=candidate.height,
                estimated_bytes=candidate.estimated_bytes,
                preview_image=self.processor._create_preview_image_from_bytes(candidate.encoded_bytes),
                encoded_bytes=candidate.encoded_bytes,
            ),
            status_message="已应用最接近目标大小的参数组合。",
        )

    def on_slider_changed(self, _value: str) -> None:
        self.scale_value_var.set(f"{self.scale_var.get()}%")
        self.quality_value_var.set(str(self.quality_var.get()))
        self.schedule_refresh()

    def on_format_changed(self, _event: tk.Event) -> None:
        self.schedule_refresh()

    def on_target_changed(self, _event: tk.Event) -> None:
        self.update_target_info()

    def schedule_refresh(self, immediate: bool = False) -> None:
        if self.pending_update_id is not None:
            self.root.after_cancel(self.pending_update_id)
            self.pending_update_id = None

        if self.source_image is None:
            self.update_target_info()
            return

        delay = 0 if immediate else self.UPDATE_DELAY_MS
        self.pending_update_id = self.root.after(delay, self.refresh_preview)

    def refresh_preview(self) -> None:
        self.pending_update_id = None
        if self.source_image is None:
            return

        try:
            result = self.processor.build_processed_image(self.source_image, self.current_settings())
        except Exception as exc:
            self.status_var.set("预览更新失败。")
            messagebox.showerror("处理失败", f"无法生成预览：\n{exc}")
            return

        self.apply_result(result, status_message="预览已更新，现在可以另存为。")

    def apply_result(self, result: ProcessedImageResult, status_message: str) -> None:
        if self.preview_label is None:
            return

        self.current_result = result
        self.preview_label.configure(image=result.preview_image, text="")
        self.preview_label.image = result.preview_image

        self.adjusted_info_var.set(f"调整后：{result.width} x {result.height}")
        self.estimated_size_var.set(f"预计大小：{format_bytes(result.estimated_bytes)}")

        ratio = (result.estimated_bytes / self.source_size_bytes) if self.source_size_bytes else 0.0
        reduction = max(0.0, 1.0 - ratio)
        self.compression_ratio_var.set(
            f"压缩比例：约为原图的 {ratio * 100:.1f}% | 体积减少 {reduction * 100:.1f}%"
        )

        self.update_target_info()
        self.status_var.set(status_message)

    def update_target_info(self) -> None:
        target_bytes = parse_target_size(self.target_size_var.get())
        if target_bytes is None:
            if self.target_size_var.get().strip():
                self.target_info_var.set("目标大小：输入格式无效")
            else:
                self.target_info_var.set("目标大小：可选，例如 300KB / 1.5MB")
            self.target_delta_var.set("目标差值：-")
            return

        self.target_info_var.set(f"目标大小：{format_bytes(target_bytes)}")
        if self.current_result is None:
            self.target_delta_var.set("目标差值：请选择图片后再比较")
            return

        delta = self.current_result.estimated_bytes - target_bytes
        sign = "+" if delta >= 0 else "-"
        self.target_delta_var.set(f"目标差值：{sign}{format_bytes(abs(delta))}")

    def current_output_format(self) -> OutputFormat:
        output_format = self.format_var.get()
        if output_format not in ("JPEG", "WEBP"):
            return "JPEG"
        return output_format

    def current_settings(self) -> CompressionSettings:
        return CompressionSettings(
            scale_percent=self.scale_var.get(),
            quality=self.quality_var.get(),
            output_format=self.current_output_format(),
        )


def parse_target_size(value: str) -> int | None:
    if not value.strip():
        return None

    match = SIZE_PATTERN.fullmatch(value)
    if match is None:
        return None

    number = float(match.group(1))
    unit = (match.group(2) or "KB").upper()
    multiplier = UNIT_MULTIPLIERS.get(unit)
    if multiplier is None:
        return None

    size_bytes = round(number * multiplier)
    if size_bytes <= 0:
        return None
    return size_bytes


def format_bytes(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def pick_better_candidate(
    current_best: CompressionCandidate | None,
    candidate: CompressionCandidate,
    target_bytes: int,
) -> CompressionCandidate:
    if current_best is None:
        return candidate

    current_diff = abs(current_best.estimated_bytes - target_bytes)
    candidate_diff = abs(candidate.estimated_bytes - target_bytes)
    if candidate_diff != current_diff:
        return candidate if candidate_diff < current_diff else current_best

    current_over = current_best.estimated_bytes > target_bytes
    candidate_over = candidate.estimated_bytes > target_bytes
    if current_over != candidate_over:
        return candidate if not candidate_over else current_best

    current_pixels = current_best.width * current_best.height
    candidate_pixels = candidate.width * candidate.height
    if candidate_pixels != current_pixels:
        return candidate if candidate_pixels > current_pixels else current_best

    if candidate.settings.quality != current_best.settings.quality:
        return candidate if candidate.settings.quality > current_best.settings.quality else current_best

    return current_best


def main() -> None:
    root = tk.Tk()
    icon_path = resource_path("assets/app_icon.ico")
    if icon_path.exists():
        try:
            root.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass
    app = ImageCompressorApp(root)
    app.on_slider_changed("0")
    root.mainloop()


if __name__ == "__main__":
    main()
