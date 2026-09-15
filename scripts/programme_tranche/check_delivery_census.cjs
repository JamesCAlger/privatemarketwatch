// Exhaustive DOM check of already published anchors; no HTML roster extraction.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require(process.env.PROGRAMME_PLAYWRIGHT||'C:/Users/alger/AppData/Local/npm-cache/_npx/9833c18b2d85bc59/node_modules/playwright');
const [siteArg,origin,coverageArg,outArg]=process.argv.slice(2);
if(!siteArg||!coverageArg||!outArg||!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))throw Error('Usage: SITE LOCAL_ORIGIN COVERAGE_DIR NEW_OUTPUT');
const site=path.resolve(siteArg),coverage=path.resolve(coverageArg),out=path.resolve(outArg);
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const check=(ok,message)=>{if(!ok)throw Error(message)};
const inventory=read(path.join(coverage,'browser_requests/manifest.json'));
const measurement=read(path.join(coverage,'result.json'));
check(inventory.release_id===measurement.release_id,'Coverage release mismatch');
check(measurement.metadata_errors===0,'Repair failed metadata checks before the browser census');
check(hash(path.join(coverage,'browser_requests/manifest.json'))===measurement.browser_request_manifest_sha256,'Browser inventory changed');
check(read(path.join(site,'data/holdings_history/manifest.json')).release_id===measurement.release_id,'Site release mismatch');
fs.mkdirSync(out,{recursive:false});
let browser;
(async()=>{
  browser=await chromium.launch({headless:true,executablePath:process.env.PROGRAMME_CHROMIUM||'C:/Users/alger/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe'});
  const context=await browser.newContext(),external=[],errors=[],documents=[];
  await context.route('**/*',route=>{
    if(route.request().url().startsWith(origin+'/'))return route.continue();
    external.push(route.request().url());return route.abort();
  });
  const page=await context.newPage();
  page.setDefaultTimeout(0);page.setDefaultNavigationTimeout(0);
  let checked=0,checkedReferences=0;
  for(const doc of inventory.documents){
    const requestPath=path.resolve(coverage,'browser_requests',doc.path);
    check(path.dirname(requestPath)===path.join(coverage,'browser_requests'),'Unsafe request path');
    check(hash(requestPath)===doc.sha256,'Browser request changed');
    check(/^\/data\/holdings_history\/[0-9]{10}\/sources\/[0-9-]+-[a-f0-9]{16}\.html$/.test(doc.href),'Unsafe source route');
    const rendition=path.join(site,doc.href.slice(1));
    check(hash(rendition)===doc.rendition_sha256,'Published rendition changed');
    const targets=read(requestPath);
    check(targets.every(t=>Number.isSafeInteger(t.reference_count)&&t.reference_count>0),'Invalid link reference population');
    const response=await page.goto(origin+doc.href);
    check(response?.ok(),'Source page failed');
    const result=await page.evaluate(targets=>{
      const ids=new Map(),failures=[];
      const activeNodes=document.querySelectorAll('script,iframe,object,embed,form').length;
      for(const node of document.querySelectorAll('[id]')){
        const entry=ids.get(node.id)||[];entry.push(node);ids.set(node.id,entry);
      }
      const normalize=value=>value.replace(/\s+/g,' ').trim();
      for(const target of targets){
        const fragment=target.href.split('#')[1],nodes=ids.get(fragment)||[];
        const reasons=[];
        if(activeNodes)reasons.push('active_source_content');
        if(nodes.length!==1)reasons.push('missing_or_ambiguous_anchor');
        else{
          const node=nodes[0],rect=node.getBoundingClientRect();
          if(normalize(node.textContent||'')!==normalize(target.source_text))reasons.push('wrong_source_text');
          if(!rect.width||!rect.height||getComputedStyle(node).visibility!=='visible')reasons.push('invisible_anchor');
          if(target.locator_kind!=='admitted_html_bridge'){
            if(node.getAttribute('contextref')!==target.context_id)reasons.push('wrong_context');
            const concept=(node.getAttribute('name')||'').split(':').at(-1).toLowerCase();
            if(concept!==target.concept)reasons.push('wrong_concept');
          }
        }
        if(reasons.length)failures.push({href:target.href,reasons,reference_count:target.reference_count});
      }
      return {checked:targets.length,failures,references:targets.reduce((sum,t)=>sum+t.reference_count,0)};
    },targets);
    checked+=result.checked;
    checkedReferences+=result.references;
    errors.push(...result.failures);
    documents.push({href:doc.href,checked:result.checked,failures:result.failures.length,rendition_sha256:doc.rendition_sha256});
    if(documents.length%25===0)process.stdout.write('Browser census: '+documents.length+' documents; '+checked+' anchors\n');
  }
  check(checkedReferences===measurement.direct_field_link_references,'Browser census omitted field link references');
  const result={status:errors.length||external.length||measurement.metadata_errors?'FAIL':'PASS',
    release_id:measurement.release_id,coverage_sha256:hash(path.join(coverage,'result.json')),
    request_manifest_sha256:hash(path.join(coverage,'browser_requests/manifest.json')),
    checked_unique_anchor_expectations:checked,checked_field_link_references:checkedReferences,documents,errors,external_requests:external,
    misleading_links:errors.reduce((sum,e)=>sum+e.reference_count,0),
    scope:'Complete published direct/donor locator census; source accuracy remains the independent field assessment. Performance is measured by the separate interaction harness.',
    browser:browser.version(),code_sha256:hash(__filename)};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2)+'\n');
  process.stdout.write(result.status+': '+checked+' anchor expectations\n');
  if(result.status!=='PASS')process.exitCode=1;
})().catch(error=>{
  fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({status:'FAIL',error:String(error.stack||error)},null,2)+'\n');
  process.exitCode=1;
}).finally(async()=>{if(browser)await browser.close()});
