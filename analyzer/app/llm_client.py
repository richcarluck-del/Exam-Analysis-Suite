import base64
import json
import logging
import mimetypes
from typing import Any, Dict, List, Optional

import httpx

from . import security

logger = logging.getLogger(__name__)
from shared.database import SessionLocal
from shared.llm_step_config import resolve_step_llm_config, supports_vision_model_name


class FatalRateLimitError(Exception):
    """模型限流/额度耗尽，应终止当前任务并报告失败。"""
    def __init__(self, model_name: str, status_code: int, body: str):
        self.model_name = model_name
        self.status_code = status_code
        self.body = body
        super().__init__(f"模型 {model_name} 返回 {status_code} (限流/额度耗尽): {body[:300]}")



def supports_vision_model(model_name: Optional[str]) -> bool:
    return supports_vision_model_name(model_name)




def _build_llm_config(provider: Any, model: Any) -> Optional[Dict[str, str]]:
    if not provider or not model:
        return None

    api_key = security.decrypt_api_key(provider.encrypted_api_key)
    api_url = str(provider.api_url)
    return {
        "provider_name": provider.name,
        "model_name": model.name,
        "api_url": api_url,
        "api_key": api_key,
    }



def get_default_llm_config(prefer_vision: bool = False) -> Optional[Dict[str, str]]:
    step_key = "analyzer.question_vlm" if prefer_vision else "analyzer.reasoning"
    db = SessionLocal()
    try:
        return resolve_step_llm_config(
            db,
            step_key,
            allow_generic_fallback=True,
            prefer_vision_fallback=prefer_vision,
        )
    finally:
        db.close()




def _extract_openai_style_content(data: Dict[str, Any]) -> Optional[str]:
    """从 OpenAI 兼容的 chat.completions JSON 中取出 assistant 文本。"""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0] if isinstance(choices[0], dict) else {}
    msg = first.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if content is None:
        return None
    if isinstance(content, str):
        return content
    # 少数网关返回多段 content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts).strip() or None
    return str(content)


def call_llm(messages: List[Dict[str, Any]], llm_config: Dict[str, str], json_mode: bool = False) -> Optional[str]:
    headers = {
        "Authorization": f"Bearer {llm_config['api_key']}",
        "Content-Type": "application/json",
    }
    base_payload: Dict[str, Any] = {"model": llm_config["model_name"], "messages": messages}

    # doubao 模型不支持 response_format json_object，直接跳过
    _model_lower = (llm_config.get("model_name") or "").lower()
    _skip_json_object = any(hint in _model_lower for hint in ("doubao",))

    # 先尝试 json_object（部分厂商不支持会 400）；再回退为普通对话，由上层解析 JSON。
    attempt_modes: List[bool] = []
    if json_mode and not _skip_json_object:
        attempt_modes = [True, False]
    elif json_mode:
        attempt_modes = [False]
    else:
        attempt_modes = [False]

    last_error: Optional[BaseException] = None
    with httpx.Client(timeout=300.0, trust_env=False) as client:
        for use_response_format in attempt_modes:
            payload = dict(base_payload)
            if use_response_format:
                payload["response_format"] = {"type": "json_object"}
            try:
                response = client.post(llm_config["api_url"], headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                text = _extract_openai_style_content(data)
                if text is not None and str(text).strip() != "":
                    return text
                logger.error(
                    "LLM 返回无文本内容: model=%s snippet=%s",
                    llm_config.get("model_name"),
                    json.dumps(data, ensure_ascii=False)[:1200],
                )
                if json_mode and use_response_format:
                    logger.info("重试：无文本内容，尝试去掉 response_format=json_object")
                    continue
            except httpx.HTTPStatusError as exc:
                last_error = exc
                body = (exc.response.text or "")[:2000]
                logger.warning(
                    "LLM HTTP 错误 status=%s model=%s body=%s",
                    exc.response.status_code,
                    llm_config.get("model_name"),
                    body,
                )
                if json_mode and use_response_format and exc.response.status_code in (400, 422):
                    logger.info("将重试：去掉 response_format=json_object（当前网关或模型可能不支持）")
                    continue
                # 429 / 额度耗尽 → 终止，继续跑没有意义
                if exc.response.status_code in (429, 402):
                    raise FatalRateLimitError(
                        model_name=llm_config.get("model_name", "unknown"),
                        status_code=exc.response.status_code,
                        body=body,
                    )
                return None
            except Exception as exc:
                last_error = exc
                logger.exception(
                    "LLM 请求异常 model=%s url=%s",
                    llm_config.get("model_name"),
                    llm_config.get("api_url"),
                )
                return None

    if last_error is not None:
        logger.error("LLM 调用失败: %s", last_error)
    return None



def build_image_data_url(image_path: str) -> str:
    mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"



def call_vlm_on_image(
    image_path: str,
    prompt: str,
    llm_config: Dict[str, str],
    json_mode: bool = False,
) -> Optional[str]:
    if not supports_vision_model(llm_config.get("model_name")):
        return None

    data_url = build_image_data_url(image_path)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]
    return call_llm(messages, llm_config, json_mode=json_mode)
