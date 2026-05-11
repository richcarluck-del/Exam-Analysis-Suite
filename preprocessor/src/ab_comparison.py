#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A/B 方案对比分析器（简化版本）

对比方案 A（split）和方案 B（whole）的结果
"""

import json
import os
from datetime import datetime


class ABComparator:
    """A/B 方案对比分析器"""
    
    def __init__(self, output_dir):
        """
        Args:
            output_dir: 输出目录路径
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def compare_results(self, split_result_path, whole_result_path, processing_time=None):
        """
        对比两种方案的结果
        
        Args:
            split_result_path: 方案 A 的结果文件路径
            whole_result_path: 方案 B 的结果文件路径
            processing_time: 处理时间（可选）
            
        Returns:
            dict: 对比报告
        """
        # 加载两种方案的结果
        split_results = self._load_results(split_result_path)
        whole_results = self._load_results(whole_result_path)
        
        # 生成对比报告
        comparison_report = {
            'generated_at': datetime.now().isoformat(),
            'split_mode': {
                'result_file': split_result_path,
                'total_questions': len(split_results),
                'questions': split_results
            },
            'whole_mode': {
                'result_file': whole_result_path,
                'total_questions': len(whole_results),
                'questions': whole_results
            },
            'comparison': {
                'question_count_diff': abs(len(split_results) - len(whole_results)),
                'split_has_more': len(split_results) > len(whole_results),
                'processing_time': processing_time
            }
        }
        
        # 保存对比报告
        self._save_comparison_report(comparison_report)
        
        return comparison_report
    
    def _load_results(self, result_path):
        """加载结果文件"""
        if not os.path.exists(result_path):
            return []
        
        with open(result_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 提取题目列表
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and 'questions' in data:
            return data['questions']
        else:
            return []
    
    def _save_comparison_report(self, report):
        """保存对比报告为 JSON"""
        # 保存 JSON
        json_path = os.path.join(self.output_dir, 'ab_comparison_report.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"✓ 对比报告已保存：{json_path}")
        
        # 生成简单的文本摘要
        summary_path = os.path.join(self.output_dir, 'ab_comparison_summary.txt')
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("A/B 方案对比测试报告\n")
            f.write("="*80 + "\n\n")
            f.write(f"生成时间：{report['generated_at']}\n\n")
            
            f.write("方案 A（分割）:\n")
            f.write(f"  - 识别题目数量：{report['split_mode']['total_questions']}\n\n")
            
            f.write("方案 B（整体）:\n")
            f.write(f"  - 识别题目数量：{report['whole_mode']['total_questions']}\n\n")
            
            f.write("对比结果:\n")
            f.write(f"  - 题目数量差异：{report['comparison']['question_count_diff']}\n")
            if report['comparison']['split_has_more']:
                f.write(f"  - 方案 A 识别出更多题目\n")
            elif report['comparison']['question_count_diff'] == 0:
                f.write(f"  - 两种方案识别的题目数量一致 ✓\n")
            else:
                f.write(f"  - 方案 B 识别出更多题目\n")
            
            if report['comparison'].get('processing_time'):
                f.write(f"  - 处理时间：{report['comparison']['processing_time']}\n")
        
        print(f"✓ 对比摘要已保存：{summary_path}")


if __name__ == "__main__":
    # 测试示例
    comparator = ABComparator("test_output")
    print("ABComparator 初始化成功")
