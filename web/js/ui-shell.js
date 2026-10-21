/* UI-only host. One guide document and one persistent, same-origin poster. */
(() => {
  const $ = s => document.querySelector(s);
  const frame = $('#posterFrame');
  let active = 'chat', ready = false, latest = null, posterBusy = false;
  const epoch = () => localStorage.getItem('qixi_epoch') || '';
  function post(type, data = {}) {
    if (ready) frame.contentWindow.postMessage({channel:'qixi-ui-v1', type, sid:Qixi.sid, ...data}, location.origin);
  }
  function snapshot(st) {
    latest = {generation:st.generation, visited:st.visited || [], epoch:epoch()};
    post('snapshot', latest);
  }
  function show(view, focus = true) {
    if (!['chat','map','poster'].includes(view)) return;
    active = view;
    if(view==='chat' && focus) document.body.dataset.conversation='true';
    const home = $('#uiHome');
    const isHome = view==='chat' && document.body.dataset.conversation!=='true';
    home.style.visibility = isHome ? 'hidden' : '';
    home.inert = isHome;
    home.setAttribute('aria-hidden',String(isHome));
    document.body.dataset.view = view;
    for (const name of ['chat','map','poster']) $('#view-'+name).hidden = name !== view;
    document.querySelectorAll('.ui-nav button').forEach(b => {
      if (b.dataset.view === view) b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current');
    });
    $('#uiMore').open = false;
    if (view === 'poster' && !frame.hasAttribute('src')) frame.src = '/poster.html?embedded=1';
    post('active', {active:view === 'poster'});
    if (view === 'map') requestAnimationFrame(() => window.QixiMap?.resize?.());
    if (focus) $('.ui-nav [data-view="'+view+'"]').focus({preventScroll:true});
    if (location.hash !== '#'+view) history.replaceState(null,'','#'+view);
  }
  window.QixiUI = {
    show, snapshot,
    home(){document.body.dataset.conversation='false';show('chat',false);window.scrollTo({top:0,behavior:'instant'});const heading=$('.hero-copy h1');heading.setAttribute('tabindex','-1');heading.focus({preventScroll:true});},
    keyStatus(configured){$('#uiKeyMissing').hidden=configured;},
    conditions(c){const now=c.weather?.now||{};$('#uiWeatherBrief').textContent=[now.text || '天气暂无数据',now.temp_c!=null?now.temp_c+'°C':'',c.red_leaf?.text || '红叶暂无数据'].filter(Boolean).join(' · ');},
    conditionsError(){$('#uiWeatherBrief').textContent='天气与红叶暂不可用，可稍后重试';},
    conversation(){document.body.dataset.conversation='true';show('chat',false);},
    resetEpoch(){latest=null;post('epoch',{epoch:epoch()});},
  };
  window.addEventListener('message', async e => {
    if (e.origin !== location.origin || e.source !== frame.contentWindow || e.data?.channel !== 'qixi-ui-v1' || e.data.sid !== Qixi.sid) return;
    if (e.data.type === 'ready' || e.data.type === 'request-state') {
      ready = true;
      post('active',{active:active === 'poster'});
      try { if(latest && latest.epoch===epoch()) post('snapshot',latest); else await window.QixiAppUI.refresh(); }
      catch { if (latest) post('snapshot',latest); else post('unavailable'); }
    } else if (e.data.type === 'busy' && typeof e.data.busy === 'boolean') posterBusy=e.data.busy;
    else if(e.data.type === 'back') QixiUI.home();
  });
  document.querySelectorAll('[data-view]').forEach(b => {
    if(b === document.body) return;
    b.addEventListener('click',() => {
      show(b.dataset.view);
      if(b.dataset.shortcut === 'places') $('#majorPois').click();
      if(b.dataset.shortcut === 'facilities') { for(const id of ['showToilets','showGates']) {$('#'+id).checked=true;$('#'+id).dispatchEvent(new Event('change'));} $('#homeMap').click(); }
    });
  });
  $('[data-weather]').onclick=()=>{show('chat',false);$('#uiWeatherDetails').open=true;$('#conditions').scrollIntoView({block:'center'});};
  $('#uiConfigureModel').onclick=()=>$('#keyBtn').click();
  $('#uiHome').onclick=()=>QixiUI.home();
  $('[data-story]').onclick=()=>{show('map');$('#mapSearchInput').value='栖霞寺';$('#mapSearchForm').requestSubmit();$('#mapResults button')?.click();};
  document.querySelectorAll('[data-tool]').forEach(b=>b.onclick=()=>{
    $('#uiMore').open=false;
    if(b.dataset.tool==='source') {$('#mapConfigOpen').click();return;}
    show('map');
    if(b.dataset.tool==='demo') {$('#uiDemo').hidden=false;$('#uiDemo').scrollIntoView({block:'center'});}
    if(b.dataset.tool==='annotations') {$('#annotationsOpen').click();$('#annotationEditor').scrollIntoView({block:'center'});}
    if(b.dataset.tool==='facilities') {$('#uiFacilities').hidden=false;$('#uiFacilities').scrollIntoView({block:'center'});}
  });
  document.querySelectorAll('[data-close-tools]').forEach(b=>b.onclick=()=>{b.parentElement.hidden=true;$('.ui-nav [aria-current]').focus();});
  $('#uiCancel').onclick=()=>$('#cancelChatBtn').click();
  $('#uiStopLocation').onclick=()=>$('#stopLocation').click();
  $('#uiStopVoice').onclick=()=>$('#stopVoiceBtn').click();
  setInterval(()=>{
    const t=window.QixiAppUI?.tasks() || {};
    const loc=window.QixiMap?.inspect().locating;
    $('#uiCancel').hidden=!t.chat;
    $('#uiStopLocation').hidden=!loc;
    $('#uiStopVoice').hidden=!t.voice;
    $('#uiPosterTask').hidden=!posterBusy;
    $('#uiTasks').hidden=!(t.chat || loc || t.voice || posterBusy);
    $('#uiTaskStatus').textContent=[t.chat?'小栖正在回答':'',loc?$('#locationStatus').textContent:'',t.voice?'讲解播放中':'',posterBusy?'海报任务进行中':''].filter(Boolean).join(' · ');
    $('#cancelChatBtn').hidden=!t.chat;
  },250);
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape' && $('#uiMore').open){$('#uiMore').open=false;$('#uiMore summary').focus();}
  });
  // Preserve the existing modal implementations, adding keyboard/focus handling.
  for(const [id,close] of [['keyModal','keyClose'],['mapConfigModal','mapConfigClose'],['facilitiesModal','facilitiesClose']]){
    const modal=$('#'+id);let opened=false,previous=null;
    modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');
    const title=modal.querySelector('h3');title.id=id+'Title';modal.setAttribute('aria-labelledby',title.id);
    const visible=()=>!modal.hidden && getComputedStyle(modal).display!=='none';
    new MutationObserver(()=>{
      const now=visible();if(now===opened)return;opened=now;
      if(now){previous=document.activeElement;modal.querySelector('input,textarea,button')?.focus();}
      else {const target=previous?.getClientRects().length?previous:$('#uiMore summary');target?.focus({preventScroll:true});}
    }).observe(modal,{attributes:true,attributeFilter:['hidden','style']});
    modal.addEventListener('keydown',e=>{
      if(e.key==='Escape') {e.preventDefault();$('#'+close).click();}
      if(e.key==='Tab') {
        const nodes=[...modal.querySelectorAll('button,input,textarea,select,a[href]')].filter(n=>!n.disabled&&n.getClientRects().length);
        if(!nodes.length)return;
        if(e.shiftKey&&document.activeElement===nodes[0]){e.preventDefault();nodes.at(-1).focus();}
        else if(!e.shiftKey&&document.activeElement===nodes.at(-1)){e.preventDefault();nodes[0].focus();}
      }
    });
  }
  $('#uiMore').addEventListener('click',e=>{if(e.target.closest('button,a')) $('#uiMore').open=false;});
  document.addEventListener('pointerdown',e=>{if(!e.target.closest('#uiMore')) $('#uiMore').open=false;});
  window.addEventListener('hashchange',()=>show(location.hash.slice(1)));
  show(['chat','map','poster'].includes(location.hash.slice(1))?location.hash.slice(1):'chat',false);
})();
