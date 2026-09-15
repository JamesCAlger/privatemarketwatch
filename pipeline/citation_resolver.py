"""Resolve release/observation/field evidence without value-only source searches."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

from lxml import etree
from pipeline.programme.core import sha


def local(name):
    return str(name).rsplit("}",1)[-1].rsplit(":",1)[-1].lower()


def unavailable(reason):
    return dict(status="unavailable",reason=reason)


def locate_inline(tree,*,context_id,concept,report_date,unit=None):
    contexts=[node for node in tree.iter() if local(node.tag)=="context" and node.get("id")==context_id]
    if len(contexts)!=1: return unavailable("Source context is missing or ambiguous")
    dates=[(n.text or "").strip() for n in contexts[0].iter() if local(n.tag) in ("instant","enddate")]
    if dates!=[report_date]: return unavailable("Source context belongs to another economic period")
    facts=[node for node in tree.iter() if local(node.tag) in ("nonfraction","nonnumeric")
        and (node.get("contextRef") or node.get("contextref"))==context_id
        and (node.get("name") or "").lower()==concept.lower()
        and (unit is None or (node.get("unitRef") or node.get("unitref"))==unit)]
    if len(facts)!=1: return unavailable("Source field is missing or ambiguous")
    fact=facts[0]
    if any(local(parent.tag) in ('hidden','header') for parent in fact.iterancestors()):
        return unavailable("Source fact is not visible in the filing rendition")
    identity=fact.get("id")
    if identity and sum(node.get("id")==identity for node in tree.iter())!=1:
        return unavailable("Inline fact ID is ambiguous")
    return dict(status="direct",element=fact,inline_fact_id=identity,
        source_text=" ".join("".join(fact.itertext()).split()),context_id=context_id,concept=concept)


class Resolver:
    def __init__(self,release_id,documents,locators):
        self.release_id=release_id
        self.documents=documents
        self.locators=locators
        self.trees={}

    def resolve(self,release_id,row_id,field,*,observation,seen=None):
        if release_id!=self.release_id: return unavailable("Evidence belongs to another release")
        if observation.get("row_id")!=row_id: return unavailable("Observation identity does not match the requested row")
        key=(row_id,field)
        seen=set() if seen is None else set(seen)
        if key in seen: return unavailable("Cyclic evidence input")
        seen.add(key)
        item=self.locators.get(key)
        if not item: return unavailable("No verified field locator in this release")
        if item.get("status")=="unavailable": return unavailable(item.get("reason","Source unavailable"))
        if item.get("status")=="inferred":
            if field not in ("gics_sector","gics_sub_industry"): return unavailable("Inference does not support this field")
            if not all(item.get(k) for k in ("decision_id","model","taxonomy_sha256","input_text")):
                return unavailable("Inference decision lacks provenance")
            return {k:item[k] for k in ("status","decision_id","model","taxonomy_sha256","input_text")}
        if item.get("status")=="calculated":
            if field!="cost": return unavailable("Donor calculation does not support this field")
            if item.get("method")!="first_observed_fv_proxy" or not all(item.get(k) for k in
                ("donor_row_id","donor_release","donor_date","donor_observation")):
                return unavailable("Calculation lacks a complete donor reference")
            donor=item["donor_observation"]
            if donor.get("report_date")!=item["donor_date"]: return unavailable("Cost donor date changed")
            if (donor.get("cik"),donor.get("position_id"))!=(observation.get("cik"),observation.get("position_id")):
                return unavailable("Cost donor belongs to another position")
            return dict(status="calculated",method=item["method"],donor_row_id=item["donor_row_id"],
                donor_release=item["donor_release"],donor_date=item["donor_date"],
                input=self.resolve(item["donor_release"],item["donor_row_id"],"fair_value",observation=donor,seen=seen))
        if item.get("status")!="direct": return unavailable("Unsupported evidence status")
        if item.get("context_id")!=observation.get("src_context_id"):
            return unavailable("Source context does not match the selected observation")
        document=self.documents.get(item.get("document_id"))
        if not document: return unavailable("Source document unavailable")
        if document.get("accession_number")!=observation.get("accession_number"):
            return unavailable("Source is another filing or amendment")
        path=Path(document["path"])
        if not path.is_file() or sha(path)!=document.get("sha256"):
            return unavailable("Source document is missing or changed")
        from pipeline.bdc_filings import _match_concept
        if _match_concept(local(item.get("concept","")))!=field:
            return unavailable("Source concept does not support this field")
        if document["sha256"] not in self.trees:
            parser=etree.HTMLParser(no_network=True,huge_tree=True,recover=True)
            self.trees[document["sha256"]]=etree.parse(str(path),parser)
        resolved=locate_inline(self.trees[document["sha256"]],context_id=item["context_id"],
            concept=item["concept"],report_date=observation["report_date"],unit=item.get("unit"))
        if resolved["status"]!="direct": return resolved
        resolved.update(document_id=item["document_id"],source_sha256=document["sha256"],source_path=str(path))
        return resolved


def write_rendition(resolved,tree,output):
    """Passive full-filing rendition with a context/concept-specific highlight."""
    if resolved.get("status")!="direct": raise ValueError("Cannot render unavailable evidence")
    from copy import deepcopy
    from scripts.programme_closeout.citation_viewer import sanitize
    anchor="evidence-"+hashlib.sha256((resolved["source_sha256"]+resolved["context_id"]+resolved["concept"]).encode()).hexdigest()[:24]
    copy=deepcopy(tree)
    # HTML parsers retain colon-bearing inline tag names without registering
    # XML namespaces; a generated XPath would incorrectly interpret prefixes.
    path=[]
    node=resolved["element"]
    while node.getparent() is not None:
        path.append(node.getparent().index(node));node=node.getparent()
    target=copy.getroot()
    for index in reversed(path): target=target[index]
    target.set("id",anchor)
    sanitize(copy)
    if sum(node.get("id")==anchor for node in copy.iter())!=1:
        raise ValueError("Source highlight is unavailable after rendering")
    Path(output).write_bytes(etree.tostring(copy,encoding="utf-8",method="html"))
    return dict(path=Path(output).name,fragment=anchor,rendition_sha256=sha(output),
        source_sha256=resolved["source_sha256"],inline_fact_id=resolved["inline_fact_id"],
        source_text=resolved["source_text"],context_id=resolved["context_id"],concept=resolved["concept"])
