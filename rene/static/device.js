(function(root){
  function classify(userAgent, model, platform, mobile){
    const ua=String(userAgent||'');
    const deviceModel=String(model||'');
    const system=String(platform||'');
    const android=/Android/i.test(ua)||/^Android$/i.test(system);
    const knownTablet=/\bSM-[XTP]\d[\w-]*\b/i.test(`${ua} ${deviceModel}`)||/Galaxy\s*Tab/i.test(`${ua} ${deviceModel}`);
    const mobilePhone=(mobile===true||/\bMobile\b/i.test(ua))&&!knownTablet;
    const reducedSamsungTablet=android&&/SamsungBrowser\//i.test(ua)&&!mobilePhone&&!/SMART-TV|\bTV\b/i.test(ua);
    if(android&&knownTablet&&!mobilePhone)return {supported:true,reason:'samsung-tablet'};
    if(reducedSamsungTablet)return {supported:true,reason:'samsung-browser-tablet'};
    if(/iPad|iPhone|iPod/i.test(ua)||(/Macintosh/i.test(ua)&&mobile===false&&/Mobile/i.test(ua)))return {supported:false,reason:'apple'};
    if(/Windows/i.test(ua))return {supported:false,reason:'windows'};
    return {supported:false,reason:'other'};
  }
  async function detect(navigatorObject){
    const nav=navigatorObject||{};
    let model='',platform='',mobile;
    if(nav.userAgentData){
      platform=nav.userAgentData.platform||'';
      mobile=nav.userAgentData.mobile;
      if(typeof nav.userAgentData.getHighEntropyValues==='function'){
        try{const values=await nav.userAgentData.getHighEntropyValues(['model','platform']);model=values.model||'';platform=values.platform||platform}catch{}
      }
    }
    return classify(nav.userAgent,model,platform,mobile);
  }
  root.reneDevice={classify,detect};
  if(typeof module!=='undefined'&&module.exports)module.exports={classify,detect};
})(typeof window!=='undefined'?window:globalThis);
