#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import requests
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
from utils.logger import get_logger


class ModelServiceClient(ABC):
    """模型服务客户端抽象基类"""
    
    def __init__(self, url: str, timeout: int = 120):
        self.url = url.rstrip('/')
        self.timeout = timeout
        self.logger = get_logger(__name__)
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查服务是否可用"""
        pass
    
    @abstractmethod
    def get_available_models(self) -> List[Dict]:
        """获取可用模型列表"""
        pass
    
    @abstractmethod
    def generate_text(self, prompt: str, model: str, **kwargs) -> str:
        """生成文本"""
        pass
    
    @abstractmethod
    def get_service_name(self) -> str:
        """获取服务名称"""
        pass


class OllamaClient(ModelServiceClient):
    """Ollama 客户端"""
    
    def __init__(self, url: str, timeout: int = 120):
        super().__init__(url, timeout)
        self.api_url = f"{self.url}/api/generate"
    
    def get_service_name(self) -> str:
        return "Ollama"
    
    def is_available(self) -> bool:
        """检查 Ollama 服务是否可用"""
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception as e:
            self.logger.debug(f"Ollama 服务不可用: {e}")
            return False
    
    def get_available_models(self) -> List[Dict]:
        """获取 Ollama 可用模型列表"""
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get('models', [])
            return []
        except Exception as e:
            self.logger.error(f"获取 Ollama 模型列表失败: {e}")
            return []
    
    def generate_text(self, prompt: str, model: str, **kwargs) -> str:
        """使用 Ollama 生成文本"""
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.1),
                "top_p": kwargs.get("top_p", 0.9),
                "num_predict": kwargs.get("max_tokens", 2048)
            }
        }
        
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "").strip()
            else:
                raise Exception(f"Ollama API 错误: {response.status_code} - {response.text}")
                
        except Exception as e:
            self.logger.error(f"Ollama 生成文本失败: {e}")
            raise


class LMStudioClient(ModelServiceClient):
    """LM Studio 客户端"""
    
    def __init__(self, url: str, timeout: int = 120):
        super().__init__(url, timeout)
        self.api_url = f"{self.url}/v1/chat/completions"
        self.models_url = f"{self.url}/v1/models"
    
    def get_service_name(self) -> str:
        return "LM Studio"
    
    def is_available(self) -> bool:
        """检查 LM Studio 服务是否可用"""
        try:
            response = requests.get(self.models_url, timeout=5)
            return response.status_code == 200
        except Exception as e:
            self.logger.debug(f"LM Studio 服务不可用: {e}")
            return False
    
    def get_available_models(self) -> List[Dict]:
        """获取 LM Studio 可用模型列表"""
        try:
            response = requests.get(self.models_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                models = data.get('data', [])
                # 转换为统一格式
                return [{"name": model.get("id", ""), "model": model} for model in models]
            return []
        except Exception as e:
            self.logger.error(f"获取 LM Studio 模型列表失败: {e}")
            return []
    
    def generate_text(self, prompt: str, model: str, **kwargs) -> str:
        """使用 LM Studio 生成文本"""
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": kwargs.get("temperature", 0.1),
            "max_tokens": kwargs.get("max_tokens", 2048),
            "top_p": kwargs.get("top_p", 0.9),
            "stream": False
        }
        
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                choices = result.get("choices", [])
                if choices:
                    message = choices[0].get("message", {})
                    return message.get("content", "").strip()
                return ""
            else:
                raise Exception(f"LM Studio API 错误: {response.status_code} - {response.text}")
                
        except Exception as e:
            self.logger.error(f"LM Studio 生成文本失败: {e}")
            raise


class ModelServiceManager:
    """模型服务管理器，负责管理多个模型服务"""
    
    def __init__(self, config):
        self.config = config
        self.logger = get_logger(__name__)
        self.clients = {}
        self.preferred_service = None  # 首选服务
        self._initialize_clients()
    
    def _initialize_clients(self):
        """初始化所有客户端"""
        # 初始化 Ollama 客户端
        self.clients["ollama"] = OllamaClient(
            self.config.OLLAMA_URL,
            self.config.OLLAMA_TIMEOUT
        )
        
        # 初始化 LM Studio 客户端
        self.clients["lm_studio"] = LMStudioClient(
            self.config.LM_STUDIO_URL,
            self.config.LM_STUDIO_TIMEOUT
        )
    
    def get_available_services(self) -> List[str]:
        """获取可用的服务列表"""
        available = []
        for service_name, client in self.clients.items():
            if client.is_available():
                available.append(service_name)
                self.logger.info(f"✅ {client.get_service_name()} 服务可用")
            else:
                self.logger.debug(f"❌ {client.get_service_name()} 服务不可用")
        return available
    
    def health_check(self) -> Dict[str, Dict[str, Any]]:
        """执行健康检查，返回所有服务的状态信息"""
        health_status = {}
        
        for service_name, client in self.clients.items():
            try:
                is_available = client.is_available()
                models = client.get_available_models() if is_available else []
                
                health_status[service_name] = {
                    "service_name": client.get_service_name(),
                    "available": is_available,
                    "url": client.url,
                    "timeout": client.timeout,
                    "model_count": len(models),
                    "models": [model.get("name", "") for model in models[:5]],  # 只显示前5个模型
                    "status": "healthy" if is_available else "unhealthy"
                }
                
                if is_available:
                    self.logger.info(f"🟢 {client.get_service_name()} 健康检查通过 - {len(models)} 个模型可用")
                else:
                    self.logger.warning(f"🔴 {client.get_service_name()} 健康检查失败")
                    
            except Exception as e:
                health_status[service_name] = {
                    "service_name": client.get_service_name(),
                    "available": False,
                    "url": client.url,
                    "timeout": client.timeout,
                    "error": str(e),
                    "status": "error"
                }
                self.logger.error(f"🔴 {client.get_service_name()} 健康检查异常: {e}")
        
        return health_status
    
    def set_preferred_service(self, service_name: str):
        """设置首选服务"""
        if service_name in self.clients:
            self.preferred_service = service_name
            self.logger.info(f"🎯 设置首选服务: {self.clients[service_name].get_service_name()}")
        else:
            self.logger.warning(f"⚠️ 无效的服务名称: {service_name}")
    
    def select_best_service(self) -> Optional[str]:
        """根据优先级选择最佳服务"""
        available_services = self.get_available_services()
        
        if not available_services:
            self.logger.error("没有可用的模型服务")
            return None
        
        # 如果设置了首选服务且可用，优先使用
        if self.preferred_service and self.preferred_service in available_services:
            client = self.clients[self.preferred_service]
            self.logger.info(f"🎯 使用首选服务: {client.get_service_name()}")
            return self.preferred_service
        
        # 按配置的优先级选择
        for service in self.config.MODEL_SERVICE_PRIORITY:
            if service in available_services:
                client = self.clients[service]
                self.logger.info(f"🎯 选择服务: {client.get_service_name()}")
                return service
        
        # 如果优先级列表中没有可用服务，选择第一个可用的
        selected = available_services[0]
        client = self.clients[selected]
        self.logger.info(f"🎯 备选服务: {client.get_service_name()}")
        return selected
    
    def get_client(self, service_name: str) -> Optional[ModelServiceClient]:
        """获取指定服务的客户端"""
        return self.clients.get(service_name)
    
    def get_all_models(self) -> Dict[str, List[Dict]]:
        """获取所有服务的模型列表"""
        all_models = {}
        for service_name, client in self.clients.items():
            if client.is_available():
                models = client.get_available_models()
                all_models[service_name] = models
                self.logger.debug(f"{client.get_service_name()} 可用模型数量: {len(models)}")
        return all_models
    
    def generate_text(self, prompt: str, service_name: Optional[str] = None, model: Optional[str] = None, **kwargs) -> Tuple[str, str]:
        """生成文本，支持自动切换服务
        
        Returns:
            (生成的文本, 使用的服务名称)
        """
        # 如果指定了服务，尝试使用该服务
        if service_name:
            return self._try_generate_with_service(prompt, service_name, model, **kwargs)
        
        # 没有指定服务，按优先级尝试所有可用服务
        available_services = self.get_available_services()
        if not available_services:
            raise Exception("没有可用的模型服务")
        
        # 如果设置了首选服务且可用，优先尝试
        if self.preferred_service and self.preferred_service in available_services:
            try:
                return self._try_generate_with_service(prompt, self.preferred_service, model, **kwargs)
            except Exception as e:
                self.logger.warning(f"首选服务 {self.preferred_service} 失败，尝试其他服务: {e}")
                # 从可用服务列表中移除失败的服务
                available_services = [s for s in available_services if s != self.preferred_service]
        
        # 按配置的优先级尝试服务
        for service in self.config.MODEL_SERVICE_PRIORITY:
            if service in available_services:
                try:
                    return self._try_generate_with_service(prompt, service, model, **kwargs)
                except Exception as e:
                    self.logger.warning(f"服务 {service} 失败，尝试下一个服务: {e}")
                    continue
        
        # 如果优先级列表中的服务都失败，尝试其他可用服务
        for service in available_services:
            if service not in self.config.MODEL_SERVICE_PRIORITY:
                try:
                    return self._try_generate_with_service(prompt, service, model, **kwargs)
                except Exception as e:
                    self.logger.warning(f"备选服务 {service} 失败: {e}")
                    continue
        
        raise Exception("所有可用的模型服务都失败了")
    
    def _try_generate_with_service(self, prompt: str, service_name: str, model: Optional[str] = None, **kwargs) -> Tuple[str, str]:
        """尝试使用指定服务生成文本"""
        client = self.get_client(service_name)
        if not client:
            raise Exception(f"服务 {service_name} 不存在")
        
        if not client.is_available():
            raise Exception(f"服务 {client.get_service_name()} 不可用")
        
        # 如果没有指定模型，使用配置中的默认模型
        if not model:
            if service_name == "ollama":
                model = self.config.OLLAMA_MODEL
            elif service_name == "lm_studio":
                model = self.config.LM_STUDIO_MODEL
            else:
                raise Exception(f"未知的服务类型: {service_name}")
        
        if not model:
            raise Exception(f"服务 {service_name} 没有配置默认模型")
        
        # 设置服务特定的参数
        if service_name == "lm_studio":
            kwargs.setdefault("temperature", self.config.LM_STUDIO_TEMPERATURE)
            kwargs.setdefault("max_tokens", self.config.LM_STUDIO_MAX_TOKENS)
        
        result = client.generate_text(prompt, model, **kwargs)
        self.logger.debug(f"使用 {client.get_service_name()} 生成文本成功")
        return result, service_name