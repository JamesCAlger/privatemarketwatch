// Actual isolated Next export; local installed Playwright only.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require(process.env.PROGRAMME_PLAYWRIGHT||'C:/Users/alger/AppData/Local/npm-cache/_npx/9833c18b2d85bc59/node_modules/playwright');
const [siteArg,origin,outArg]=process.argv.slice(2);
if(!siteArg||!origin||!outArg||!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))throw Error('Usage: node check_history_browser.cjs SITE LOCAL_ORIGIN NEW_OUTPUT');
const site=path.resolve(siteArg),out=path.resolve(outArg),history=path.join(site,'data/holdings_history');
fs.mkdirSync(out,{recursive:false});
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const assert=(ok,msg)=>{if(!ok)throw Error(msg)};
const manifest=read(path.join(history,'manifest.json'));
const cases=new Map(),seenPosition=new Map();
let largest=null;
for(const cik of manifest.funds){
  const index=read(path.join(history,cik,'index.json'));
  for(const q of index.quarters){
    const payload=read(path.join(history,cik,q.quarter+'.json'));
    if(!largest||payload.rows.length>largest.count)largest={cik,quarter:q.quarter,count:payload.rows.length};
    const seenValue=new Map();
    for(const [i,row] of payload.rows.entries()){
      const c={cik,quarter:q.quarter,row_id:row.row_id,index:i,issuer:row.issuer_name,field:'fair_value',evidence:row.evidence?.fair_value};
      const take=(name,value=c)=>{if(!cases.has(name))cases.set(name,{name,...value})};
      if(c.evidence?.status==='direct'){
        take('direct');
        if(seenValue.has(row.fair_value))take('repeated_number');
        seenValue.set(row.fair_value,c);
        const prior=seenPosition.get(row.position_id);
        if(prior&&prior.quarter!==q.quarter)take('comparative_period');
        seenPosition.set(row.position_id,c);
      }else take('unavailable');
      if(['FX_unavailable','FX_stale','unit_unresolved'].includes(c.evidence?.reason)
          &&c.evidence.source_amount!=null)take('unavailable_usd');
      if(row.fair_value<0)take('negative_value');
      if(row.fair_value===0)take('zero_value');
      if(row.evidence?.cost?.status==='calculated')take('cost_donor',{...c,field:'cost',evidence:row.evidence.cost});
      if(row.evidence?.gics_sub_industry?.status==='inferred')take('inferred_sector',{...c,field:'gics_sub_industry',evidence:row.evidence.gics_sub_industry});
    }
  }
}
let browser;
(async()=>{
  browser=await chromium.launch({headless:true,executablePath:process.env.PROGRAMME_CHROMIUM||'C:/Users/alger/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe'});
  const context=await browser.newContext({viewport:{width:1440,height:960}}),errors=[],external=[],timings=[];
  await context.route('**/*',route=>{if(route.request().url().startsWith(origin+'/'))return route.continue();external.push(route.request().url());return route.abort()});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));
  const characteristics=read(path.join(site,'data/portfolio_characteristics.json'));
  const missingUsd=characteristics.missingFairValueCount||0;
  await page.goto(origin+'/');
  const missingNotice=page.getByText(/^USD fair value is unavailable for /);
  assert(await missingNotice.count()===(missingUsd>0?1:0),'Missing USD notice disagrees with exported count');
  if(missingUsd>0){
    assert((await missingNotice.innerText()).replace(/,/g,'').includes(String(missingUsd)+' positions.'),'Wrong unavailable USD count');
    await page.screenshot({path:path.join(out,'missing-usd-homepage.png'),fullPage:true});
  }
  const routeFor=cik=>fs.existsSync(path.join(site,'funds',cik+'.html'))?`/funds/${cik}.html`:`/funds/${cik}/`;
  async function open(c){
    await page.goto(origin+routeFor(c.cik));
    await page.getByRole('button',{name:'Holdings',exact:true}).click();
    const section=page.getByRole('region',{name:'Holdings history'});
    await section.getByRole('link',{name:'Download complete quarter'}).waitFor();
    await section.getByLabel('Reporting date').selectOption(c.quarter);
    await section.getByRole('link',{name:'Download complete quarter'}).waitFor();
    return section;
  }
  for(let repeat=0;repeat<6;repeat++)for(const c of cases.values()){
    const started=performance.now(),section=await open(c);
    // Pagination preserves observation order; verify the selected identity below.
    for(let i=0;i<Math.floor(c.index/100);i++)await section.getByRole('button',{name:'Next',exact:true}).click();
    const row=section.locator('tbody tr').nth(c.index%100);
    assert((await row.innerText()).includes(c.issuer),'Wrong visible issuer');
    const fieldIndex=['fair_value','cost','interest_rate','maturity_date','gics_sub_industry'].indexOf(c.field);
    await row.getByRole('button').nth(fieldIndex).focus();await page.keyboard.press('Enter');
    const panel=section.getByRole('complementary',{name:'Field evidence'});
    await panel.locator('summary').click();
    assert((await panel.innerText()).includes(c.row_id),'Wrong observation evidence');
    if(c.name==='unavailable_usd'){
      assert((await panel.innerText()).includes('Source amount: '+c.evidence.source_currency+' '+c.evidence.source_amount),'Original foreign amount is absent');
      assert(!(await row.getByRole('button').first().innerText()).includes('$'),'Unavailable USD appears as a dollar amount');
    }
    let citation=c.evidence;
    if(citation?.status==='calculated'&&citation.input?.status==='direct')citation=citation.input;
    if(citation?.status==='direct'){
      const link=panel.getByRole('link').first();
      assert(await link.getAttribute('href')===citation.href,'Wrong source path');
      const source=await context.newPage();await source.goto(origin+citation.href);
      const fragment=citation.href.split('#')[1],target=source.locator('#'+fragment);
      assert(await target.count()===1,'Ambiguous source anchor');
      assert((await target.innerText()).replace(/\s+/g,' ').trim()===citation.source_text,'Wrong source text');
      assert(await source.locator('script,iframe,object,embed').count()===0,'Active filing content');
      assert(await target.evaluate(e=>{const r=e.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight&&e.matches(':target')}),'Source anchor is not in view');
      await source.close();
    }else assert(await panel.getByRole('link').count()===0,'Unverified direct link');
    timings.push({case:c.name,repeat,ms:performance.now()-started});
  }
  const section=await open(largest);
  await section.getByRole('searchbox').fill('no-match-unlikely-observation-12345');
  assert(await section.locator('tbody tr').count()===0,'Search did not narrow history');
  await section.getByRole('searchbox').fill('');
  assert(await section.locator('tbody tr').count()===Math.min(100,largest.count),'Search reset lost rows');
  await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Outer mobile overflow');
  await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
  // Exercise absent service outcomes and hostile/stale payloads through the
  // compiled component. These fixtures measure UI behavior, never data coverage.
  const synthetic=[];
  const fixtureCik=largest.cik,fixtureQuarter=largest.quarter,fixtureBase=`/data/holdings_history/${fixtureCik}`;
  const template=read(path.join(history,fixtureCik,fixtureQuarter+'.json'));
  let fixture;
  await context.route(origin+fixtureBase+'/**',route=>{
    const url=new URL(route.request().url());
    if(url.pathname===fixtureBase+'/index.json')return route.fulfill({json:fixture.index});
    if(url.pathname===fixtureBase+'/'+fixtureQuarter+'.json')return route.fulfill({body:fixture.bytes,contentType:'application/json'});
    return route.continue();
  });
  const fixtureRelease='browser-control-release',fixtureSource='a'.repeat(64),fixtureAccession='0000000123-26-000001';
  const direct={status:'direct',release_id:fixtureRelease,row_id:'browser-row',field:'fair_value',
    accession_number:fixtureAccession,source_sha256:fixtureSource,source_text:'0',
    href:fixtureBase+'/sources/'+fixtureAccession+'-'+fixtureSource.slice(0,16)+'.html#evidence-'+'b'.repeat(24)};
  const controls=[
    {name:'inferred_sector_fixture',field:4,evidenceField:'gics_sub_industry',evidence:{status:'inferred',decision_id:'fixture-decision',
      model:'fixture-model-no-service-call',input_text:'Fixture issuer description',taxonomy_sha256:'c'.repeat(64)},expected:'Inferred classification'},
    {name:'unavailable_fixture',evidence:{status:'unavailable',reason:'Fixture source unavailable'},expected:'Source evidence unavailable'},
    {name:'missing_fx_fixture',evidence:{status:'unavailable',reason:'FX_unavailable',source_amount:'80',source_currency:'GBP'},
      expected:'A usable USD conversion is unavailable.',also:['Source amount: GBP 80.']},
    {name:'stale_fx_fixture',evidence:{status:'unavailable',reason:'FX_stale',source_amount:'-80',source_currency:'GBP'},
      expected:'No FX quote within seven days',also:['Source amount: GBP -80.']},
    {name:'converted_fx_fixture',evidence:{status:'calculated',method:'report_date_reference_conversion',
      calculation:{source_value:'80',resolved_currency:'GBP',conversion:{quote_date:'2026-03-30'}}},
      expected:'Calculated USD fair value',also:['Source amount: GBP 80.','FRED H.10 observation: 2026-03-30.']},
    {name:'reviewed_usd_fixture',evidence:{status:'calculated',method:'already_USD',
      calculation:{source_value:'0',resolved_currency:'USD'}},expected:'Reviewed USD denomination',also:['Source amount: USD 0.']},
    {name:'amended_accession_rejected',evidence:{...direct,accession_number:'0000000123-26-000002'},expected:'Source evidence unavailable'},
    {name:'different_release_rejected',evidence:{...direct,release_id:'different-release'},expected:'Source evidence unavailable'},
    {name:'different_row_rejected',evidence:{...direct,row_id:'different-row'},expected:'Source evidence unavailable'},
    {name:'source_hash_mismatch_rejected',evidence:{...direct,source_sha256:'d'.repeat(64)},expected:'Source evidence unavailable'},
    {name:'external_link_rejected',evidence:{...direct,href:'https://example.invalid/source'},expected:'Source evidence unavailable'},
    {name:'tampered_quarter_hash_rejected',tamper:true},
    {name:'payload_release_mismatch_rejected',payloadRelease:'other-release'},
  ];
  for(const c of controls){
    const field=c.evidenceField||'fair_value';
    const row={...template.rows[0],row_id:'browser-row',position_id:'browser-position',entity_id:'browser-entity',
      issuer_name:'Browser control issuer',instrument_description:'Synthetic browser control',accession_number:fixtureAccession,
      fair_value:0,gics_sub_industry:'Application Software',evidence:{[field]:{
        release_id:fixtureRelease,row_id:'browser-row',field,...c.evidence}}};
    const payload={...template,release_id:c.payloadRelease||fixtureRelease,rows:[row],citations:{}};
    const bytes=Buffer.from(JSON.stringify(payload)),digest=crypto.createHash('sha256').update(bytes).digest('hex');
    fixture={bytes,index:{cik:fixtureCik,release_id:fixtureRelease,quarters:[{quarter:fixtureQuarter,rows:1,
      path:fixtureQuarter+'.json',sha256:c.tamper?'0'.repeat(64):digest}]}};
    await page.goto(origin+routeFor(fixtureCik));
    await page.getByRole('button',{name:'Holdings',exact:true}).click();
    const controlSection=page.getByRole('region',{name:'Holdings history'});
    if(c.tamper||c.payloadRelease){
      await controlSection.getByRole('status').filter({hasText:'The quarter does not match this release.'}).waitFor();
      assert(await controlSection.locator('tbody tr').count()===0,'Invalid quarter displayed rows');
      assert(await controlSection.getByRole('link',{name:'Download complete quarter'}).count()===0,'Invalid quarter exposed download');
    }else{
      await controlSection.getByRole('link',{name:'Download complete quarter'}).waitFor();
      await controlSection.locator('tbody tr').first().getByRole('button').nth(c.field||0).click();
      const panel=controlSection.getByRole('complementary',{name:'Field evidence'});
      assert((await panel.innerText()).includes(c.expected),'Wrong fixture evidence state: '+c.name);
      for(const text of c.also||[])assert((await panel.innerText()).includes(text),'Missing monetary evidence: '+c.name+' '+text);
      assert(await panel.getByRole('link').count()===0,'Fixture exposed unverified source link: '+c.name);
      if(c.name==='inferred_sector_fixture'){
        assert((await panel.innerText()).includes('fixture-model-no-service-call'),'Inference provenance absent');
        await page.screenshot({path:path.join(out,'inferred-fixture.png'),fullPage:true});
      }
    }
    synthetic.push({name:c.name,status:'PASS',fixture_sha256:digest,role:'Synthetic browser control; not production data evidence'});
  }
  const sorted=timings.map(t=>t.ms).sort((a,b)=>a-b),p95=sorted[Math.ceil(sorted.length*.95)-1];
  const result={status:errors.length||external.length||p95>5000?'FAIL':'PASS',release_id:manifest.release_id,
    browser:browser.version(),workload:'Local static Next export, desktop1440x960/mobile390x844;6 sequential visits per observed scenario including source navigation;warm process, no remote-device claim',
    cases:[...cases.values()],synthetic_controls:synthetic,homepage_missing_usd_count:missingUsd,largest,timings,p95_ms:p95,errors,external_requests:external,
    unobserved:['direct','repeated_number','comparative_period','cost_donor','inferred_sector'].filter(n=>!cases.has(n)),
    limitations:['Amendment and inferred-sector fixtures exercise the compiled UI; they do not establish their frequency or correctness in published holdings.'],adoption:'not_adopted'};
  fs.writeFileSync(path.join(out,'browser_result.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({status:result.status,cases:cases.size,p95_ms:p95,unobserved:result.unobserved}));
  await browser.close();if(result.status!=='PASS')process.exitCode=1;
})().catch(async e=>{fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(e),stack:e.stack},null,2));console.error(e);if(browser)await browser.close();process.exitCode=1});
