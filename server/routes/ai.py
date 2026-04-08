"""
AI / OCR 模块
"""

import os
import json
from pathlib import Path
from flask import Blueprint, request, jsonify

from ..config import load_config, DATA_DIR
from ..session import require_auth

# AI配置
AI_CONFIG_FILE = DATA_DIR / "ai_config.json"

# 创建蓝图
ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')


def load_ai_config() -> dict:
    """加载 AI 配置"""
    try:
        if AI_CONFIG_FILE.exists():
            with AI_CONFIG_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Failed to load AI config: {e}")
    return {}


def save_ai_config(config: dict) -> bool:
    """保存 AI 配置"""
    try:
        AI_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AI_CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Failed to save AI config: {e}")
        return False


@ai_bp.route('/config', methods=['GET'])
def get_ai_config():
    """获取 AI 配置（不返回完整 API Key）"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    config = load_ai_config()
    api_key = config.get("api_key", "")
    if api_key:
        masked_key = api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:] if len(api_key) > 12 else "****"
    else:
        masked_key = ""

    return jsonify({
        "api_key": masked_key,
        "has_key": bool(api_key),
        "model": config.get("model", "deepseek-ai/DeepSeek-OCR"),
        "base_url": config.get("base_url", "https://api.siliconflow.cn/v1")
    })


@ai_bp.route('/models', methods=['GET'])
def get_ai_models():
    """获取可用模型列表"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    models = [
        {"id": "deepseek-ai/DeepSeek-OCR", "name": "DeepSeek OCR"},
        {"id": "Qwen/Qwen2-VL-7B-Instruct", "name": "Qwen2-VL-7B"},
        {"id": "Qwen/Qwen2-VL-72B-Instruct", "name": "Qwen2-VL-72B"},
        {"id": "OpenGVLab/InternVL2-26B", "name": "InternVL2-26B"},
        {"id": "OpenGVLab/InternVL2-8B", "name": "InternVL2-8B"},
        {"id": "Pro/Qwen/Qwen2-VL-7B-Instruct", "name": "Qwen2-VL-7B Pro"},
    ]
    return jsonify(models)


@ai_bp.route('/ocr', methods=['POST'])
def ai_ocr():
    """OCR 接口 - 调用 SiliconFlow DeepSeek-OCR"""
    if not require_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    config = load_ai_config()
    data = request.json
    image_base64 = data.get("image", "")
    prompt_type = data.get("prompt_type", "ocr")

    # 从配置获取默认值
    default_api_key = os.environ.get("OCR_API_KEY", "")
    default_ocr_model = "deepseek-ai/DeepSeek-OCR"

    # 优先级：前端传入 > 已保存配置 > 默认配置
    input_api_key = data.get("api_key", "")
    api_key = input_api_key or config.get("api_key", "") or default_api_key
    model = data.get("model", "") or config.get("model", "") or default_ocr_model

    if not image_base64:
        return jsonify({'error': '请上传图片'}), 400

    # 如果前端传入了新的 API Key，保存它
    if input_api_key and not input_api_key.startswith("sk-****"):
        config["api_key"] = input_api_key
        if model:
            config["model"] = model
        save_ai_config(config)

    # 根据类型选择不同的提示词
    prompts = {
        "ocr": "<image>\n<|grounding|>OCR this image.",
        "markdown": "<image>\n<|grounding|>Convert the document to markdown.",
        "free": "<image>\nFree OCR."
    }
    prompt = prompts.get(prompt_type, prompts["ocr"])

    try:
        import urllib.request
        import urllib.error

        base_url = config.get("base_url", "https://api.siliconflow.cn/v1")
        url = f"{base_url.rstrip('/')}/chat/completions"

        request_data = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ],
            "max_tokens": 4096
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(request_data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))

            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0].get("message", {}).get("content", "")

                # 根据模式处理输出
                if prompt_type == "ocr" and "<|ref|>" in content:
                    # OCR 模式：从 <|ref|>文字<|/ref|><|det|>坐标<|/det|> 格式中提取文字
                    import re
                    texts = re.findall(r'<\|ref\|>(.*?)<\|\/ref\|>', content, flags=re.DOTALL)
                    output = '\n'.join(texts)
                elif "<|ref|>" in content or "<|det|>" in content:
                    # Markdown/Free 模式但包含标签：移除标签保留文本
                    output = re.sub(r'<\|ref\|>.*?<\|\/ref\|>', '', content, flags=re.DOTALL)
                    output = re.sub(r'<\|det\|>.*?<\|\/det\|>', '', output, flags=re.DOTALL)
                else:
                    # 无标签：直接输出
                    output = content

                output = re.sub(r'\n{3,}', '\n\n', output)
                output = output.strip()

                return jsonify({
                    "success": True,
                    "output": output,
                    "raw": content,
                    "model": result.get("model", model),
                    "debug": {
                        "request": {
                            "url": url,
                            "model": model,
                            "prompt_type": prompt_type,
                            "prompt": prompts.get(prompt_type, prompts["ocr"]),
                            "image_size": len(image_base64),
                            "api_key": api_key[:8] + "****" + api_key[-4:] if len(api_key) > 12 else "****"
                        },
                        "response": {
                            "status": response.status,
                            "model": result.get("model", model),
                            "usage": result.get("usage", {}),
                            "content_length": len(content)
                        }
                    }
                })
            else:
                return jsonify({'error': '无响应内容'}), 500

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get("error", {}).get("message", error_body)
        except:
            error_msg = error_body or str(e)
        return jsonify({'error': f'API 错误: {error_msg}'}), 500
    except urllib.error.URLError as e:
        return jsonify({'error': f'网络错误: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'请求失败: {str(e)}'}), 500