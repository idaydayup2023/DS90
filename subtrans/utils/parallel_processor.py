#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubTrans 2.0 - 并行处理管理器
实现多线程并行处理，提升批量处理性能
"""

from dataclasses import dataclass, field
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.config import SubTransConfig
from utils.logger import get_logger

logger = get_logger(__name__)


class TaskStatus(Enum):
    """任务状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 在导入部分添加Any


@dataclass
class ProcessingTask:
    """处理任务"""

    task_id: str
    input_data: Any
    processor_func: Callable[..., Any]
    kwargs: Dict[str, Any] = field(
        default_factory=dict
    )  # 使用field确保每个实例都有独立的字典
    priority: int = 0
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[Exception] = None
    start_time: float = 0.0
    end_time: float = 0.0


@dataclass
class ProcessingStats:
    """处理统计信息"""

    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    total_time: float = 0.0
    average_time: float = 0.0
    throughput: float = 0.0  # 任务/秒


class ParallelProcessor:
    """并行处理管理器"""

    def __init__(
        self, config: SubTransConfig, max_workers: Optional[int] = None
    ):
        self.config = config
        self.max_workers = max_workers or min(8, (os.cpu_count() or 1) + 4)

        # 任务管理
        self.task_queue = queue.PriorityQueue()
        self.active_tasks: Dict[str, ProcessingTask] = {}
        self.completed_tasks: Dict[str, ProcessingTask] = {}

        # 线程池
        self.executor: Optional[ThreadPoolExecutor] = None
        self.is_running = False

        # 统计信息
        self.stats = ProcessingStats()
        self.start_time = 0.0

        # 进度回调
        self.progress_callback: Optional[Callable] = None

        # 线程锁
        self.lock = threading.Lock()

        logger.info(
            f"并行处理器初始化完成，最大工作线程数: {self.max_workers}"
        )

    def start(self) -> None:
        """启动并行处理器"""
        if self.is_running:
            logger.warning("并行处理器已在运行")
            return

        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.is_running = True
        self.start_time = time.time()

        logger.info("并行处理器已启动")

    def stop(self) -> None:
        """停止并行处理器"""
        if not self.is_running:
            return

        self.is_running = False

        if self.executor:
            self.executor.shutdown(wait=True)
            self.executor = None

        # 更新统计信息
        if self.start_time > 0:
            self.stats.total_time = time.time() - self.start_time
            if self.stats.completed_tasks > 0:
                self.stats.average_time = (
                    self.stats.total_time / self.stats.completed_tasks
                )
                self.stats.throughput = (
                    self.stats.completed_tasks / self.stats.total_time
                )

        logger.info("并行处理器已停止")

    def add_task(
        self,
        task_id: str,
        input_data: Any,
        processor_func: Callable,
        priority: int = 0,
        **kwargs,
    ) -> None:
        """添加处理任务"""
        task = ProcessingTask(
            task_id=task_id,
            input_data=input_data,
            processor_func=processor_func,
            kwargs=kwargs,
            priority=priority,
        )

        with self.lock:
            self.active_tasks[task_id] = task
            self.stats.total_tasks += 1

        # 如果处理器正在运行，直接提交任务到线程池
        if self.is_running and self.executor is not None:
            future = self.executor.submit(self._execute_task, task)
            # 可以选择存储future以便后续跟踪
        else:
            # 否则添加到队列等待批量处理
            self.task_queue.put((-priority, task_id, task))

        logger.debug(f"添加任务: {task_id} (优先级: {priority})")

    def process_batch(
        self,
        tasks: List[Tuple[str, Any, Callable]],
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """批量处理任务"""
        if not self.is_running:
            self.start()

        # 确保 executor 已初始化
        if self.executor is None:
            raise RuntimeError("Executor not initialized. Call start() first.")

        self.progress_callback = progress_callback

        # 直接提交任务到线程池，不使用add_task
        future_to_task = {}

        for i, (task_id, input_data, processor_func) in enumerate(tasks):
            task = ProcessingTask(
                task_id=task_id,
                input_data=input_data,
                processor_func=processor_func,
                priority=i,
            )

            with self.lock:
                self.active_tasks[task_id] = task
                self.stats.total_tasks += 1

            future = self.executor.submit(self._execute_task, task)
            future_to_task[future] = task

        # 等待任务完成
        results = {}
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            try:
                result = future.result()
                results[task.task_id] = result

                # 更新进度
                if self.progress_callback:
                    progress = (
                        self.stats.completed_tasks + self.stats.failed_tasks
                    ) / self.stats.total_tasks
                    self.progress_callback(progress, task.task_id, result)

            except Exception as e:
                logger.error(f"任务 {task.task_id} 执行失败: {e}")
                results[task.task_id] = None

        return results

    def _execute_task(self, task: ProcessingTask) -> Any:
        """执行单个任务"""
        task.start_time = time.time()
        task.status = TaskStatus.RUNNING

        try:
            logger.debug(f"开始执行任务: {task.task_id}")

            # 执行处理函数
            result = task.processor_func(task.input_data, **task.kwargs)

            task.result = result
            task.status = TaskStatus.COMPLETED
            task.end_time = time.time()

            with self.lock:
                self.stats.completed_tasks += 1
                self.completed_tasks[task.task_id] = task
                if task.task_id in self.active_tasks:
                    del self.active_tasks[task.task_id]

            logger.debug(
                f"任务完成: {task.task_id} (耗时: {task.end_time - task.start_time:.2f}s)"
            )
            return result

        except Exception as e:
            task.error = e
            task.status = TaskStatus.FAILED
            task.end_time = time.time()

            with self.lock:
                self.stats.failed_tasks += 1
                # 将失败的任务移到completed_tasks而不是删除
                self.completed_tasks[task.task_id] = task
                if task.task_id in self.active_tasks:
                    del self.active_tasks[task.task_id]

            logger.error(f"任务失败: {task.task_id} - {e}")
            raise e

    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """获取任务状态"""
        # 先检查活跃任务
        if task_id in self.active_tasks:
            return self.active_tasks[task_id].status
        # 再检查已完成任务（包括失败的任务）
        elif task_id in self.completed_tasks:
            return self.completed_tasks[task_id].status
        return None

    def get_task_result(self, task_id: str) -> Any:
        """获取任务结果"""
        if task_id in self.completed_tasks:
            task = self.completed_tasks[task_id]
            if task.status == TaskStatus.COMPLETED:
                return task.result
            elif task.status == TaskStatus.FAILED:
                if task.error is not None:  # 添加None检查
                    raise task.error
                else:
                    raise RuntimeError(f"任务 {task_id} 失败但没有错误信息")
        return None

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        with self.lock:
            if task_id in self.active_tasks:
                task = self.active_tasks[task_id]
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.CANCELLED
                    self.stats.cancelled_tasks += 1
                    del self.active_tasks[task_id]
                    logger.info(f"任务已取消: {task_id}")
                    return True
        return False

    def get_stats(self) -> ProcessingStats:
        """获取处理统计信息"""
        return self.stats

    def clear_completed_tasks(self) -> None:
        """清理已完成的任务"""
        with self.lock:
            self.completed_tasks.clear()
            logger.debug("已清理完成的任务")

    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.stop()

    def process_files(
        self,
        file_paths: List[str],
        output_dir: str,
        processor_func: Callable,
        max_workers: Optional[int] = None,
    ) -> List[Any]:
        """并行处理文件列表"""
        if not file_paths:
            return []

        # 设置工作线程数
        original_workers = None  # 初始化变量
        if max_workers:
            original_workers = self.max_workers
            self.max_workers = max_workers

        try:
            # 构建任务列表
            tasks = []
            for i, file_path in enumerate(file_paths):
                task_id = f"file_{i}_{Path(file_path).stem}"
                tasks.append(
                    (
                        task_id,
                        file_path,
                        lambda path: processor_func(path, output_dir),
                    )
                )

            # 执行批量处理
            results = self.process_batch(tasks)

            # 返回结果列表
            return [results.get(task_id) for task_id, _, _ in tasks]

        finally:
            # 恢复原始工作线程数
            if max_workers and original_workers is not None:
                self.max_workers = original_workers
