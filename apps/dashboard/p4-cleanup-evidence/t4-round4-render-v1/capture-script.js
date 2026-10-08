async page => {
  const root='/home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/apps/dashboard/p4-cleanup-evidence/t4-round4-render-v1';
  const axe='/home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/apps/dashboard/node_modules/axe-core/axe.min.js';
  const rows=[],pageErrors=[],apiFailures=[],consoleErrors=[];
  const onError=error=>pageErrors.push(error.message);
  const onConsole=message=>{if(message.type()==='error')consoleErrors.push(message.text().replace(/https?:\/\/[^\s)]+/g,'[redacted-url]'));};
  const onResponse=response=>{const url=new URL(response.url());if(url.origin==='http://localhost:3241'&&url.pathname.startsWith('/api/')&&response.status()>=400)apiFailures.push({path:url.pathname,status:response.status()});};
  page.on('pageerror',onError);page.on('response',onResponse);page.on('console',onConsole);
  const capture=async(name,width,path,extra={})=>{
    await page.getByRole('main').waitFor();
    await page.waitForFunction(()=>!document.querySelector('main [aria-busy="true"]')&&!document.querySelector('main').innerText.includes('읽는 중입니다.'),{},{timeout:15000});
    await page.evaluate(async()=>await document.fonts.ready);
    await page.addScriptTag({path:axe});
    const state=await page.evaluate(async()=>{
      const result=await window.axe.run();
      return {h1Count:document.querySelectorAll('h1').length,headings:[...document.querySelectorAll('main h1,main h2')].map(e=>({tag:e.tagName,text:e.innerText})),
        mainText:document.querySelector('main').innerText,viewportWidth:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,
        a11y:result.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length})),
        reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches};
    });
    await page.screenshot({path:`${root}/${name}-${width}.png`,fullPage:true,animations:'disabled'});
    const row={name,width,path,settled:true,...state,...extra};
    if(name==='more-after'){
      row.retiredCopyPresent=/비행 임무|장비 연결|복구처럼/.test(state.mainText);
      row.supportLink=await page.getByRole('main').getByRole('link').evaluateAll(es=>es.map(e=>({href:e.getAttribute('href'),text:e.innerText})));
    }
    if(name==='actual-analysis')row.mainAlerts=await page.getByRole('main').getByRole('alert').count();
    rows.push(row);
    if(row.h1Count!==1||row.documentWidth>row.viewportWidth+1)throw new Error(`Heading/overflow failure: ${name}-${width}`);
    if(name.startsWith('denied')&&state.mainText.includes('E2E 현장 작업공간'))throw new Error('Tenant name disclosure');
  };
  for(const [width,height]of[[390,844],[768,1024],[1440,900]]){
    await page.setViewportSize({width,height});await page.emulateMedia({colorScheme:'light',reducedMotion:'reduce'});
    await page.goto('http://localhost:3241/sites/e2e-site-workspace/spatial-assets');
    await page.getByRole('heading',{level:2,name:'현장 공간 자산',exact:true}).waitFor();
    await page.reload();
    await page.getByText('E2E 현장 작업공간',{exact:true}).waitFor();
    await capture('actual-assets',width,'/sites/e2e-site-workspace/spatial-assets',{arrival:'direct URL followed by reload'});
    await page.goto('http://localhost:3241/more');
    await page.getByText('운영 지원 범위와 아직 실장비 검증 전인 기능을 안내합니다.',{exact:true}).waitFor();
    await capture('more-after',width,'/more');
    await page.goto('http://localhost:3241/sites/e2e-site-workspace?section=analysis');
    await page.getByRole('link',{name:'현장 분석 열기',exact:true}).click();
    await page.getByText('이 환경에서는 현장 분석 기능을 사용할 수 없습니다.',{exact:true}).waitFor();
    await capture('actual-analysis',width,'/sites/e2e-site-workspace/analysis',{arrival:'actual gateway click'});
  }
  await page.goto('http://localhost:3241/login');
  await page.getByText('권한별 화면 테스트',{exact:true}).click();
  await page.getByRole('button',{name:'다른 개발 계정 선택'}).click();
  await page.getByText('권한별 화면 테스트(선택)',{exact:true}).click();
  await page.getByRole('button',{name:/KSI 빈 조직 관리자/}).click();
  await page.waitForURL('http://localhost:3241/');
  for(const [width,height]of[[390,844],[768,1024],[1440,900]]){
    await page.setViewportSize({width,height});
    for(const [name,path]of[['denied-assets','/sites/e2e-site-workspace/spatial-assets'],['denied-site','/sites/e2e-site-workspace'],['denied-analysis','/sites/e2e-site-workspace/analysis']]){
      await page.goto('http://localhost:3241'+path);
      await page.getByRole('heading',{level:2,name:'현장을 찾을 수 없습니다',exact:true}).waitFor();
      await capture(name,width,path,{account:'owned empty organization fixture'});
    }
  }
  await page.goto('http://localhost:3241/login');await page.getByRole('button',{name:/개발 Operations Console 시작/}).click();
  const picker=page.getByRole('button',{name:/기본 개발 계정으로 계속/});
  if(await picker.waitFor({state:'visible',timeout:5000}).then(()=>true).catch(()=>false))await picker.click();
  await page.waitForURL('http://localhost:3241/');await page.getByRole('region',{name:'확인 필요 현장 캐러셀'}).waitFor();
  page.off('pageerror',onError);page.off('response',onResponse);page.off('console',onConsole);
  return {origin:'http://localhost:3241',phase:'post-T4-round4-source',generatedDataOnly:true,normalFixtureLoginRestored:true,rows,pageErrors,apiFailures,consoleErrors};
}
