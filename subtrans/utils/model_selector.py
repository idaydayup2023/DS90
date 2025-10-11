#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import requests
from typing import List, Optional, Dict, Tuple
from utils.logger import get_logger


class ModelSelector:
    """多服务模型选择器，支持 Ollama 和 LM Studio，优先选择 gemma3 模型"""
    
    def __init__(self, config=None):
        self.logger = get_logger(__name__)
        
        # 兼容旧的初始化方式
        if config is None:
            from core.config import SubTransConfig
            self.config = SubTransConfig
        else:
            self.config = config
        
        # 模型家族优先级：gemma3 > llama3 > qwen2 > mistral > 其他
        self.family_priority = ["gemma3", "llama3", "qwen2", "mistral"]
        
    def get_available_models(self, service: str = "ollama") -> List[Dict]:
        """获取指定服务中所有可用的模型"""
        try:
            if service == "ollama":
                url = f"{self.config.OLLAMA_URL.rstrip('/')}/api/tags"
            elif service == "lm_studio":
                url = f"{self.config.LM_STUDIO_URL.rstrip('/')}/v1/models"
            else:
                self.logger.error(f"不支持的服务类型: {service}")
                return []
            
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if service == "ollama":
                    return data.get('models', [])
                elif service == "lm_studio":
                    # 转换 LM Studio 格式为统一格式
                    models = data.get('data', [])
                    return [{"name": model.get("id", ""), "model": model} for model in models]
            else:
                self.logger.error(f"获取{service}模型列表失败，状态码: {response.status_code}")
                return []
        except requests.exceptions.RequestException as e:
            self.logger.error(f"连接{service}服务失败: {e}")
            return []
    
    def parse_model_size(self, model_name: str) -> Optional[float]:
        """解析模型名称中的参数量
        
        支持的格式:
        - gemma3:4b -> 4.0
        - gemma3:12b -> 12.0
        - llama3:8b -> 8.0
        - qwen2:7b -> 7.0
        - mistral:7b -> 7.0
        - google/gemma-3-4b -> 4.0
        - google/gemma-2-9b -> 9.0
        """
        model_name_lower = model_name.lower()
        
        # 匹配模型名称中的参数量，支持多种格式
        patterns = [
            r':(\d+(?:\.\d+)?)b?$',      # 标准格式: gemma3:4b
            r'-(\d+(?:\.\d+)?)b$',       # 连字符格式: google/gemma-3-4b
            r'/.*-(\d+(?:\.\d+)?)b$',    # 路径格式: google/gemma-3-4b
        ]
        
        for pattern in patterns:
            match = re.search(pattern, model_name_lower)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        
        # 如果没有找到参数量信息，返回None
        return None
    
    def filter_models_by_family(self, models: List[Dict], family: Optional[str] = None) -> List[Dict]:
        """按模型家族过滤模型
        
        Args:
            models: 模型列表
            family: 模型家族名称，如'gemma3', 'llama3'等。如果为None，则不过滤
        """
        if not family:
            return models
        
        filtered = []
        for model in models:
            model_name = model.get('name', '')
            model_name_lower = model_name.lower()
            family_lower = family.lower()
            
            # 支持多种匹配模式
            if (model_name_lower.startswith(family_lower) or  # 标准格式: gemma3:4b
                f"/{family_lower}" in model_name_lower or     # 路径格式: google/gemma3
                f"-{family_lower}" in model_name_lower or     # 连字符格式: google-gemma3
                family_lower.replace('3', '') in model_name_lower):  # 去掉版本号: gemma in google/gemma-3-4b
                filtered.append(model)
        
        return filtered
    
    def select_largest_model(self, family: Optional[str] = None, service: str = "ollama") -> Optional[str]:
        """选择参数量最大的模型
        
        Args:
            family: 模型家族名称，如'gemma3', 'llama3'等。如果为None，则从所有模型中选择
            service: 服务类型，"ollama" 或 "lm_studio"
            
        Returns:
            参数量最大的模型名称，如果没有找到则返回None
        """
        models = self.get_available_models(service)
        if not models:
            self.logger.warning(f"没有找到{service}的可用模型")
            return None
        
        # 按家族过滤模型
        if family:
            models = self.filter_models_by_family(models, family)
            if not models:
                self.logger.warning(f"没有找到{service}中{family}家族的模型")
                return None
        
        # 解析每个模型的参数量并排序
        model_sizes = []
        models_without_size = []
        
        for model in models:
            model_name = model.get('name', '')
            size = self.parse_model_size(model_name)
            if size is not None:
                model_sizes.append((model_name, size))
                self.logger.debug(f"发现模型: {model_name}, 参数量: {size}B")
            else:
                models_without_size.append(model_name)
                self.logger.debug(f"发现模型: {model_name}, 参数量未知")
        
        # 如果有带参数量信息的模型，优先选择参数量最大的
        if model_sizes:
            # 按参数量降序排序，选择最大的
            model_sizes.sort(key=lambda x: x[1], reverse=True)
            largest_model = model_sizes[0][0]
            
            self.logger.info(f"自动选择参数量最大的模型: {largest_model} ({model_sizes[0][1]}B)")
            
            # 显示所有找到的模型
            if len(model_sizes) > 1:
                self.logger.info("其他可用模型:")
                for name, size in model_sizes[1:]:
                    self.logger.info(f"  - {name} ({size}B)")
            
            return largest_model
        
        # 如果没有带参数量信息的模型，但有其他模型，选择第一个
        elif models_without_size:
            selected_model = models_without_size[0]
            self.logger.info(f"选择第一个可用模型: {selected_model} (参数量未知)")
            
            if len(models_without_size) > 1:
                self.logger.info("其他可用模型:")
                for name in models_without_size[1:]:
                    self.logger.info(f"  - {name} (参数量未知)")
            
            return selected_model
        
        # 如果什么都没找到
        else:
            self.logger.warning("没有找到可用的模型")
            return None
    
    def get_model_info(self, model_name: str) -> Optional[Dict]:
        """获取指定模型的详细信息"""
        models = self.get_available_models()
        for model in models:
            if model.get('name') == model_name:
                return model
        return None
    
    def is_model_available(self, model_name: str) -> bool:
        """检查指定模型是否可用"""
        models = self.get_available_models()
        for model in models:
            if model.get('name') == model_name:
                return True
        return False
    
    def suggest_best_model(self, preferred_family: Optional[str] = None) -> Tuple[Optional[str], str, str]:
        """建议最佳模型，支持多服务和 gemma3 优先
        
        Returns:
            (模型名称, 服务名称, 建议原因)
        """
        # 检查服务可用性
        from utils.model_service_client import ModelServiceManager
        service_manager = ModelServiceManager(self.config)
        available_services = service_manager.get_available_services()
        
        if not available_services:
            return None, "", "没有可用的模型服务"
        
        # 按优先级尝试服务
        for service in self.config.MODEL_SERVICE_PRIORITY:
            if service not in available_services:
                continue
            
            # 首先尝试 gemma3 家族（如果没有指定其他家族）
            target_family = preferred_family or "gemma3"
            
            # 尝试指定家族
            model = self.select_largest_model(target_family, service)
            if model:
                size = self.parse_model_size(model)
                service_name = "LM Studio" if service == "lm_studio" else "Ollama"
                return model, service, f"在{service_name}的{target_family}家族中选择了参数量最大的模型 ({size}B)"
            
            # 如果指定家族没有找到，按优先级尝试其他家族
            for family in self.family_priority:
                if family == target_family:
                    continue  # 已经尝试过了
                
                model = self.select_largest_model(family, service)
                if model:
                    size = self.parse_model_size(model)
                    service_name = "LM Studio" if service == "lm_studio" else "Ollama"
                    return model, service, f"在{service_name}的{family}家族中选择了参数量最大的模型 ({size}B)"
            
            # 如果所有优先家族都没有找到，选择任意最大的模型
            model = self.select_largest_model(None, service)
            if model:
                size = self.parse_model_size(model)
                family = model.split(':')[0] if ':' in model else model
                service_name = "LM Studio" if service == "lm_studio" else "Ollama"
                return model, service, f"在{service_name}中选择了参数量最大的模型 {family} ({size}B)"
        
        # 最后的备选方案：直接从服务管理器获取所有模型，选择第一个可用的
        all_models = service_manager.get_all_models()
        if all_models:
            for service_name, models in all_models.items():
                if models and service_name in available_services:
                    model = models[0]['name']
                    service_name_display = "LM Studio" if service_name == "lm_studio" else "Ollama"
                    return model, service_name, f"在{service_name_display}中选择了第一个可用模型 {model}"
        
        return None, "", "没有找到可用的模型"


