from PIL import Image
from transformers import AutoTokenizer, AutoProcessor, AutoModelForImageTextToText
import time

model_path = "nanonets/Nanonets-OCR2-3B"

model = AutoModelForImageTextToText.from_pretrained(
            model_path, 
            dtype="auto", 
            device_map="cuda", # try auto 
            attn_implementation="eager",
            load_in_8bit=True,

            )
model = model.eval()
tokenizer = AutoTokenizer.from_pretrained(model_path)
processor = AutoProcessor.from_pretrained(model_path)


def ocr_page_with_nanonets_s(image_path, model, processor, max_new_tokens=4096):
        prompt = """Extract the text from the above document as if you were reading it naturally. Return the tables in html format. Return the equations in LaTeX representation. If there is an image in the document and image caption is not present, add a small description of the image inside the <img></img> tag; otherwise, add the image caption inside <img></img>. Watermarks should be wrapped in brackets. Ex: <watermark>OFFICIAL COPY</watermark>. Page numbers should be wrapped in brackets. Ex: <page_number>14</page_number> or <page_number>9/22</page_number>. Prefer using ☐ and ☑ for check boxes."""
        image = Image.open(image_path)
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": [
                {"type": "image", "image": f"file://{image_path}"},
                {"type": "text", "text": prompt},
            ]},
        ]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=[image], padding=True, return_tensors="pt")
        inputs = inputs.to(model.device)

        output_ids = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        generated_ids = [output_ids[len(input_ids):] for input_ids, output_ids in zip(inputs.input_ids, output_ids)]

        output_text = processor.batch_decode(generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        return output_text[0]

image_path = "image2.jpg"
print('waiting results')
start = time.time()
result = ocr_page_with_nanonets_s(image_path, model, processor, max_new_tokens=15000)
end = time.time()
time_result = round((end - start) / 60, 2)
print(f'time spent on text recognition: {time_result} min')

with open('result_test.txt', mode='w', encoding='utf-8') as f:
    f.write(f'{time_result} min\n')
    f.writelines(result)

print(result)

