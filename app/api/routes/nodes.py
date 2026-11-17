from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.models.tree import TreeNode
from app.schemas.node import NodePageResponse, NodeResponse

router = APIRouter(tags=["nodes"])


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
