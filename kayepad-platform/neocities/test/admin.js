(()=>{
const API=(window.KAYSTANT_API||'').replace(/\/$/,'');
const $=id=>document.getElementById(id);
let token='';
let primaryToken='';
let adminToken='';
let challengeToken='';
let currentStep=2;
let currentUser=null;
let users=[];
let posts=[];
let selectedUserId='';
const loginCard=$('login-card');
const panel=$('admin-panel');
const loginMessage=$('login-message');
const stepupCard=$('stepup-card');
const stepupMessage=$('stepup-message');
const stepupQuestion=$('stepup-question');
const stepCount=$('step-count');
const stepDots=$('step-dots');
const stepupAnswer=$('stepup-answer');
const panelMessage=$('panel-message');
const userRows=$('user-rows');
const userFilter=$('user-filter');
const userDetail=$('selected-user');
const actionSelect=$('action');
const postSelect=$('post-select');
const postLabel=$('post-label');
const blockConfirmWrap=$('block-confirm-wrap');
const blockConfirm=$('block-confirm');
const sqlOutput=$('sql-output');
const generateButton=$('generate-button');
const copyButton=$('copy-button');
const uuidPattern=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const setMessage=(element,text,type='')=>{element.textContent=text;element.className='message'+(type?' '+type:'')};
const safeId=value=>{if(!uuidPattern.test(String(value||'')))throw Error('Identificador inválido. Atualize a lista e tente novamente.');return String(value).toLowerCase()};
const api=async(path,options={})=>{
 if(!API)throw Error('A API da Kaystant não está configurada.');
 const headers={'Accept':'application/json',...(options.headers||{})};
 if(options.body){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body)}
 if(token)headers.Authorization='Bearer '+token;
 let response;
 try{response=await fetch(API+path,{...options,headers})}catch(e){throw Error('Não foi possível alcançar o servidor. Tente novamente.')}
 const data=await response.json().catch(()=>({}));
 if(!response.ok){
  const expiredAdminToken=adminToken&&token===adminToken;
  const expiredPrimarySession=/verifica(?:ção|cao) expirada|sessão expirada/i.test(data.detail||'');
  if(response.status===401&&token&&(expiredAdminToken||expiredPrimarySession)){const oldPrimary=primaryToken;clearSensitiveState('A sessão expirou. Entre e confirme novamente.');if(oldPrimary&&API)fetch(API+'/auth/logout',{method:'POST',headers:{Authorization:'Bearer '+oldPrimary}}).catch(()=>{})}
  throw Error(data.detail||'A solicitação não foi autorizada.')
 }
 return data
};
const formatDate=value=>{
 if(!value)return '—';
 const date=new Date(value);
 return Number.isNaN(date.getTime())?'—':new Intl.DateTimeFormat('pt-BR',{dateStyle:'short'}).format(date)
};
const selectedUser=()=>users.find(user=>user.id===selectedUserId)||null;
const isProtectedAdmin=user=>Boolean(user&&(user.is_admin||(currentUser&&user.id===currentUser.id)));
const protectedAdminIds=()=>[...new Set([...users.filter(user=>user.is_admin).map(user=>safeId(user.id)),...(currentUser&&currentUser.id?[safeId(currentUser.id)]:[])])];
const protectedAdminArray=ids=>{const values=ids.map(id=>`'${safeId(id)}'::uuid`);if(!values.length)throw Error('Nenhuma conta administrativa protegida foi identificada.');return values.join(', ')};
const makeCell=(row,value)=>{const cell=document.createElement('td');cell.textContent=value;row.append(cell);return cell};
function renderUsers(){
 userRows.replaceChildren();
 const query=userFilter.value.trim().toLocaleLowerCase('pt-BR');
 const filtered=users.filter(user=>String(user.username||'').toLocaleLowerCase('pt-BR').includes(query));
 if(!filtered.length){const row=document.createElement('tr');const cell=document.createElement('td');cell.colSpan=2;cell.className='empty';cell.textContent=users.length?'Nenhuma conta corresponde ao filtro.':'Nenhuma conta encontrada.';row.append(cell);userRows.append(row);return}
 for(const user of filtered){
  const row=document.createElement('tr');
  row.classList.toggle('selected',user.id===selectedUserId);
  const nameCell=document.createElement('td');
  const pick=document.createElement('button');
  pick.type='button';pick.className='user-pick';pick.textContent='@'+user.username;
  pick.addEventListener('click',()=>selectUser(user.id));
  nameCell.append(pick);row.append(nameCell);
  const stateCell=document.createElement('td');
  const state=document.createElement('span');state.className='status'+(user.is_blocked?' blocked':'');state.textContent=user.is_blocked?'Bloqueada':'Ativa';stateCell.append(state);row.append(stateCell);
  userRows.append(row)
 }
}
function renderPosts(){
 const user=selectedUser();
 postSelect.replaceChildren();
 const ownPosts=posts.filter(post=>user&&post.user_id===user.id);
 if(!ownPosts.length){const option=document.createElement('option');option.value='';option.textContent='Nenhuma publicação desta conta';postSelect.append(option);return}
 for(const post of ownPosts){const option=document.createElement('option');option.value=post.id;option.textContent=`${post.title} · ${formatDate(post.created_at)}`;postSelect.append(option)}
}
function renderSelectedUser(user,isAdmin){
 userDetail.replaceChildren();
 if(!user){userDetail.textContent='Selecione uma conta.';return}
 const fields=[
  ['Usuário','@'+(user.username||'—')],
  ['Nome definido',user.display_name||'—'],
  ['Email',user.email||'—'],
  ['Cadastro',formatDate(user.created_at)],
  ['Bio',user.bio||'—'],
  ['Acesso',user.is_blocked?'Bloqueada':'Ativa']
 ];
 if(isAdmin)fields.push(['Proteção','Conta administrativa protegida']);
 for(const [label,value] of fields){const line=document.createElement('p');const title=document.createElement('strong');title.textContent=label+':';line.append(title,document.createTextNode(' '+String(value)));userDetail.append(line)}
}
function updateControls(){
 const user=selectedUser();
 const action=actionSelect.value;
 postLabel.hidden=action!=='delete-post';
 postSelect.hidden=action!=='delete-post';
 blockConfirmWrap.hidden=action!=='block';
 const isAdmin=isProtectedAdmin(user);
 blockConfirmWrap.hidden=action!=='block'&&action!=='unblock';
 $('action-confirm-text').textContent=action==='unblock'?'Confirme que revisou o pedido por email e decidiu desbloquear.':'Confirme que analisou o relato e avisou a pessoa antes de bloquear.';
 generateButton.disabled=!user||isAdmin||(action==='delete-post'&&!postSelect.value)||((action==='block'||action==='unblock')&&!blockConfirm.checked)||(action==='block'&&user.is_blocked)||(action==='unblock'&&!user.is_blocked);
 copyButton.disabled=!sqlOutput.value;
 renderSelectedUser(user,isAdmin)
}
function selectUser(id){
 selectedUserId=id;
 blockConfirm.checked=false;
 renderUsers();
 renderPosts();
 sqlOutput.value='';
 updateControls()
}
function sqlDeleteUser(userId,protectedIds){
 const user=safeId(userId),admins=protectedAdminArray(protectedIds);
 return `BEGIN;\nDO $$\nDECLARE\n  target_user_id uuid := '${user}'::uuid;\nBEGIN\n  IF target_user_id = ANY (ARRAY[${admins}]) THEN\n    RAISE EXCEPTION 'Uma conta administrativa protegida não pode ser apagada por este painel.';\n  END IF;\n  IF NOT EXISTS (SELECT 1 FROM public.kt_users WHERE id = target_user_id) THEN\n    RAISE EXCEPTION 'A conta selecionada não existe neste projeto.';\n  END IF;\n  DELETE FROM public.kt_kayepad_delivery_feedback\n  WHERE delivery_id IN (SELECT id FROM public.kt_kayepad_deliveries WHERE sender_id = target_user_id OR recipient_id = target_user_id);\n  DELETE FROM public.kt_kayepad_delivery_notices\n  WHERE user_id = target_user_id OR delivery_id IN (SELECT id FROM public.kt_kayepad_deliveries WHERE sender_id = target_user_id OR recipient_id = target_user_id);\n  DELETE FROM public.kt_kayepad_deliveries\n  WHERE sender_id = target_user_id OR recipient_id = target_user_id;\n  DELETE FROM public.kt_pet_interactions\n  WHERE visitor_id = target_user_id OR pet_id IN (SELECT id FROM public.kt_pets WHERE user_id = target_user_id);\n  DELETE FROM public.kt_group_members\n  WHERE user_id = target_user_id OR group_id IN (SELECT id FROM public.kt_groups WHERE owner_id = target_user_id);\n  DELETE FROM public.kt_group_rules\n  WHERE group_id IN (SELECT id FROM public.kt_groups WHERE owner_id = target_user_id);\n  DELETE FROM public.kt_book_posts\n  WHERE book_id IN (SELECT id FROM public.kt_books WHERE owner_id = target_user_id) OR post_id IN (SELECT id FROM public.kt_posts WHERE user_id = target_user_id);\n  DELETE FROM public.kt_inks\n  WHERE user_id = target_user_id OR post_id IN (SELECT id FROM public.kt_posts WHERE user_id = target_user_id);\n  DELETE FROM public.kt_tickets\n  WHERE user_id = target_user_id OR post_id IN (SELECT id FROM public.kt_posts WHERE user_id = target_user_id);\n  DELETE FROM public.kt_effects\n  WHERE user_id = target_user_id OR post_id IN (SELECT id FROM public.kt_posts WHERE user_id = target_user_id);\n  DELETE FROM public.kt_follows\n  WHERE follower_id = target_user_id OR followed_id = target_user_id;\n  DELETE FROM public.kt_sessions WHERE user_id = target_user_id;\n  DELETE FROM public.kt_password_resets WHERE user_id = target_user_id::text;\n  DELETE FROM public.kt_purchases WHERE user_id = target_user_id;\n  DELETE FROM public.kt_activity WHERE user_id = target_user_id;\n  DELETE FROM public.kt_ticket_inventory WHERE user_id = target_user_id;\n  DELETE FROM public.kt_seal_profiles WHERE user_id = target_user_id;\n  DELETE FROM public.kt_seal_states WHERE user_id = target_user_id;\n  DELETE FROM public.kt_special_wallets WHERE user_id = target_user_id;\n  DELETE FROM public.kt_pets WHERE user_id = target_user_id;\n  DELETE FROM public.kt_books WHERE owner_id = target_user_id;\n  DELETE FROM public.kt_groups WHERE owner_id = target_user_id;\n  DELETE FROM public.kt_posts WHERE user_id = target_user_id;\n  DELETE FROM public.kt_users WHERE id = target_user_id;\nEND $$;\nCOMMIT;`
}
function sqlDeletePost(userId,postId,protectedIds){
 const user=safeId(userId),post=safeId(postId),admins=protectedAdminArray(protectedIds);
 return `BEGIN;\nDO $$\nDECLARE\n  target_user_id uuid := '${user}'::uuid;\n  target_post_id uuid := '${post}'::uuid;\nBEGIN\n  IF target_user_id = ANY (ARRAY[${admins}]) THEN\n    RAISE EXCEPTION 'Publicações de contas administrativas protegidas não podem ser apagadas por este painel.';\n  END IF;\n  IF NOT EXISTS (SELECT 1 FROM public.kt_posts WHERE id = target_post_id AND user_id = target_user_id) THEN\n    RAISE EXCEPTION 'A publicação não pertence à conta selecionada ou não existe.';\n  END IF;\n  DELETE FROM public.kt_book_posts WHERE post_id = target_post_id;\n  DELETE FROM public.kt_inks WHERE post_id = target_post_id;\n  DELETE FROM public.kt_tickets WHERE post_id = target_post_id;\n  DELETE FROM public.kt_effects WHERE post_id = target_post_id;\n  DELETE FROM public.kt_posts WHERE id = target_post_id AND user_id = target_user_id;\nEND $$;\nCOMMIT;`
}
function sqlSetBlocked(userId,blocked,protectedIds){
 const user=safeId(userId),admins=protectedAdminArray(protectedIds);
 const value=blocked?'TRUE':'FALSE';
 const guard=blocked?'A conta foi bloqueada e as sessões atuais foram revogadas.':'A conta foi desbloqueada. A pessoa precisará entrar novamente.';
 return `BEGIN;\nDO $$\nDECLARE\n  target_user_id uuid := '${user}'::uuid;\nBEGIN\n  IF target_user_id = ANY (ARRAY[${admins}]) THEN\n    RAISE EXCEPTION 'Uma conta administrativa protegida não pode ser bloqueada nem desbloqueada por este painel.';\n  END IF;\n  IF NOT EXISTS (SELECT 1 FROM public.kt_users WHERE id = target_user_id) THEN\n    RAISE EXCEPTION 'A conta selecionada não existe neste projeto.';\n  END IF;\n  UPDATE public.kt_users SET is_blocked = ${value} WHERE id = target_user_id;\n  ${blocked?'UPDATE public.kt_sessions SET revoked = TRUE WHERE user_id = target_user_id;':''}\nEND $$;\nCOMMIT;\nSELECT '${guard}' AS resultado;`
}
async function loadData(){
 const [userData,postData]=await Promise.all([api('/admin/users'),api('/admin/posts')]);
 if(!Array.isArray(userData)||!Array.isArray(postData))throw Error('A resposta do servidor não está no formato esperado.');
 users=userData;posts=postData;
 if(!users.some(user=>user.id===selectedUserId))selectedUserId=(users.find(user=>user.id!==currentUser.id)||users[0]||{}).id||'';
 renderUsers();renderPosts();updateControls();
 const time=new Intl.DateTimeFormat('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date());
 setMessage(panelMessage,`Consulta às ${time}: ${users.length} contas e ${posts.length} publicações.`,'success')
}
function updateStepup(data){
 currentStep=data.step;
 challengeToken=data.challenge||challengeToken;
 stepupQuestion.textContent=data.question||'';
 stepupQuestion.setAttribute('translate',currentStep===3?'no':'yes');
 stepCount.textContent=`Faltam ${data.remaining} etapas para liberar o painel`;
 [...stepDots.children].forEach((dot,index)=>dot.classList.toggle('done',index<3-data.remaining));
 stepupAnswer.value='';
 setMessage(stepupMessage,'');
}
$('login-form').addEventListener('submit',async event=>{
 event.preventDefault();
 if(!API){setMessage(loginMessage,'A API da Kaystant não está configurada.','error');return}
 const button=$('login-button');button.disabled=true;setMessage(loginMessage,'Verificando a conta no servidor…');
 try{
  const result=await api('/auth/login',{method:'POST',body:{email:$('email').value.trim(),password:$('password').value}});
  primaryToken=result.token;token=primaryToken;currentUser=result.user;$('password').value='';
  const verification=await api('/admin/step-up/start',{method:'POST'});
  updateStepup(verification);loginCard.hidden=true;stepupCard.hidden=false;stepupAnswer.focus();
 }catch(error){
  if(primaryToken)fetch(API+'/auth/logout',{method:'POST',headers:{Authorization:'Bearer '+primaryToken}}).catch(()=>{});
  token='';primaryToken='';adminToken='';challengeToken='';currentUser=null;users=[];posts=[];
  setMessage(loginMessage,error.message||'Não foi possível entrar no painel.','error')
 }finally{button.disabled=false}
});
$('stepup-form').addEventListener('submit',async event=>{
 event.preventDefault();
 const button=$('stepup-submit');button.disabled=true;setMessage(stepupMessage,'Validando a etapa no servidor…');
 try{
  const result=await api('/admin/step-up/answer',{method:'POST',body:{challenge:challengeToken,answer:stepupAnswer.value}});
  if(result.completed){
   adminToken=result.admin_token;token=adminToken;challengeToken='';stepupCard.hidden=true;panel.hidden=false;
   await loadData();setMessage(panelMessage,`Acesso autorizado por 15 minutos. ${users.length} contas e ${posts.length} publicações carregadas.`,'success');
  }else{updateStepup(result);setMessage(stepupMessage,'Etapa validada. Continue.','success');stepupAnswer.focus()}
 }catch(error){stepupAnswer.value='';setMessage(stepupMessage,error.message||'Não foi possível validar a etapa.','error')}
 finally{button.disabled=false}
});
$('stepup-cancel').addEventListener('click',()=>{
 const oldToken=primaryToken;
 clearSensitiveState('Verificação cancelada.');
 if(oldToken)fetch(API+'/auth/logout',{method:'POST',headers:{Authorization:'Bearer '+oldToken}}).catch(()=>{})
});
$('refresh-button').addEventListener('click',async()=>{
 $('refresh-button').disabled=true;setMessage(panelMessage,'Atualizando…');
 try{await loadData()}catch(error){setMessage(panelMessage,error.message||'Não foi possível atualizar.','error')}
 finally{$('refresh-button').disabled=false}
});
$('logout-button').addEventListener('click',async()=>{
 const oldToken=primaryToken;
 clearSensitiveState('Você saiu do painel.');
 if(oldToken)try{await fetch(API+'/auth/logout',{method:'POST',headers:{Authorization:'Bearer '+oldToken}})}catch(e){}
});
userFilter.addEventListener('input',renderUsers);
actionSelect.addEventListener('change',()=>{sqlOutput.value='';blockConfirm.checked=false;updateControls()});
postSelect.addEventListener('change',()=>{sqlOutput.value='';updateControls()});
blockConfirm.addEventListener('change',updateControls);
$('generate-button').addEventListener('click',()=>{
 const user=selectedUser();
 if(!user||!currentUser){setMessage(panelMessage,'Selecione uma conta.','error');return}
 if(isProtectedAdmin(user)){setMessage(panelMessage,'Contas administrativas e suas publicações estão protegidas.','error');return}
 if((actionSelect.value==='block'||actionSelect.value==='unblock')&&!blockConfirm.checked){setMessage(panelMessage,actionSelect.value==='block'?'Antes do bloqueio, confirme que analisou o relato e avisou a pessoa.':'Antes de desbloquear, confirme que revisou o pedido por email e decidiu liberar o acesso.','error');return}
 try{
  const protectedIds=protectedAdminIds();
  if(actionSelect.value==='delete-user')sqlOutput.value=sqlDeleteUser(user.id,protectedIds);
  else if(actionSelect.value==='delete-post')sqlOutput.value=sqlDeletePost(user.id,postSelect.value,protectedIds);
  else if(actionSelect.value==='block')sqlOutput.value=sqlSetBlocked(user.id,true,protectedIds);
  else if(actionSelect.value==='unblock')sqlOutput.value=sqlSetBlocked(user.id,false,protectedIds);
  setMessage(panelMessage,actionSelect.value==='block'?'SQL gerado após sua confirmação de análise e contato. Revise antes de executar.':'SQL gerado. Revise antes de executar no projeto Kaystant do Supabase.','success');
  updateControls()
 }catch(error){setMessage(panelMessage,error.message||'Não foi possível gerar o SQL.','error')}
});
copyButton.addEventListener('click',async()=>{
 if(!sqlOutput.value)return;
 try{await navigator.clipboard.writeText(sqlOutput.value);setMessage(panelMessage,'SQL copiado.','success')}
 catch(error){sqlOutput.focus();sqlOutput.select();setMessage(panelMessage,'Código selecionado. Copie-o manualmente.','')}
});
const clearSensitiveState=message=>{
 const oldToken=primaryToken;
 token='';primaryToken='';adminToken='';challengeToken='';currentStep=2;currentUser=null;users=[];posts=[];selectedUserId='';sqlOutput.value='';userRows.replaceChildren();userFilter.value='';stepupQuestion.textContent='';stepupAnswer.value='';blockConfirm.checked=false;renderPosts();
 panel.hidden=true;stepupCard.hidden=true;loginCard.hidden=false;$('login-form').reset();$('stepup-form').reset();setMessage(loginMessage,message||'Entre novamente para abrir o painel.');setMessage(stepupMessage,'');updateControls();
 return oldToken
};
window.addEventListener('pagehide',()=>{
 const oldToken=clearSensitiveState('Entre novamente ao abrir o painel.');
 if(oldToken&&API)fetch(API+'/auth/logout',{method:'POST',headers:{Authorization:'Bearer '+oldToken},keepalive:true}).catch(()=>{})
});
window.addEventListener('pageshow',event=>{
 if(event.persisted)clearSensitiveState('Entre novamente para abrir o painel.')
});
})();
