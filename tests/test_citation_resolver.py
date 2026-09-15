from copy import deepcopy

from lxml import etree

from pipeline.citation_resolver import Resolver,write_rendition
from pipeline.programme.core import sha


def fixture(tmp_path):
    path=tmp_path/"filing.html"
    path.write_text('''<html><head></head><body><script>alert("bad")</script>
      <xbrli:context id="c1"><xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period></xbrli:context>
      <xbrli:context id="prior"><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
      <table><tr><td>Acme</td><td><ix:nonfraction id="current-fv" name="us:InvestmentOwnedAtFairValue"
      contextRef="c1" unitRef="USD">100</ix:nonfraction></td></tr>
      <tr><td>Comparative Acme</td><td><ix:nonfraction id="prior-fv" name="us:InvestmentOwnedAtFairValue"
      contextRef="prior" unitRef="USD">100</ix:nonfraction></td></tr></table></body></html>''')
    observation=dict(row_id="R1",cik="123",position_id="P1",src_context_id="c1",accession_number="original",report_date="2026-03-31")
    documents={"D1":dict(path=str(path),sha256=sha(path),accession_number="original")}
    locators={("R1","fair_value"):dict(status="direct",document_id="D1",context_id="c1",concept="us:InvestmentOwnedAtFairValue",unit="USD")}
    return Resolver("release",documents,locators),observation,path


def test_repeated_numbers_resolve_by_context_concept_period_and_rendition_is_passive(tmp_path):
    resolver,observation,path=fixture(tmp_path)
    result=resolver.resolve("release","R1","fair_value",observation=observation)
    assert result["status"]=="direct" and result["inline_fact_id"]=="current-fv"
    target=tmp_path/"rendition.html"
    record=write_rendition(result,resolver.trees[sha(path)],target)
    rendered=etree.parse(str(target),etree.HTMLParser())
    assert not rendered.xpath("//script")
    assert len(rendered.xpath('//*[@id="'+record["fragment"]+'"]'))==1
    # Rendering must not destroy the source context for subsequent resolutions.
    assert resolver.resolve("release","R1","fair_value",observation=observation)["status"]=="direct"


def test_comparative_date_amendment_and_mismatched_row_never_link_nearest_number(tmp_path):
    resolver,observation,_=fixture(tmp_path)
    for change in (dict(report_date="2025-12-31"),dict(accession_number="amendment"),dict(row_id="different")):
        assert resolver.resolve("release","R1","fair_value",observation=dict(observation,**change))["status"]=="unavailable"
    assert resolver.resolve("older-release","R1","fair_value",observation=observation)["status"]=="unavailable"


def test_changed_source_and_ambiguous_fact_are_unavailable(tmp_path):
    resolver,observation,path=fixture(tmp_path)
    path.write_text(path.read_text().replace("<table>","<table><ix:nonfraction name='us:InvestmentOwnedAtFairValue' contextRef='c1' unitRef='USD'>100</ix:nonfraction>"))
    assert resolver.resolve("release","R1","fair_value",observation=observation)["status"]=="unavailable"
    resolver.documents["D1"]["sha256"]=sha(path)
    assert resolver.resolve("release","R1","fair_value",observation=observation)["reason"]=="Source field is missing or ambiguous"


def test_inferred_sector_and_cost_donor_are_not_presented_as_direct_filing_facts(tmp_path):
    resolver,observation,_=fixture(tmp_path)
    resolver.locators[("R1","gics_sector")]=dict(status="inferred",decision_id="D",model="M",taxonomy_sha256="T",input_text="Acme")
    assert resolver.resolve("release","R1","gics_sector",observation=observation)["status"]=="inferred"
    borrower=dict(observation,row_id="R2",report_date="2026-06-30")
    resolver.locators[("R2","cost")]=dict(status="calculated",method="first_observed_fv_proxy",donor_row_id="R1",
        donor_release="release",donor_date="2026-03-31",donor_observation=observation)
    result=resolver.resolve("release","R2","cost",observation=borrower)
    assert result["status"]=="calculated" and result["input"]["status"]=="direct"
    assert resolver.resolve("release","R2","cost",observation=dict(borrower,position_id="Other"))["status"]=="unavailable"
