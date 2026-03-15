import requests
import base64
import json

api_key = "sk-0ac4ae0c039846d889beae0b03c2a96b"
api_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
model = "qwen3-max"

image_path = r"D:\10739\Exam-Analysis-Suite\preprocessor\my_test_images\1.jpg"

with open(image_path, "rb") as f:
    base64_image = base64.b64encode(f.read()).decode("utf-8")

prompt = "请描述这张图片的内容。"

payload = {
    "model": model,
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        }
    ],
    "temperature": 0.1,
    "max_tokens": 1000
}

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

response = requests.post(api_url, headers=headers, json=payload, timeout=300)
print(f"Status: {response.status_code}")
print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