def auto_select_model(config=None, preferred_family: Optional[str] = None) -> Tuple[Optional[str], str, str]:
    """便捷函数：自动选择最佳模型
    
    Args:
        config: 配置对象，如果为None则使用默认配置
        preferred_family: 首选模型家族，如'gemma3', 'llama3'等
        
    Returns:
        (模型名称, 服务名称, 建议原因)
    """
    if config is None:
        from core.config import SubTransConfig
        config = SubTransConfig()
    
    selector = ModelSelector(config)
    return selector.suggest_best_model(preferred_family)


if __name__ == "__main__":
    # 测试代码
    selector = ModelSelector()
    
    print("=== 获取所有可用模型 ===")
    models = selector.get_available_models()
    for model in models:
        print(f"- {model.get('name', 'Unknown')}")
    
    print("\n=== 选择最大参数量的gemma3模型 ===")
    best_gemma = selector.select_largest_model('gemma3')
    print(f"选择结果: {best_gemma}")
    
    print("\n=== 选择全局最大参数量的模型 ===")
    best_overall = selector.select_largest_model()
    print(f"选择结果: {best_overall}")
    
    print("\n=== 智能建议 ===")
    model, service, reason = selector.suggest_best_model('gemma3')
    print(f"建议模型: {model}")
    print(f"使用服务: {service}")
    print(f"建议原因: {reason}")