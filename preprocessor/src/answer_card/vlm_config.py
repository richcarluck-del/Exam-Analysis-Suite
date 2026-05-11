"""
VLM 配置管理模块

功能：
1. 从数据库读取 VLM 模型配置
2. 支持通过模型名称或用途获取配置
3. 提供默认配置回退机制
"""

import os
import sys
from typing import Dict, Optional
from dataclasses import dataclass

# 添加项目根目录到路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, project_root)

from shared.database import SessionLocal
from shared.llm_step_config import resolve_step_llm_config
from shared.models import APIProvider, LLMModel


@dataclass
class VLMConfig:
    """VLM 配置数据类"""
    provider_name: str
    api_url: str
    api_key: str
    model_name: str
    model_id: int
    provider_id: int


def get_vlm_config_by_model_name(model_name: str, pre_decrypted_api_key: Optional[str] = None) -> Optional[VLMConfig]:
    """
    根据模型名称从数据库获取 VLM 配置
    
    Args:
        model_name: 模型名称，如 "gemini-3.1-flash-image-preview"
        pre_decrypted_api_key: 可选，已解密的 API Key（如果提供则直接使用）
        
    Returns:
        VLMConfig 对象，如果找不到则返回 None
    """
    db = SessionLocal()
    try:
        # 查找模型
        model = db.query(LLMModel).filter(
            LLMModel.name == model_name
        ).first()
        
        if not model:
            print(f"[VLM 配置] 数据库中未找到模型：{model_name}")
            return None
        
        # 获取供应商信息
        provider = model.provider
        if not provider:
            print(f"[VLM 配置] 模型 {model_name} 没有关联的供应商")
            return None
        
        # 如果提供了已解密的 API Key，直接使用；否则从数据库解密
        if pre_decrypted_api_key:
            api_key = pre_decrypted_api_key
            print(f"[VLM 配置] 使用传入的已解密 API Key")
        else:
            from analyzer.app.security import decrypt_api_key
            api_key = decrypt_api_key(provider.encrypted_api_key)
            print(f"[VLM 配置] 从数据库解密 API Key")
        
        return VLMConfig(
            provider_name=provider.name,
            api_url=provider.api_url,
            api_key=api_key,
            model_name=model.name,
            model_id=model.id,
            provider_id=provider.id
        )
        
    except Exception as e:
        print(f"[VLM 配置] 获取配置失败：{e}")
        return None
    finally:
        db.close()


def get_vlm_config_by_provider(provider_name: str, model_name: Optional[str] = None) -> Optional[VLMConfig]:
    """
    根据供应商名称获取 VLM 配置
    
    Args:
        provider_name: 供应商名称，如 "ohmygpt"
        model_name: 可选，指定模型名称
        
    Returns:
        VLMConfig 对象，如果找不到则返回 None
    """
    db = SessionLocal()
    try:
        # 查找供应商
        provider = db.query(APIProvider).filter(
            APIProvider.name == provider_name
        ).first()
        
        if not provider:
            print(f"[VLM 配置] 数据库中未找到供应商: {provider_name}")
            return None
        
        # 获取模型
        if model_name:
            model = db.query(LLMModel).filter(
                LLMModel.provider_id == provider.id,
                LLMModel.name == model_name
            ).first()
        else:
            # 使用供应商的第一个模型
            model = provider.models[0] if provider.models else None
        
        if not model:
            print(f"[VLM 配置] 供应商 {provider_name} 没有可用的模型")
            return None
        
        # 解密 API Key
        from analyzer.app.security import decrypt_api_key
        api_key = decrypt_api_key(provider.encrypted_api_key)
        
        return VLMConfig(
            provider_name=provider.name,
            api_url=provider.api_url,
            api_key=api_key,
            model_name=model.name,
            model_id=model.id,
            provider_id=provider.id
        )
        
    except Exception as e:
        print(f"[VLM 配置] 获取配置失败: {e}")
        return None
    finally:
        db.close()


