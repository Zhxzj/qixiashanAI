/* Presentation only. Delegated events cover late map results and iframe controls. */
(() => {
  'use strict';
  const selector='button,summary,a.ghost,.topnav a,.leaflet-control-zoom-in,.leaflet-control-zoom-out';
  const enabled=el=>!el.matches(':disabled,[aria-disabled="true"]')&&!el.closest('[inert]');
  const blocked=el=>!!el.closest('.poster-stage,#mapBox,.leaflet-marker-pane,.leaflet-popup-pane,.leaflet-tooltip-pane') || (!!el.closest('.leaflet-container')&&!el.matches('.leaflet-control-zoom-in,.leaflet-control-zoom-out'));
  function mark(el){
    if(blocked(el)||el.classList.contains('qixi-glass'))return;
    // Keep absolute/fixed close/remove buttons in their original positioning scheme.
    if(getComputedStyle(el).position==='static')el.classList.add('qixi-glass-anchor');
    el.classList.add('qixi-glass');
    if(el.matches('.place-photo-button,.cand,.thumb-x,[data-story],.leaflet-control-zoom-in,.leaflet-control-zoom-out'))el.classList.add('qixi-glass-flat');
  }
  function discover(root){if(root.nodeType!==1)return;if(root.matches(selector))mark(root);root.querySelectorAll(selector).forEach(mark);}
  discover(document.body);
  const observer=new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)discover(node);});
  observer.observe(document.body,{childList:true,subtree:true});
  let held=null,heldPointer=null;
  const clear=()=>{held?.classList.remove('qixi-pressed');held=null;heldPointer=null;};
  document.addEventListener('pointerdown',event=>{
    clear();document.documentElement.dataset.qixiInput='pointer';
    if(event.button!==0)return;
    const el=event.target.closest(selector);
    if(!el||!enabled(el)||blocked(el))return;
    mark(el);held=el;heldPointer=event.pointerId;el.classList.add('qixi-pressed');
  },true);
  document.addEventListener('pointermove',event=>{if(event.pointerType==='mouse'&&document.documentElement.dataset.qixiInput!=='pointer')document.documentElement.dataset.qixiInput='pointer';},{passive:true});
  document.addEventListener('pointerout',event=>{if(held&&event.pointerId===heldPointer&&!held.contains(event.relatedTarget))clear();},{passive:true});
  for(const type of ['pointerup','pointercancel','lostpointercapture'])window.addEventListener(type,clear,true);
  window.addEventListener('blur',clear);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)clear();});
  document.addEventListener('keydown',event=>{if(!event.metaKey&&!event.ctrlKey&&!event.altKey){clear();if(document.documentElement.dataset.qixiInput!=='keyboard')document.documentElement.dataset.qixiInput='keyboard';}},true);
})();
