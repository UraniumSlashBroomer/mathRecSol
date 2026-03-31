from __future__ import annotations

from PIL import Image


class NanonetsOcr2Service:
    def __init__(self, model_path: str = "nanonets/Nanonets-OCR2-3B") -> None:
        self.model_path = model_path
        self.model = None
        self.processor = None

    def load(self) -> None:
        try:
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as exc:
            raise ImportError(
                "Transformers is not installed. Install it with `pip install transformers`."
            ) from exc

        self.model = AutoModelForImageTextToText.from_pretrained(
            self.model_path,
            dtype="auto",
            device_map="cuda",
            attn_implementation="eager",
            load_in_8bit=True,
        )
        self.model = self.model.eval()
        self.processor = AutoProcessor.from_pretrained(self.model_path)

    def is_loaded(self) -> bool:
        return self.model is not None and self.processor is not None

    def read_text(self, image_path: str, max_new_tokens: int = 15000) -> str:
        if self.model is None or self.processor is None:
            raise RuntimeError("Nanonets OCR2 model is not loaded.")

        prompt = (
            "Extract the text from the above document as if you were reading it naturally. "
            "Return the tables in html format. Return the equations in LaTeX representation. "
            "If there is an image in the document and image caption is not present, add a small "
            "description of the image inside the <img></img> tag; otherwise, add the image caption "
            "inside <img></img>. Watermarks should be wrapped in brackets. Ex: "
            "<watermark>OFFICIAL COPY</watermark>. Page numbers should be wrapped in brackets. Ex: "
            "<page_number>14</page_number> or <page_number>9/22</page_number>. Prefer using ☐ and "
            "☑ for check boxes."
        )
        with Image.open(image_path) as image:
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": f"file://{image_path}"},
                        {"type": "text", "text": prompt},
                    ],
                },
            ]
            text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.processor(text=[text], images=[image], padding=True, return_tensors="pt")
            inputs = inputs.to(self.model.device)

            output_ids = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
            generated_ids = [output[len(input_ids):] for input_ids, output in zip(inputs.input_ids, output_ids)]
            output_text = self.processor.batch_decode(
                generated_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True,
            )
        return output_text[0]
