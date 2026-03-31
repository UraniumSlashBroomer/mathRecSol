from __future__ import annotations

from typing import Iterable


class EasyOcrService:
    def __init__(self, languages: Iterable[str] | None = None, gpu: bool = True) -> None:
        self.languages = list(languages or ["en"])
        self.gpu = gpu
        self.reader = None

    def load(self) -> None:
        try:
            import easyocr
        except ImportError as exc:
            raise ImportError(
                "EasyOCR is not installed. Install it with `pip install easyocr`."
            ) from exc

        self.reader = easyocr.Reader(self.languages, gpu=self.gpu)

    def is_loaded(self) -> bool:
        return self.reader is not None

    def read_text(self, image_path: str, detail: int = 0, paragraph: bool = True) -> str:
        if self.reader is None:
            raise RuntimeError("EasyOCR reader is not loaded.")

        result = self.reader.readtext(image_path, detail=detail, paragraph=paragraph)

        if detail == 0:
            return "\n".join(line.strip() for line in result if line.strip())

        lines = []
        for item in result:
            if len(item) < 3:
                continue
            _, text, confidence = item
            text = text.strip()
            if not text:
                continue
            lines.append(f"[{confidence:.3f}] {text}")
        return "\n".join(lines)
