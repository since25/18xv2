from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.models.tree import TreeNode
from app.schemas.node import NodePageResponse, NodeResponse

router = APIRouter(tags=["nodes"])


@router.get("/nodes", response_class=HTMLResponse)
def nodes_workbench(import_id: int | None = None) -> str:
    initial_import_id = "" if import_id is None else str(import_id)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>节点列表</title>
  <style>
    :root {{ --bg:#f6efe5; --card:#fffaf3; --ink:#1f2421; --muted:#5b645f; --accent:#115e59; --soft:#d7ece8; --line:#ddd3c4; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:"PingFang SC","Noto Sans SC",sans-serif; background:linear-gradient(135deg,#f8f3ea 0%,#eee3d6 100%); color:var(--ink); }}
    .shell {{ max-width:1280px; margin:0 auto; padding:28px 18px 40px; }}
    .hero,.panel {{ background:var(--card); border:1px solid var(--line); border-radius:24px; box-shadow:0 12px 28px rgba(33,37,41,.06); }}
    .hero {{ padding:24px; color:#fff; background:linear-gradient(135deg, rgba(17,94,89,.95), rgba(15,92,138,.92)); }}
    .hero a {{ display:inline-flex; align-items:center; justify-content:center; min-height:42px; padding:0 14px; border-radius:14px; text-decoration:none; font-weight:600; background:rgba(255,255,255,.14); color:#fff; border:1px solid rgba(255,255,255,.18); margin-right:10px; margin-top:14px; }}
    .grid {{ display:grid; grid-template-columns:340px 1fr; gap:18px; margin-top:22px; }}
    .panel {{ padding:20px; }}
    label {{ display:block; margin:12px 0 6px; color:var(--muted); font-size:13px; }}
    input, select, button {{ width:100%; border-radius:14px; border:1px solid var(--line); font:inherit; }}
    input, select {{ padding:12px 14px; background:#fff; }}
    button {{ padding:12px 14px; cursor:pointer; background:var(--accent); color:#fff; border:none; font-weight:600; }}
    button.secondary {{ background:var(--soft); color:var(--accent); border:1px solid rgba(17,94,89,.18); }}
    .actions {{ display:flex; gap:10px; margin-top:14px; }}
    .actions button {{ flex:1; }}
    .status,.box {{ margin-top:14px; padding:12px; border-radius:16px; background:#f3ece2; white-space:pre-wrap; font-size:13px; line-height:1.6; }}
    .list {{ display:grid; gap:12px; }}
    .card {{ border:1px solid var(--line); border-radius:18px; padding:14px; background:#fff; }}
    .badges {{ display:flex; gap:8px; flex-wrap:wrap; margin:8px 0; }}
    .badge {{ background:#eee5d8; border-radius:999px; padding:4px 10px; font-size:12px; color:var(--muted); }}
    .path {{ font-size:13px; line-height:1.6; color:var(--muted); word-break:break-all; }}
    @media (max-width:960px) {{ .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>节点列表</h1>
      <p>节点列表默认只分页显示目录节点，不再把整棵长目录树一次性铺开。可以按导入批次、关键词、层级筛选，再点开单个节点查看详情。</p>
      <a href="/workbench">返回统一工作台</a>
      <a href="/imports">返回导入批次</a>
    </section>
    <div class="grid">
      <aside class="panel">
        <label for="importId">导入批次</label>
        <input id="importId" value="{initial_import_id}" placeholder="例如 3" />
        <label for="queryInput">名称 / 路径搜索</label>
        <input id="queryInput" placeholder="例如 动漫 或 待整理" />
        <label for="depthInput">最大层级</label>
        <input id="depthInput" type="number" min="1" placeholder="不填表示全部" />
        <label for="limitInput">每页数量</label>
        <input id="limitInput" type="number" min="1" max="200" value="50" />
        <div class="actions">
          <button id="loadBtn">刷新列表</button>
          <button class="secondary" id="moreBtn">加载更多</button>
        </div>
        <div class="status" id="statusBox">先按条件筛选，再查看当前页节点。</div>
      </aside>
      <section class="panel">
        <div class="box" id="metaBox">节点会显示在这里。</div>
        <div class="list" id="nodeList"></div>
      </section>
    </div>
  </div>
  <script>
    const nodeList = document.getElementById('nodeList');
    const metaBox = document.getElementById('metaBox');
    const statusBox = document.getElementById('statusBox');
    const state = {{ offset: 0, total: 0 }};

    function buildParams() {{
      const params = new URLSearchParams();
      const importId = document.getElementById('importId').value.trim();
      const query = document.getElementById('queryInput').value.trim();
      const depth = document.getElementById('depthInput').value.trim();
      const limit = Number(document.getElementById('limitInput').value) || 50;
      if (importId) params.set('import_id', importId);
      if (query) params.set('query', query);
      if (depth) params.set('max_depth', depth);
      params.set('limit', String(limit));
      params.set('offset', String(state.offset));
      return params;
    }}

    function renderItems(items, append) {{
      if (!append) nodeList.innerHTML = '';
      if (!items.length && !append) {{
        nodeList.innerHTML = '<div class="box">当前条件下没有节点。</div>';
        return;
      }}
      items.forEach(item => {{
        const card = document.createElement('article');
        card.className = 'card';
        const tags = item.tags.length ? item.tags.map(tag => `<span class="badge">${{tag.tag}} ${{Number(tag.score).toFixed(2)}}</span>`).join('') : '<span class="badge">无标签</span>';
        card.innerHTML = `
          <div><strong>#${{item.id}} · ${{item.raw_name}}</strong></div>
          <div class="badges">
            <span class="badge">import #${{item.import_id}}</span>
            <span class="badge">depth ${{item.depth}}</span>
            <span class="badge">${{item.node_type}}</span>
            ${{tags}}
          </div>
          <div class="path">${{item.raw_path}}</div>
          <div class="actions">
            <button class="secondary" data-role="detail">查看 JSON 详情</button>
          </div>
        `;
        card.querySelector('[data-role="detail"]').addEventListener('click', () => {{
          window.open(`/nodes/data/${{item.id}}`, '_blank');
        }});
        nodeList.appendChild(card);
      }});
    }}

    async function loadNodes(append = false) {{
      if (!append) state.offset = 0;
      const response = await fetch(`/nodes/data?${{buildParams().toString()}}`);
      const body = await response.json();
      state.total = body.total;
      renderItems(body.items, append);
      metaBox.textContent = `当前显示 ${{append ? nodeList.children.length : body.items.length}} / ${{body.total}} 个节点。`;
      statusBox.textContent = body.items.length ? '节点列表已刷新。' : '当前条件下没有节点。';
    }}

    async function loadMore() {{
      state.offset += Number(document.getElementById('limitInput').value) || 50;
      await loadNodes(true);
    }}

    document.getElementById('loadBtn').addEventListener('click', () => loadNodes(false));
    document.getElementById('moreBtn').addEventListener('click', loadMore);
    loadNodes(false);
  </script>
</body>
</html>"""


@router.get("/nodes/data", response_model=NodePageResponse)
def list_nodes(
    import_id: int | None = None,
    query: str | None = None,
    max_depth: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> NodePageResponse:
    stmt = select(TreeNode).options(selectinload(TreeNode.tags)).order_by(TreeNode.id)
    if import_id is not None:
        stmt = stmt.where(TreeNode.import_id == import_id)
    if query:
        stmt = stmt.where((TreeNode.raw_name.contains(query)) | (TreeNode.raw_path.contains(query)))
    if max_depth is not None:
        stmt = stmt.where(TreeNode.depth <= max_depth)
    nodes = list(db.scalars(stmt).all())
    sliced = nodes[offset : offset + max(1, min(limit, 200))]
    return NodePageResponse(total=len(nodes), items=[NodeResponse.model_validate(node) for node in sliced])


@router.get("/nodes/data/{node_id}", response_model=NodeResponse)
def get_node(node_id: int, db: Session = Depends(get_db)) -> NodeResponse:
    node = db.scalar(select(TreeNode).where(TreeNode.id == node_id).options(selectinload(TreeNode.tags)))
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return NodeResponse.model_validate(node)
