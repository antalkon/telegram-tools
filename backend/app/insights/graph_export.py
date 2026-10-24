"""Graphs for Gephi, Maltego, yEd and friends: GEXF 1.3 and GraphML from the panel's {nodes, links}."""

from typing import Any
from xml.sax.saxutils import escape, quoteattr

NODE_ATTRS = [("type", "string"), ("peer_id", "long"), ("value", "double"), ("source_type", "string"), ("sources", "integer")]
EDGE_ATTRS = [("kind", "string"), ("weight", "double")]
MEDIA = {"gexf": "application/gexf+xml", "graphml": "application/graphml+xml"}


def _val(v: Any) -> str:
    return quoteattr("" if v is None else str(v))


def to_gexf(data: dict[str, Any], title: str = "TG Toolkit") -> bytes:
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gexf xmlns="http://gexf.net/1.3" version="1.3">',
           f'<meta><creator>TG Toolkit</creator><description>{escape(title)}</description></meta>',
           '<graph defaultedgetype="undirected" mode="static">',
           '<attributes class="node">',
           *(f'<attribute id="{i}" title="{k}" type="{t}"/>' for i, (k, t) in enumerate(NODE_ATTRS)),
           '</attributes><attributes class="edge">',
           *(f'<attribute id="{i}" title="{k}" type="{t}"/>' for i, (k, t) in enumerate(EDGE_ATTRS[:1])),
           '</attributes><nodes>']
    for n in data["nodes"]:
        attrs = "".join(f'<attvalue for="{i}" value={_val(n.get(k))}/>' for i, (k, _) in enumerate(NODE_ATTRS) if n.get(k) is not None)
        out.append(f'<node id={_val(n["id"])} label={_val(n.get("label"))}><attvalues>{attrs}</attvalues></node>')
    out.append("</nodes><edges>")
    for i, e in enumerate(data["links"]):
        out.append(f'<edge id="{i}" source={_val(e["source"])} target={_val(e["target"])} weight={_val(e.get("weight") or 1)}>'
                   f'<attvalues><attvalue for="0" value={_val(e.get("kind"))}/></attvalues></edge>')
    out.append("</edges></graph></gexf>")
    return "\n".join(out).encode()


def to_graphml(data: dict[str, Any]) -> bytes:
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
           '<key id="label" for="node" attr.name="label" attr.type="string"/>',
           *(f'<key id="n_{k}" for="node" attr.name="{k}" attr.type="{t}"/>' for k, t in NODE_ATTRS),
           *(f'<key id="e_{k}" for="edge" attr.name="{k}" attr.type="{t}"/>' for k, t in EDGE_ATTRS),
           '<graph id="G" edgedefault="undirected">']
    for n in data["nodes"]:
        attrs = "".join(f'<data key="n_{k}">{escape(str(n[k]))}</data>' for k, _ in NODE_ATTRS if n.get(k) is not None)
        out.append(f'<node id={_val(n["id"])}><data key="label">{escape(str(n.get("label") or ""))}</data>{attrs}</node>')
    for e in data["links"]:
        attrs = "".join(f'<data key="e_{k}">{escape(str(e[k]))}</data>' for k, _ in EDGE_ATTRS if e.get(k) is not None)
        out.append(f'<edge source={_val(e["source"])} target={_val(e["target"])}>{attrs}</edge>')
    out.append("</graph></graphml>")
    return "\n".join(out).encode()


def render(data: dict[str, Any], fmt: str, title: str) -> bytes:
    return to_gexf(data, title) if fmt == "gexf" else to_graphml(data)
