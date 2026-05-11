#!/usr/bin/env python3
"""提示词版本验证模块"""

import sys
import os
from typing import Dict, Optional, Tuple

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from src.prompt_manager import prompt_manager


class PromptVersionValidator:
    """提示词版本验证器"""
    
    def __init__(self):
        self.validation_results = {}
    
    def validate_prompt_version(self, step: int, target_type: str, 
                               requested_version: str) -> Tuple[bool, str, Optional[str]]:
        """
        验证提示词版本
        
        Args:
            step: 步骤号
            target_type: 目标类型
            requested_version: 请求的版本号（如 "10", "latest"）
            
        Returns:
            (是否成功, 实际使用的版本, 错误信息)
        """
        # 获取提示词
        prompt_text = prompt_manager.get_prompt(
            step=step, 
            target_type=target_type, 
            version=requested_version
        )
        
        if prompt_text:
            # 成功获取到指定版本
            return True, requested_version, None
        
        # 如果指定版本不存在，尝试获取最新版本
        if requested_version != "latest":
            latest_prompt = prompt_manager.get_prompt(
                step=step,
                target_type=target_type,
                version="latest"
            )
            
            if latest_prompt:
                # 获取最新版本成功
                return True, "latest", f"v{requested_version} 不存在，使用最新版本"
            else:
                # 连最新版本都没有
                return False, None, f"v{requested_version} 不存在，且没有最新版本"
        else:
            # 请求的就是最新版本，但没找到
            return False, None, "未找到最新版本提示词"
    
    def validate_all_prompts(self, requested_version: str) -> Dict:
        """
        验证所有步骤的提示词
        
        Args:
            requested_version: 请求的版本号
            
        Returns:
            验证结果字典
        """
        validation_results = {
            "requested_version": requested_version,
            "steps": {},
            "all_valid": True,
            "errors": []
        }
        
        # 步骤1：透视矫正
        step1_valid, step1_actual_version, step1_error = self.validate_prompt_version(
            step=1, target_type="all_types", requested_version=requested_version
        )
        validation_results["steps"]["step1_perspective_correction"] = {
            "valid": step1_valid,
            "requested": requested_version,
            "actual": step1_actual_version,
            "error": step1_error
        }
        if not step1_valid:
            validation_results["all_valid"] = False
            validation_results["errors"].append(f"步骤1: {step1_error}")
        
        # 步骤2：页面分类
        step2_valid, step2_actual_version, step2_error = self.validate_prompt_version(
            step=2, target_type="full_page", requested_version=requested_version
        )
        validation_results["steps"]["step2_page_classification"] = {
            "valid": step2_valid,
            "requested": requested_version,
            "actual": step2_actual_version,
            "error": step2_error
        }
        if not step2_valid:
            validation_results["all_valid"] = False
            validation_results["errors"].append(f"步骤2: {step2_error}")
        
        # 步骤4：内容提取（三个类型）
        step4_types = ["exam_paper", "answer_sheet", "mixed"]
        for target_type in step4_types:
            step4_valid, step4_actual_version, step4_error = self.validate_prompt_version(
                step=4, target_type=target_type, requested_version=requested_version
            )
            validation_results["steps"][f"step4_content_extraction_{target_type}"] = {
                "valid": step4_valid,
                "requested": requested_version,
                "actual": step4_actual_version,
                "error": step4_error
            }
            if not step4_valid:
                validation_results["all_valid"] = False
                validation_results["errors"].append(f"步骤4-{target_type}: {step4_error}")
        
        return validation_results
    
    def print_validation_report(self, validation_results: Dict):
        """打印验证报告"""
        print("\n" + "="*80)
        print("提示词版本验证报告")
        print("="*80)
        print(f"请求版本: v{validation_results['requested_version']}")
        print(f"整体状态: {'✓ 所有提示词版本有效' if validation_results['all_valid'] else '✗ 存在无效版本'}")
        print()
        
        # 打印每个步骤的验证结果
        for step_name, step_result in validation_results["steps"].items():
            status_icon = "✓" if step_result["valid"] else "✗"
            actual_version = step_result["actual"] if step_result["actual"] else "无"
            
            print(f"{status_icon} {step_name}:")
            print(f"  请求版本: v{step_result['requested']}")
            print(f"  实际版本: v{actual_version}")
            if step_result["error"]:
                print(f"  错误信息: {step_result['error']}")
            print()
        
        # 打印错误汇总
        if validation_results["errors"]:
            print("错误汇总:")
            for error in validation_results["errors"]:
                print(f"  - {error}")
        
        print("="*80)
        
        return validation_results["all_valid"]


# 全局验证器实例
prompt_validator = PromptVersionValidator()


if __name__ == "__main__":
    # 测试验证功能
    print("测试提示词版本验证功能")
    
    # 测试 v10
    print("\n1. 测试 v10 版本:")
    results_v10 = prompt_validator.validate_all_prompts("10")
    is_valid_v10 = prompt_validator.print_validation_report(results_v10)
    print(f"v10 版本是否有效: {is_valid_v10}")
    
    # 测试 v8
    print("\n2. 测试 v8 版本:")
    results_v8 = prompt_validator.validate_all_prompts("8")
    is_valid_v8 = prompt_validator.print_validation_report(results_v8)
    print(f"v8 版本是否有效: {is_valid_v8}")
    
    # 测试 latest
    print("\n3. 测试 latest 版本:")
    results_latest = prompt_validator.validate_all_prompts("latest")
    is_valid_latest = prompt_validator.print_validation_report(results_latest)
    print(f"latest 版本是否有效: {is_valid_latest}")