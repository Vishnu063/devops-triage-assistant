/* Real desktop/mobile first-use checks. Run with Playwright installed separately. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const {mkdtempSync,rmSync,mkdirSync,readFileSync}=require('node:fs');
const {tmpdir}=require('node:os');
const {join}=require('node:path');
const assert=require('node:assert/strict');

(async()=>{
 const folder=mkdtempSync(join(tmpdir(),'triage-browser-'));
 const port=18769,url='http://127.0.0.1:'+port;
 let service,browser;
 const artifacts=process.env.TRIAGE_BROWSER_ARTIFACTS||join(folder,'artifacts');
 mkdirSync(artifacts,{recursive:true});
 try{
  browser=await chromium.launch({headless:true});
  service=spawn('python',['-m','triage.cli','--config',join(folder,'connections.json'),'--state-dir',join(folder,'state'),'web','--port',String(port)],{stdio:'ignore'});
  let ready=false;
  for(let i=0;i<50;i++){
   try{if((await fetch(url)).ok){ready=true;break}}catch{}
   await new Promise(resolve=>setTimeout(resolve,200));
  }
  assert(ready,'Dashboard did not start');
  const page=await browser.newPage({viewport:{width:1365,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const text=async(id,value)=>page.waitForFunction(({id,value})=>document.getElementById(id).textContent.includes(value),{id,value});
  await page.goto(url);
  await page.waitForFunction(()=>document.querySelector('#tool').options.length===61);
  await page.getByRole('button',{name:'Docker out of memory',exact:true}).click();
  await text('report-headline','Sample incident');
  await page.getByRole('button',{name:'Likely cause?',exact:true}).click();
  await text('chat-log','hypotheses, not confirmed');
  assert.equal(await page.locator('#repair-actions button').count(),0);
  assert(await page.locator('#ai-explain').isDisabled());
  await page.screenshot({path:join(artifacts,'desktop-demo.png'),fullPage:true});
  await page.getByRole('button',{name:'Kubernetes image pull',exact:true}).click();
  await text('findings','Image pull failure');
  await page.getByRole('button',{name:'What next?',exact:true}).click();
  await text('chat-log','imagePullSecret');
  await page.getByRole('button',{name:'Linux disk full',exact:true}).click();
  await text('disk','96%');
  await page.getByRole('button',{name:'Leave sample mode',exact:true}).click();
  assert(await page.locator('#chat-panel').isHidden());
  await page.locator('#filter').fill('docker');
  await text('filter-status','1 matching integrations.');
  await page.locator('#tool').selectOption('docker');
  await page.getByRole('button',{name:'Run live checks',exact:true}).click();
  await text('errors','No configuration for docker');
  await page.getByRole('button',{name:'Connection wizard',exact:true}).click();
  await page.locator('#connection-fields input').first().waitFor();
  await page.getByRole('button',{name:'Close',exact:true}).click();
  await page.locator('#filter').fill('');await page.locator('#tool').selectOption('linux');
  await page.getByRole('button',{name:'Run live checks',exact:true}).click();
  await text('report-mode','LIVE EVIDENCE SAMPLE');
  await page.getByRole('button',{name:'Application healthy?',exact:true}).click();
  await text('chat-log','not verified');
  const downloadEvent=page.waitForEvent('download');
  await page.getByRole('button',{name:'Download filtered summary',exact:true}).click();
  const download=await downloadEvent;const file=join(folder,'summary.json');await download.saveAs(file);
  const summary=JSON.parse(readFileSync(file,'utf8'));assert(!('target' in summary));assert('evidence' in summary);
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'Docker out of memory',exact:true}).click();
  await text('report-headline','Sample incident');
  await page.screenshot({path:join(artifacts,'mobile-demo.png'),fullPage:true});
  assert(!await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),'Mobile horizontal overflow');
  assert.deepEqual(errors,[]);
  console.log('PASS: desktop/mobile samples, questions, live Linux checks, setup errors, wizard, search and summary download.');
 }finally{
  if(browser)await browser.close();
  if(service&&service.exitCode===null){service.kill();await new Promise(resolve=>service.once('close',resolve));}
  rmSync(folder,{recursive:true,force:true});
 }
})().catch(e=>{console.error(e);process.exitCode=1});
