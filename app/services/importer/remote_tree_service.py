"""远端目录树快照服务：调用 115 fs_export_dir 接口一次性导出目录树 txt，解析后存入 TreeImport/TreeNode。

设计原则：
- 仅手动触发，不能后台自动执行（高风控接口）
- 使用 p115client.P115Client（cookies）调用 webapi，而非 Open API token
- 导出完成后下载 txt，复用现有 parse_tree_bytes 解析器
- 全程不在 API 调用期间持有 DB 事务，避免 SQLite 写锁竞争
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import requests as http_requests
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tree import TreeImport, TreeNode
from app.services.classifier.keyword_classifier import normalize_folder_name
from app.services.importer.tree_parser import parse_tree_bytes

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2      # 秒
_POLL_MAX_TRIES = 60    # 最多等 2 分钟
_TREE_ROOT_PREFIX = "|---- "
_TREE_CHILD_PREFIX = "| "


class RemoteTreeFetchService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_p115_client(self):
        """懒加载 p115client.P115Client（使用 cookies 文件）。"""
        try:
            import p115client  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("p115client 未安装") from exc
        cookies_path = Path(get_settings().cookies_path)
        if not cookies_path.exists():
            raise RuntimeError(f"cookies 文件不存在：{cookies_path}")
        return p115client.P115Client(cookies_path.read_text().strip())

    @staticmethod
    def _normalize_export_cid(cid: str) -> int | str:
        normalized = cid.strip()
        if normalized.isdigit():
            return int(normalized)
        return normalized

    def _list_dir_items(self, client, cid: int | str) -> list[dict]:
        items: list[dict] = []
        offset = 0
        while True:
            response = client.fs_files({
                "cid": cid,
                "limit": 200,
                "offset": offset,
                "show_dir": 1,
            })
            batch = response.get("data") or []
            items.extend(batch)
            total = int(response.get("count", 0) or 0)
            if not batch or len(items) >= total:
                break
            offset += len(batch)
            time.sleep(0.2)
        return items

    def _build_tree_bytes_from_listing(self, client, cid: int | str, label: str, max_depth: int) -> bytes:
        lines: list[str] = [f"{_TREE_ROOT_PREFIX}{label}"]

        def walk(parent_cid: int | str, depth: int) -> None:
            if depth >= max_depth:
                return
            prefix = "|" + _TREE_CHILD_PREFIX * depth
            for item in self._list_dir_items(client, parent_cid):
                name = str(item.get("fn") or item.get("file_name") or "未命名")
                is_folder = str(item.get("fc", "1")) == "0"
                lines.append(f"{prefix}- {name}")
                if is_folder:
                    child_cid = item.get("fid") or item.get("file_id")
                    if child_cid not in (None, ""):
                        walk(str(child_cid), depth + 1)

        walk(cid, 0)
        return ("\n".join(lines) + "\n").encode("utf-8")

    def fetch_subtree(
        self,
        cid: str,
        path_label: str,
        *,
        depth_limit: int = 3,
        folders_only: bool = True,
    ) -> TreeImport:
        """触发 115 目录树导出，下载 txt 并解析存库。

        cid        — 115 目录 ID
        path_label — 用户可读路径标签，仅用于展示
        depth_limit — 导出层级深度（传给 layer_limit）
        """
        label = path_label.strip() or f"cid:{cid}"
        client = self._get_p115_client()
        export_cid = self._normalize_export_cid(cid)
        logger.info("准备拉取远端目录树 cid=%s normalized_cid=%r depth_limit=%s label=%s", cid, export_cid, depth_limit, label)

        # 1. 触发导出
        export_resp = client.fs_export_dir({
            "file_ids": export_cid,
            "target": "U_1_0",
            "layer_limit": depth_limit,
        })
        export_id = export_resp.get("data", {}).get("export_id")
        if not export_id:
            if export_cid == 0 and int(export_resp.get("errno", 0) or 0) == 90008:
                logger.warning("fs_export_dir 不支持根目录 cid=0，回退到分页遍历模式")
                raw_bytes = self._build_tree_bytes_from_listing(client, export_cid, label, depth_limit)
                logger.info("根目录回退遍历完成，生成目录树文本大小=%d bytes", len(raw_bytes))
                return self._persist_tree_import(
                    cid=str(export_cid),
                    depth_limit=depth_limit,
                    raw_bytes=raw_bytes,
                    source_label=label,
                )
            raise RuntimeError(f"fs_export_dir 返回异常：{export_resp}")
        logger.info("目录树导出已触发 export_id=%s cid=%s", export_id, cid)

        # 2. 轮询完成（file_id 出现即为完成）
        pick_code = None
        for _ in range(_POLL_MAX_TRIES):
            status = client.fs_export_dir_status({"export_id": export_id})
            data = status.get("data")
            if isinstance(data, dict) and data.get("file_id"):
                pick_code = data.get("pick_code")
                logger.info("目录树导出完成 pick_code=%s", pick_code)
                break
            time.sleep(_POLL_INTERVAL)
        else:
            raise RuntimeError("等待目录树导出超时（>2分钟）")

        # 3. 获取下载链接并下载（需空 user-agent，否则 403）
        download_url = client.download_url(pick_code)
        raw_bytes = http_requests.get(str(download_url), headers={"user-agent": ""}).content
        logger.info("目录树 txt 下载完成，大小=%d bytes", len(raw_bytes))

        return self._persist_tree_import(
            cid=str(export_cid),
            depth_limit=depth_limit,
            raw_bytes=raw_bytes,
            source_label=label,
        )

    def _persist_tree_import(
        self,
        *,
        cid: str,
        depth_limit: int,
        raw_bytes: bytes,
        source_label: str,
    ) -> TreeImport:
        logger.info("开始解析目录树文本 source=%s cid=%s", source_label, cid)

        # 4. 解析（复用现有解析器）
        parsed_nodes = parse_tree_bytes(raw_bytes)
        folder_nodes = [p for p in parsed_nodes if p.node_type == "folder"]
        logger.info("解析完成，文件夹节点数=%d", len(folder_nodes))

        # 5. 写入 DB（先 commit TreeImport，再批量插 TreeNode，全程无长事务）
        tree_import = TreeImport(
            source_filename=f"remote:{source_label}",
            source_type="remote_115",
            status="processing",
            note=f"cid={cid} depth_limit={depth_limit}",
        )
        self.db.add(tree_import)
        self.db.commit()
        self.db.refresh(tree_import)

        seen_paths: set[str] = set()
        folder_path_to_id: dict[str, int] = {}
        db_nodes: list[TreeNode] = []
        for p in folder_nodes:
            if p.raw_path in seen_paths:
                continue
            seen_paths.add(p.raw_path)
            node = TreeNode(
                import_id=tree_import.id,
                raw_name=p.name,
                normalized_name=normalize_folder_name(p.name),
                raw_path=p.raw_path,
                parent_path=p.parent_path,
                depth=p.depth,
                node_type="folder",
                parent_id=folder_path_to_id.get(p.parent_path or ""),
                fingerprint_hint=p.fingerprint_hint,
            )
            db_nodes.append(node)

        self.db.add_all(db_nodes)
        self.db.flush()
        for node in db_nodes:
            folder_path_to_id[node.raw_path] = node.id

        tree_import.status = "completed"
        tree_import.note = f"cid={cid} depth_limit={depth_limit} folders={len(db_nodes)}"
        self.db.commit()
        self.db.refresh(tree_import)
        logger.info(
            "远端目录树快照完成：import_id=%d cid=%s folders=%d",
            tree_import.id, cid, len(db_nodes),
        )
        return tree_import
