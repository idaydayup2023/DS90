#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
媒体库字幕管理工具
提供完整的字幕扫描、AI字幕检查和管理功能
"""

import os
import sys
import argparse
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

# 添加项目路径到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from media_manager.scanner.file_scanner import MediaFileScanner
from media_manager.utils.subtitle_detector import SubtitleDetector
from media_manager.database.db_manager import get_db_manager

class SubtitleManagementTool:
    """字幕管理工具"""
    
    def __init__(self):
        self.db = get_db_manager()
        self.scanner = MediaFileScanner()
        self.subtitle_detector = SubtitleDetector()
        
        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def scan_media_with_subtitles(self, scan_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        """扫描媒体文件并检测字幕"""
        
        if not scan_paths:
            # 从数据库获取配置的扫描路径
            paths = self.db.execute_query("SELECT full_path FROM scan_paths WHERE is_enabled = 1")
            scan_paths = [path['full_path'] for path in paths]
        
        if not scan_paths:
            self.logger.warning("没有找到启用的扫描路径")
            return {'error': '没有找到启用的扫描路径'}
        
        total_results = {
            'files_scanned': 0,
            'files_added': 0,
            'files_updated': 0,
            'files_skipped': 0,
            'errors': 0,
            'subtitles_found': 0,
            'ai_subtitles_found': 0
        }
        
        for scan_path in scan_paths:
            if not os.path.exists(scan_path):
                self.logger.warning(f"扫描路径不存在: {scan_path}")
                continue
            
            self.logger.info(f"开始扫描路径: {scan_path}")
            
            # 扫描媒体文件
            results = self.scanner.scan_directory(scan_path)
            
            # 累计结果
            for key in total_results:
                if key in results:
                    total_results[key] += results[key]
        
        # 统计字幕信息
        subtitle_stats = self.get_subtitle_statistics()
        total_results['subtitles_found'] = subtitle_stats['total_subtitles']
        total_results['ai_subtitles_found'] = subtitle_stats['ai_subtitles']
        
        return total_results
    
    def check_missing_ai_subtitles(self) -> Dict[str, Any]:
        """检查缺失的AI字幕"""
        
        missing_files = self.scanner.get_missing_ai_subtitles_report()
        
        return {
            'total_missing': missing_files['total_missing'],
            'movies_missing': missing_files['missing_by_type']['movies'],
            'tv_shows_missing': missing_files['missing_by_type']['tv_shows'],
            'missing_files': missing_files['missing_files']
        }
    
    def get_subtitle_statistics(self) -> Dict[str, Any]:
        """获取字幕统计信息"""
        
        # 总字幕数
        total_result = self.db.execute_query("SELECT COUNT(*) as count FROM subtitle_files")
        total_subtitles = total_result[0]['count'] if total_result else 0
        
        # AI字幕数
        ai_result = self.db.execute_query("SELECT COUNT(*) as count FROM subtitle_files WHERE is_ai_generated = 1")
        ai_subtitles = ai_result[0]['count'] if ai_result else 0
        
        # 按语言统计
        lang_result = self.db.execute_query("""
            SELECT language_code, language_name, COUNT(*) as count 
            FROM subtitle_files 
            GROUP BY language_code, language_name 
            ORDER BY count DESC
        """)
        
        # 按格式统计
        format_result = self.db.execute_query("""
            SELECT format, COUNT(*) as count 
            FROM subtitle_files 
            GROUP BY format 
            ORDER BY count DESC
        """)
        
        # 按类型统计
        type_result = self.db.execute_query("""
            SELECT subtitle_type, COUNT(*) as count 
            FROM subtitle_files 
            GROUP BY subtitle_type 
            ORDER BY count DESC
        """)
        
        return {
            'total_subtitles': total_subtitles,
            'ai_subtitles': ai_subtitles,
            'other_subtitles': total_subtitles - ai_subtitles,
            'by_language': [dict(row) for row in lang_result],
            'by_format': [dict(row) for row in format_result],
            'by_type': [dict(row) for row in type_result]
        }
    
    def get_media_without_ai_subtitles(self) -> List[Dict[str, Any]]:
        """获取没有AI字幕的媒体文件"""
        
        query = """
        SELECT 
            mf.id,
            mf.file_path,
            mf.file_name,
            mi.title,
            mi.type as media_type,
            mi.year
        FROM media_files mf
        LEFT JOIN media_items mi ON mf.media_id = mi.id
        LEFT JOIN subtitle_files sf ON mf.id = sf.media_file_id AND sf.is_ai_generated = 1
        WHERE sf.id IS NULL
        ORDER BY mi.type, mi.title, mf.file_name
        """
        
        results = self.db.execute_query(query)
        return [dict(row) for row in results]
    
    def generate_ai_subtitle_report(self, output_file: Optional[str] = None) -> str:
        """生成AI字幕报告"""
        
        stats = self.get_subtitle_statistics()
        missing = self.check_missing_ai_subtitles()
        media_without_ai = self.get_media_without_ai_subtitles()
        
        report_lines = [
            "=" * 60,
            "媒体库AI字幕报告",
            "=" * 60,
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "📊 字幕统计概览:",
            f"  总字幕文件数: {stats['total_subtitles']}",
            f"  AI字幕文件数: {stats['ai_subtitles']}",
            f"  其他字幕文件数: {stats['other_subtitles']}",
            f"  AI字幕覆盖率: {(stats['ai_subtitles'] / max(stats['total_subtitles'], 1) * 100):.1f}%",
            "",
            "🌍 按语言分布:",
        ]
        
        for lang in stats['by_language']:
            report_lines.append(f"  {lang['language_name']} ({lang['language_code']}): {lang['count']} 个")
        
        report_lines.extend([
            "",
            "📄 按格式分布:",
        ])
        
        for fmt in stats['by_format']:
            report_lines.append(f"  {fmt['format'].upper()}: {fmt['count']} 个")
        
        report_lines.extend([
            "",
            "🏷️ 按类型分布:",
        ])
        
        for typ in stats['by_type']:
            report_lines.append(f"  {typ['subtitle_type']}: {typ['count']} 个")
        
        report_lines.extend([
            "",
            "❌ 缺失AI字幕统计:",
            f"  总计缺失: {missing['total_missing']} 个文件",
            f"  电影缺失: {missing['movies_missing']} 个",
            f"  电视剧缺失: {missing['tv_shows_missing']} 个",
            "",
        ])
        
        if media_without_ai:
            report_lines.extend([
                "📋 缺失AI字幕的媒体文件:",
                ""
            ])
            
            current_type = None
            for media in media_without_ai:
                if media['media_type'] != current_type:
                    current_type = media['media_type']
                    type_name = "电影" if current_type == "movie" else "电视剧"
                    report_lines.append(f"  {type_name}:")
                
                title = media['title'] or "未知标题"
                year = f" ({media['year']})" if media['year'] else ""
                report_lines.append(f"    - {title}{year}")
                report_lines.append(f"      文件: {media['file_name']}")
                report_lines.append("")
        else:
            report_lines.append("🎉 所有媒体文件都已有AI字幕！")
        
        report_lines.extend([
            "",
            "=" * 60,
            "报告结束",
            "=" * 60
        ])
        
        report_content = "\n".join(report_lines)
        
        if output_file:
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(report_content)
                self.logger.info(f"报告已保存到: {output_file}")
            except Exception as e:
                self.logger.error(f"保存报告失败: {e}")
        
        return report_content
    
    def cleanup_orphaned_subtitles(self) -> int:
        """清理孤立的字幕记录（对应的媒体文件已不存在）"""
        
        query = """
        DELETE FROM subtitle_files 
        WHERE media_file_id NOT IN (SELECT id FROM media_files)
        """
        
        result = self.db.execute_update(query)
        deleted_count = result if result else 0
        
        self.logger.info(f"清理了 {deleted_count} 个孤立的字幕记录")
        return deleted_count
    
    def rescan_subtitles_for_media(self, media_file_ids: Optional[List[int]] = None) -> Dict[str, int]:
        """重新扫描指定媒体文件的字幕"""
        
        if media_file_ids:
            # 扫描指定的媒体文件
            media_files = self.db.execute_query("""
                SELECT id, file_path FROM media_files WHERE id IN ({})
            """.format(','.join('?' * len(media_file_ids))), tuple(media_file_ids))
        else:
            # 扫描所有媒体文件
            media_files = self.db.execute_query("SELECT id, file_path FROM media_files")
        
        processed = 0
        updated = 0
        
        for media_file in media_files:
            try:
                # 删除旧的字幕记录
                self.db.execute_update(
                    "DELETE FROM subtitle_files WHERE media_file_id = ?",
                    (media_file['id'],)
                )
                
                # 重新检测字幕
                video_path = media_file['file_path']
                if os.path.exists(video_path):
                    subtitles = self.subtitle_detector.detect_subtitles_for_video(video_path)
                    
                    for subtitle in subtitles:
                        self.subtitle_detector.save_subtitle_info(media_file['id'], subtitle)
                        updated += 1
                
                processed += 1
                
            except Exception as e:
                self.logger.error(f"重新扫描字幕失败 {media_file['file_path']}: {e}")
        
        return {'processed': processed, 'updated': updated}

def main():
    """主函数"""
    
    parser = argparse.ArgumentParser(description='媒体库字幕管理工具')
    parser.add_argument('action', choices=[
        'scan', 'check', 'stats', 'report', 'cleanup', 'rescan'
    ], help='执行的操作')
    
    parser.add_argument('--paths', nargs='+', help='扫描路径（用于scan操作）')
    parser.add_argument('--output', '-o', help='输出文件路径（用于report操作）')
    parser.add_argument('--media-ids', nargs='+', type=int, help='媒体文件ID列表（用于rescan操作）')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    tool = SubtitleManagementTool()
    
    try:
        if args.action == 'scan':
            print("🔍 开始扫描媒体文件和字幕...")
            results = tool.scan_media_with_subtitles(args.paths)
            
            if 'error' in results:
                print(f"❌ 扫描失败: {results['error']}")
                return 1
            
            print("\n📊 扫描结果:")
            print(f"  扫描文件数: {results['files_scanned']}")
            print(f"  添加文件数: {results['files_added']}")
            print(f"  更新文件数: {results['files_updated']}")
            print(f"  跳过文件数: {results['files_skipped']}")
            print(f"  错误数: {results['errors']}")
            print(f"  发现字幕数: {results['subtitles_found']}")
            print(f"  AI字幕数: {results['ai_subtitles_found']}")
        
        elif args.action == 'check':
            print("🔍 检查缺失的AI字幕...")
            missing = tool.check_missing_ai_subtitles()
            
            print(f"\n❌ 缺失AI字幕统计:")
            print(f"  总计缺失: {missing['total_missing']} 个文件")
            print(f"  电影缺失: {missing['movies_missing']} 个")
            print(f"  电视剧缺失: {missing['tv_shows_missing']} 个")
            
            if missing['missing_files']:
                print(f"\n📋 缺失AI字幕的文件:")
                for file_info in missing['missing_files'][:10]:  # 只显示前10个
                    print(f"  - {file_info['file_name']}")
                
                if len(missing['missing_files']) > 10:
                    print(f"  ... 还有 {len(missing['missing_files']) - 10} 个文件")
        
        elif args.action == 'stats':
            print("📊 获取字幕统计信息...")
            stats = tool.get_subtitle_statistics()
            
            print(f"\n📈 字幕统计:")
            print(f"  总字幕文件数: {stats['total_subtitles']}")
            print(f"  AI字幕文件数: {stats['ai_subtitles']}")
            print(f"  其他字幕文件数: {stats['other_subtitles']}")
            
            if stats['by_language']:
                print(f"\n🌍 按语言分布:")
                for lang in stats['by_language'][:5]:
                    print(f"  {lang['language_name']}: {lang['count']} 个")
            
            if stats['by_format']:
                print(f"\n📄 按格式分布:")
                for fmt in stats['by_format']:
                    print(f"  {fmt['format'].upper()}: {fmt['count']} 个")
        
        elif args.action == 'report':
            print("📋 生成AI字幕报告...")
            report = tool.generate_ai_subtitle_report(args.output)
            
            if not args.output:
                print(report)
            else:
                print(f"✅ 报告已保存到: {args.output}")
        
        elif args.action == 'cleanup':
            print("🧹 清理孤立的字幕记录...")
            deleted = tool.cleanup_orphaned_subtitles()
            print(f"✅ 清理了 {deleted} 个孤立的字幕记录")
        
        elif args.action == 'rescan':
            print("🔄 重新扫描字幕...")
            results = tool.rescan_subtitles_for_media(args.media_ids)
            print(f"✅ 处理了 {results['processed']} 个媒体文件")
            print(f"✅ 更新了 {results['updated']} 个字幕记录")
        
        print("\n✅ 操作完成！")
        return 0
        
    except Exception as e:
        print(f"❌ 操作失败: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())