// Offline browser proof; Playwright must already be installed locally.
const fs=require('node:fs'), path=require('node:path'), {pathToFileURL}=require('node:url');
const {chromium}=require(process.env.PROGRAMME_PLAYWRIGHT || 'C:/Users/alger/AppData/Local/npm-cache/_npx/9833c18b2d85bc59/node_modules/playwright');
const dir=path.join(process.cwd(),'docs/production_stack/programme_closeout_evidence_2026-09-09/viewer');
const scratch=path.join(process.cwd(),'scratch/2026-09-09_programme_closeout');fs.mkdirSync(scratch,{recursive:true});
const assert=(ok,msg)=>{if(!ok)throw Error(msg)};
let browser;
(async()=>{
 browser=await chromium.launch({headless:true,executablePath:process.env.PROGRAMME_CHROMIUM || 'C:/Users/alger/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe'});const context=await browser.newContext({viewport:{width:1440,height:960}});
 const page=await context.newPage(), errors=[],external=[];page.on('pageerror',e=>errors.push(String(e)));
 await context.route(/^https?:/,route=>{external.push(route.request().url());return route.abort()});
 const cases=JSON.parse(fs.readFileSync(path.join(dir,'citations.json'),'utf8'));
 await page.goto(pathToFileURL(path.join(dir,'index.html')).href);
 assert(await page.locator('#cases button').count()===cases.length,'Example inventory');
 const navigation=[];
 for(let repeat=0;repeat<6;repeat++)for(const c of cases){
   const started=performance.now();await page.locator(`button[data-id="${c.id}"]`).click();
   assert(await page.locator('#category').innerText()===c.category,'Evidence category');
   if(c.rendition){
     const frame=page.frameLocator('iframe'),target=frame.locator('#'+c.fragment);
     await target.waitFor({state:'visible'});
     assert((await target.innerText()).replace(/\s+/g,' ').trim()===c.cell_text,'Wrong highlighted text '+c.id);
     assert(await target.getAttribute('data-citation')===c.id,'Wrong citation identity');
     assert((await page.locator('#meta').innerText()).includes(c.source_sha256),'Missing source identity');
     assert((await page.locator('#links a').getAttribute('href'))===c.rendition+'#'+c.fragment,'New-tab target');
     const framePage=page.frames().find(f=>f.url().includes(c.rendition));
     // Host-side polling also works with a scripts-disabled filing sandbox.
     const readyDeadline=Date.now()+30000;
     while(await framePage.evaluate(()=>document.readyState)!=='complete'){
       assert(Date.now()<readyDeadline,'Filing load deadline '+c.id);
       await new Promise(resolve=>setTimeout(resolve,50));
     }
     assert(await target.evaluate(el=>{const r=el.getBoundingClientRect();return r.bottom>0 && r.top<innerHeight && el.matches(':target')}),'Highlight is not scrolled into view '+c.id);
     assert(await framePage.locator('script,iframe,object,embed').count()===0,'Active filing content');
     navigation.push({id:c.id,repeat,ms:performance.now()-started});
   }else {
     assert(await page.locator('iframe').count()===0,'Misleading direct source for '+c.id);
     if(c.inputs)assert(await page.locator('#links a[data-input]').count()===c.inputs.length,'Missing calculation or inference inputs');
   }
 }
 await page.locator('button[data-id="derived"]').click();
 await page.locator('#links a[data-input="forterro-sek-fv"]').click();
 await page.frameLocator('iframe').locator('#cite-forterro-sek-fv').waitFor();
 await page.locator('button[data-id="inferred"]').click();
 assert((await page.locator('#display').innerText()).includes('DEV-GICS-FORTERRO-20260909'),'Missing inference decision');
 await page.locator('#links a[data-input="forterro-fv"]').click();
 await page.frameLocator('iframe').locator('#cite-forterro-fv').waitFor();
 await page.locator('button[data-id="riser"]').focus();await page.keyboard.press('Enter');
 await page.frameLocator('iframe').locator('#cite-riser').waitFor();
 await page.screenshot({path:path.join(scratch,'viewer-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Outer mobile overflow');
 await page.screenshot({path:path.join(scratch,'viewer-mobile.png'),fullPage:true});
 assert(errors.length===0,'Browser errors: '+errors);assert(external.length===0,'External requests: '+external);
 const sorted=navigation.map(x=>x.ms).sort((a,b)=>a-b),quant=p=>sorted[Math.ceil(sorted.length*p)-1];
 const result={status:'pass',browser:browser.version(),platform:process.platform,viewport:'1440x960 desktop / 390x844 mobile',
    workload:'Local file; one browser context; first visits plus warm repetitions. No remote network or cold-device claim.',
    real_cases:cases.filter(c=>c.rendition).length,indirect_cases:4,navigations:navigation.length,p50_ms:quant(.5),p95_ms:quant(.95),max_ms:sorted.at(-1),
    observations:navigation,external_requests:external,errors,keyboard:true,mobile_outer_overflow:false};
 fs.writeFileSync(path.join(dir,'browser_result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,navigations:result.navigations,p50_ms:result.p50_ms,p95_ms:result.p95_ms}));
 await browser.close();
})().catch(async e=>{console.error(e);if(browser)await browser.close();process.exit(1)});
