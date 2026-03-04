from pydantic import BaseModel


class DAGNode(BaseModel):
    id: str
    type: str
    data: dict
    position: dict


class DAGEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    animated: bool


class DAGResponse(BaseModel):
    nodes: list[DAGNode]
    edges: list[DAGEdge]
