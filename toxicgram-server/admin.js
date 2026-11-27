"use strict";const $=id=>document.getElementById(id);let key="",items=[],asset="";function status(s,error=false){$("status").textContent=s;$("status").className=error?"error":""}async function api(path,options={}){const r=await fetch(path,{...options,headers:{Authorization:"Bearer "+key,...options.headers},cache:"no-store"});let body;try{body=await r.json()}catch{body={}}if(!r.ok)throw Error(typeof body.detail==="string"?body.detail:"HTTP "+r.status);return body}function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}async function refresh(){const data=await api("/v1/admin/catalog");items=data.catalog;$("stats").replaceChildren();for(const [label,v] of [["Аккаунты",data.stats.users],["Выдано подарков",data.stats.gifts],["Звёзды на балансах",data.stats.stars]]){const b=el("div");b.append(el("small",label),el("strong",String(v)));$("stats").append(b)}$("list").replaceChildren();for(const g of items){const row=el("div",undefined,"gift"),d=el("div",undefined,"description"),b=el("button","Изменить");d.append(el("strong",g.name),el("small"," • "+g.rarity),el("p","⭐ "+g.price+" · "+(g.supply?g.issued+"/"+g.supply:"без лимита")+" · "+(g.active?"Опубликован":"Скрыт")));b.onclick=()=>edit(g);row.append(el("span",g.emoji||"🎁","symbol"),d,b);$("list").append(row)}}function edit(g){$("gift-form").reset();$("kind").readOnly=!!g;$("kind").value=g?.kind||"";$("name").value=g?.name||"";$("price").value=g?.price||100;$("supply").value=g?.supply||0;$("rarity").value=g?.rarity||"common";$("emoji").value=g?.emoji||"";$("upgrade").checked=!!g?.upgrade_enabled;$("active").checked=g?!!g.active:true;asset=g?.asset||"";$("art-state").textContent=asset?"Анимация загружена":g?.art?"Встроенная анимация":"Загрузите анимацию";$("edit-title").textContent=g?"Редактирование: "+g.name:"Новый подарок";$("editor").scrollIntoView({behavior:"smooth"})}$("login-form").addEventListener("submit",async e=>{e.preventDefault();key=$("key").value;$("key").value="";try{await refresh();$("login").hidden=true;$("dashboard").hidden=false;status("Вход выполнен")}catch(e){key="";status(e.message,true)}});$("logout").onclick=()=>{clearUsers();key="";items=[];asset="";$("dashboard").hidden=true;$("login").hidden=false;status("Выход выполнен")};$("new").onclick=()=>edit(null);$("gift-form").addEventListener("submit",async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{const file=$("art").files[0];if(file){if(file.size>262144)throw Error("Максимальный размер 256 КБ");asset=(await api("/v1/admin/art",{method:"POST",body:file,headers:{"Content-Type":"application/octet-stream"}})).asset}const body={kind:$("kind").value,name:$("name").value,price:Number($("price").value),supply:Number($("supply").value),rarity:$("rarity").value,emoji:$("emoji").value,upgrade_enabled:$("upgrade").checked,active:$("active").checked,asset};await api("/v1/admin/catalog",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});await refresh();edit(items.find(g=>g.kind===body.kind));status("Подарок сохранён")}catch(e){status(e.message,true)}finally{b.disabled=false}});
let selectedUser=null,userCursor="",avatarURL="",userEpoch=0,listEpoch=0,userBusy=false,pendingAction=null;
function clearUsers(){userEpoch++;listEpoch++;selectedUser=null;pendingAction=null;userCursor="";if(avatarURL)URL.revokeObjectURL(avatarURL);avatarURL="";$("user-avatar").removeAttribute("src");$("user-avatar").hidden=true;$("user-detail").hidden=true;$("user-list").replaceChildren();$("user-info").replaceChildren();$("user-state").replaceChildren();$("user-gifts").replaceChildren();$("user-audit").replaceChildren();$("user-more").hidden=true;$("user-query").value="";$("stars-form").reset();$("grant-form").reset();$("freeze-form").reset();showTab(false)}
function showTab(users){$("catalog-panel").hidden=users;$("users-panel").hidden=!users;$("tab-catalog").setAttribute("aria-pressed",String(!users));$("tab-users").setAttribute("aria-pressed",String(users))}
$("tab-catalog").onclick=()=>showTab(false);
$("tab-users").onclick=async()=>{showTab(true);await loadUsers()};
async function loadUsers(more=false){
 const epoch=++listEpoch,query=$("user-query").value.trim(),after=more?userCursor:"";
 $("user-more").disabled=true;
 try{
  const data=await api("/v1/admin/users?"+new URLSearchParams({q:query,after,limit:"30"}));
  if(epoch!==listEpoch||!key)return;
  if(!more)$("user-list").replaceChildren();
  for(const u of data.users){const row=el("div",undefined,"gift"),d=el("div",undefined,"description"),b=el("button","Профиль");
   d.append(el("strong",u.name),el("small"," • "+(u.username?"@"+u.username:u.number)),el("p","⭐ "+u.balance+" · Подарков: "+u.gift_count+" · "+(u.frozen?"Заморожен":"Активен")));
   b.onclick=()=>{if(!userBusy){pendingAction=null;openUser(u.number)}};row.append(el("span",u.frozen?"🔒":"👤","symbol"),d,b);$("user-list").append(row)}
  if(!more&&!data.users.length)$("user-list").append(el("p","Пользователи не найдены"));
  userCursor=data.next||"";$("user-more").hidden=!userCursor;
 }catch(e){if(epoch===listEpoch)status(e.message,true)}finally{$("user-more").disabled=false}
}
$("user-search").onsubmit=e=>{e.preventDefault();loadUsers()};
$("user-more").onclick=()=>loadUsers(true);
$("user-close").onclick=()=>{if(userBusy)return;userEpoch++;selectedUser=null;pendingAction=null;$("user-detail").hidden=true};
function renderUser(data){
 const u=data.user;selectedUser=u;$("verify-form").reset();$("verify-title").value=u.verification_title||"";$("verify-description").value=u.verification_description||"";$("verify-symbol").value=String(u.verification_symbol||0);$("verify-color").value=String(u.verification_color||0);$("user-info").replaceChildren(el("h2",u.name),el("p",u.number+" · "+(u.username?"@"+u.username:"Без username")),el("p",u.phone||"Виртуальный номер ещё не назначен"),el("p",u.bio||"Нет описания"));
 $("user-state").replaceChildren(el("strong","⭐ "+u.balance+" · "+(u.frozen?"Аккаунт заморожен":"Аккаунт активен")),el("p",u.freeze_reason||""));
 $("freeze-submit").textContent=u.frozen?"Разморозить аккаунт":"Заморозить аккаунт";
 $("grant-kind").replaceChildren();for(const g of items){const option=el("option",g.name+(g.supply?" · осталось "+g.remaining:""));option.value=g.kind;option.disabled=!!g.supply&&g.remaining===0;$("grant-kind").append(option)}
 $("user-gifts").replaceChildren();for(const g of data.gifts){$("user-gifts").append(el("p",(g.emoji||"🎁")+" "+g.name+(g.num?" #"+g.num:"")+" · "+(g.visible?"В профиле":"Скрыт")))}if(!data.gifts.length)$("user-gifts").append(el("p","Нет подарков"));
 const labels={"verification.set":"Верификация","stars.adjust":"Баланс","gift.grant":"Выдача подарка","account.freeze":"Заморозка","account.unfreeze":"Разморозка"};
 $("user-audit").replaceChildren();for(const a of data.audit){let detail="";try{const d=JSON.parse(a.detail);detail=a.action==="stars.adjust"?(d.delta>0?"+":"")+d.delta+" ⭐ ("+d.before+" → "+d.balance+")":a.action==="gift.grant"?d.kind+" #"+d.num:""}catch{}
 $("user-audit").append(el("p",new Date(a.created*1000).toLocaleString()+" · "+(labels[a.action]||a.action)+" "+detail+" · "+a.reason))}
 if(!data.audit.length)$("user-audit").append(el("p","Нет действий"));
 $("user-detail").hidden=false;
}
async function openUser(number,scroll=true){
 const epoch=++userEpoch;
 if(avatarURL)URL.revokeObjectURL(avatarURL);avatarURL="";$("user-avatar").removeAttribute("src");$("user-avatar").hidden=true;
 try{const data=await api("/v1/admin/users/"+encodeURIComponent(number));if(epoch!==userEpoch||!key)return;renderUser(data);if(scroll){$("stars-form").reset();$("freeze-form").reset();$("grant-reason").value="";$("user-detail").scrollIntoView({behavior:"smooth"})}
 if(data.user.avatar){const r=await fetch("/v1/admin/users/"+encodeURIComponent(number)+"/avatar",{headers:{Authorization:"Bearer "+key},cache:"no-store"});if(r.ok){const blob=await r.blob();if(epoch===userEpoch&&key){avatarURL=URL.createObjectURL(blob);$("user-avatar").src=avatarURL;$("user-avatar").hidden=false}}}
 }catch(e){if(epoch===userEpoch)status(e.message,true)}
}
async function mutate(e,action,body,description){
 e.preventDefault();if(!selectedUser||userBusy)return;const number=selectedUser.number;
 if(!body.reason.trim()){status("Укажите причину",true);return}
 const fingerprint=JSON.stringify([number,action,body]);const requestId=pendingAction?.fingerprint===fingerprint?pendingAction.id:crypto.randomUUID();
 if(!confirm(description+"\nПользователь: "+selectedUser.name+" ("+number+")"))return;
 pendingAction={fingerprint,id:requestId};userBusy=true;const b=e.submitter;if(b)b.disabled=true;
 try{await api("/v1/admin/users/"+encodeURIComponent(number)+"/"+action,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...body,request_id:requestId})});pendingAction=null;e.target.reset();await refresh();await loadUsers();await openUser(number,false);status("Действие выполнено")}
 catch(err){status(err.message+" · При повторе тех же параметров используется тот же ID операции.",true)}
 finally{userBusy=false;if(b)b.disabled=false}
}
$("stars-form").onsubmit=e=>{const delta=Number($("stars-amount").value)*($("stars-mode").value==="add"?1:-1);mutate(e,"stars",{delta,reason:$("stars-reason").value},(delta>0?"Начислить ":"Списать ")+Math.abs(delta)+" ⭐?")};
$("grant-form").onsubmit=e=>mutate(e,"gift",{kind:$("grant-kind").value,reason:$("grant-reason").value},"Выдать подарок "+$("grant-kind").selectedOptions[0]?.textContent+" бесплатно?");
$("freeze-form").onsubmit=e=>{if(!selectedUser)return;const frozen=!selectedUser.frozen;mutate(e,"freeze",{frozen,reason:$("freeze-reason").value},frozen?"Заморозить аккаунт и завершить все его сеансы?":"Разморозить аккаунт? Пользователю потребуется новый вход.")};

$("verify-form").onsubmit=e=>mutate(e,"verification",{enabled:$("verify-enabled").value==="yes",title:$("verify-title").value,description:$("verify-description").value,symbol:Number($("verify-symbol").value),color:Number($("verify-color").value),reason:$("verify-reason").value},"Изменить верификацию пользователя?");
