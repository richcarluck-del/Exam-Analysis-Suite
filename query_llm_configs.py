
#!/usr/bin/env python
"""查询所有大模型配置（API提供商、模型、步骤配置）"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from shared.database import SessionLocal
from shared.models import APIProvider, LLMModel, LLMStepConfig


def query_all_llm_configs():
    db = SessionLocal()
    try:
        print("=" * 120)
        print("【API 提供商列表】")
        print("=" * 120)
        providers = db.query(APIProvider).order_by(APIProvider.id).all()
        if not providers:
            print("（无记录）")
        else:
            print(f"{'ID':<5} {'名称':<30} {'API地址':<60} {'加密密钥(前20位)':<25}")
            print("-" * 120)
            for p in providers:
                key_preview = (p.encrypted_api_key[:20] + "...") if p.encrypted_api_key and len(p.encrypted_api_key) > 20 else (p.encrypted_api_key or "")
                print(f"{p.id:<5} {p.name:<30} {p.api_url:<60} {key_preview:<25}")

        print()
        print("=" * 120)
        print("【大模型列表 (LLMModel)】")
        print("=" * 120)
        models = db.query(LLMModel).order_by(LLMModel.id).all()
        if not models:
            print("（无记录）")
        else:
            print(f"{'ID':<5} {'模型名称':<40} {'提供商ID':<12} {'提供商名称':<30}")
            print("-" * 120)
            for m in models:
                provider_name = m.provider.name if m.provider else "N/A"
                print(f"{m.id:<5} {m.name:<40} {m.provider_id:<12} {provider_name:<30}")

        print()
        print("=" * 120)
        print("【LLM 步骤配置 (LLMStepConfig)】")
        print("=" * 120)
        steps = db.query(LLMStepConfig).order_by(LLMStepConfig.id).all()
        if not steps:
            print("（无记录）")
        else:
            print(f"{'ID':<5} {'步骤Key':<30} {'步骤标签':<30} {'模块':<20} {'提供商ID':<12} {'模型ID':<10} {'是否激活':<10}")
            print("-" * 120)
            for s in steps:
                active = "是" if s.is_active else "否"
                print(f"{s.id:<5} {s.step_key:<30} {s.step_label:<30} {s.module_name:<20} {str(s.provider_id or ''):<12} {str(s.model_id or ''):<10} {active:<10}")

    finally:
        db.close()


if __name__ == "__main__":
    query_all_llm_configs()