def get_first_available_vlm_config() -> Optional[VLMConfig]:
    """
    获取第一个可用的 VLM 配置
    
    Returns:
        VLMConfig 对象，如果找不到则返回 None
    """
    db = SessionLocal()
    try:
        # 获取第一个有模型的供应商
        providers = db.query(APIProvider).all()
        
        for provider in providers:
            if provider.models:
                model = provider.models[0]
                
                # 解密 API Key
                from analyzer.app.security import decrypt_api_key
                api_key = decrypt_api_key(provider.encrypted_api_key)
                
                return VLMConfig(
                    provider_name=provider.name,
                    api_url=provider.api_url,
                    api_key=api_key,
                    model_name=model.name,
                    model_id=model.id,
                    provider_id=provider.id
                )
        
        print("[VLM 配置] 数据库中没有可用的 VLM 配置")
        return None
        
    except Exception as e:
        print(f"[VLM 配置] 获取配置失败: {e}")
        return None
    finally:
        db.close()


def get_vlm_config(
    model_name: Optional[str] = None,
    provider_name: Optional[str] = None,
    use_default: bool = True
) -> Optional[VLMConfig]:
    """
    获取 VLM 配置的通用接口
    
    优先级：
    1. 如果指定了 model_name，按模型名称查找
    2. 如果指定了 provider_name，按供应商查找
    3. 如果 use_default=True，返回第一个可用配置
    4. 返回 None
    
    Args:
        model_name: 可选，模型名称
        provider_name: 可选，供应商名称
        use_default: 是否使用默认配置
        
    Returns:
        VLMConfig 对象，如果找不到则返回 None
    """
    config = None
    
    # 1. 按模型名称查找
    if model_name:
        config = get_vlm_config_by_model_name(model_name)
        if config:
            print(f"[VLM 配置] 使用模型 '{model_name}' 的配置")
            return config
    
    # 2. 按供应商查找
    if provider_name:
        config = get_vlm_config_by_provider(provider_name, model_name)
        if config:
            print(f"[VLM 配置] 使用供应商 '{provider_name}' 的配置")
            return config
    
    # 3. 使用步骤配置作为默认配置
    if use_default:
        db = SessionLocal()
        try:
            step_config = resolve_step_llm_config(
                db,
                'preprocessor.answer_card_recognition',
                fallback_provider_name='volcengine',
                fallback_model_name='doubao-seed-2-0-pro-260215',
            )
        finally:
            db.close()

        if step_config:
            print(
                f"[VLM 配置] 使用步骤配置: "
                f"{step_config['provider_name']}/{step_config['model_name']}"
            )
            return VLMConfig(
                provider_name=step_config['provider_name'],
                api_url=step_config['api_url'],
                api_key=step_config['api_key'],
                model_name=step_config['model_name'],
                model_id=step_config['model_id'],
                provider_id=step_config['provider_id'],
            )

        config = get_first_available_vlm_config()
        if config:
            print(f"[VLM 配置] 使用默认配置: {config.provider_name}/{config.model_name}")
            return config
    
    return None


def list_available_vlm_models() -> list:
    """
    列出数据库中所有可用的 VLM 模型
    
    Returns:
        模型列表，每项包含 provider_name, model_name, model_id
    """
    db = SessionLocal()
    try:
        models = []
        providers = db.query(APIProvider).all()
        
        for provider in providers:
            for model in provider.models:
                models.append({
                    'provider_name': provider.name,
                    'model_name': model.name,
                    'model_id': model.id,
                    'provider_id': provider.id
                })
        
        return models
        
    except Exception as e:
        print(f"[VLM 配置] 获取模型列表失败: {e}")
        return []
    finally:
        db.close()


if __name__ == '__main__':
    print("=" * 60)
    print("VLM 配置管理工具")
    print("=" * 60)
    
    # 列出所有可用模型
    print("\n可用模型列表:")
    models = list_available_vlm_models()
    if models:
        for m in models:
            print(f"  - {m['provider_name']}/{m['model_name']} (ID: {m['model_id']})")
    else:
        print("  暂无可用模型")
    
    # 测试获取默认配置
    print("\n获取默认配置:")
    config = get_vlm_config()
    if config:
        print(f"  供应商: {config.provider_name}")
        print(f"  API URL: {config.api_url}")
        print(f"  API Key: {config.api_key[:15]}...{config.api_key[-5:]}")
        print(f"  模型: {config.model_name}")
    else:
        print("  未找到可用配置")
