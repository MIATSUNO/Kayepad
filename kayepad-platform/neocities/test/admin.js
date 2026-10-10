(()=>{
const API=(window.KAYSTANT_API||'').replace(/\/$/,'');
const $=id=>document.getElementById(id);
let token='';
let currentUser=null;
let users=[];
let posts=[];
let selectedUserId='';
const loginCard=$('login-card');
const panel=$('admin-panel');
const loginMessage=$('login-message');
const panelMessage=$('panel-message');
const userRows=$('user-rows');
const userFilter=$('user-filter');
const userDetail=$('selected-user');
const actionSelect=$('action');
const postSelect=$('post-select');
const postLabel=$('post-label');
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
 if(!response.ok)throw Error(data.detail||'A solicitação não foi autorizada.');
 return data
};
const formatDate=value=>{
 if(!value)return '—';
 const date=new Date(value);
 return Number.isNaN(date.getTime())?'—':new Intl.DateTimeFormat('pt-BR',{dateStyle:'short'}).format(date)
};
const selectedUser=()=>users.find(user=>user.id===selectedUserId)||null;
const makeCell=(row,value)=>{const cell=document.createElement('td');cell.textContent=value;row.append(cell);return cell};
function renderUsers(){
 userRows.replaceChildren();
 const query=userFilter.value.trim().toLocaleLowerCase('pt-BR');
 const filtered=users.filter(user=>`${user.username} ${user.email}`.toLocaleLowerCase('pt-BR').includes(query));
 if(!filtered.length){const row=document.createElement('tr');const cell=document.createElement('td');cell.colSpan=4;cell.className='empty';cell.textContent=users.length?'Nenhuma conta corresponde ao filtro.':'Nenhuma conta encontrada.';row.append(cell);userRows.append(row);return}
 for(const user of filtered){
  const row=document.createElement('tr');
  row.classList.toggle('selected',user.id===selectedUserId);
  const nameCell=document.createElement('td');
  const pick=document.createElement('button');
  pick.type='button';pick.className='user-pick';pick.textContent='@'+user.username;
  pick.addEventListener('click',()=>selectUser(user.id));
  nameCell.append(pick);row.append(nameCell);
  makeCell(row,user.email);
  makeCell(row,formatDate(user.created_at));
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
function updateControls(){
 const user=selectedUser();
 const action=actionSelect.value;
 postLabel.hidden=action!=='delete-post';
 postSelect.hidden=action!=='delete-post';
 const isAdmin=user&&currentUser&&user.id===currentUser.id;
 generateButton.disabled=!user||Boolean(isAdmin)||(action==='delete-post'&&!postSelect.value)||(action==='block'&&user.is_blocked)||(action==='unblock'&&!user.is_blocked);
 copyButton.disabled=!sqlOutput.value;
 if(isAdmin)userDetail.textContent='@'+user.username+' · '+user.email+' · Conta administrativa protegida';
 else if(user)userDetail.textContent='@'+user.username+' · '+user.email+' · Cadastro '+formatDate(user.created_at);
 else userDetail.textContent='Selecione uma conta.'
}
function selectUser(id){
 selectedUserId=id;
 renderUsers();
 renderPosts();
 sqlOutput.value='';
 updateControls()
}
function sqlDeleteUser(userId,adminId){
 const user=safeId(userId),admin=safeId(adminId);
 return `BEGIN;\nDO $$\nDECLARE\n  target_user_id uuid := '${user}'::uuid;\n  admin_user_id uuid := '${admin}'::uuid;\nBEGIN\n  IF target_user_id = admin_user_id THEN\n    RAISE EXCEPTION 'A conta administrativa protegida não pode ser apagada por este painel.';\n  END IF;\n  IF NOT EXISTS (SELECT 1 FROM public.kt_users WHERE id = target_user_id) THEN\n    RAISE EXCEPTION 'A conta selecionada não existe neste projeto.';\n  END IF;\n  DELETE FROM public.kt_kayepad_delivery_feedback\n  WHERE delivery_id IN (SELECT id FROM public.kt_kayepad_deliveries WHERE sender_id = target_user_id OR recipient_id = target_user_id);\n  DELETE FROM public.kt_kayepad_delivery_notices\n  WHERE user_id = target_user_id OR delivery_id IN (SELECT id FROM public.kt_kayepad_deliveries WHERE sender_id = target_user_id OR recipient_id = target_user_id);\n  DELETE FROM public.kt_kayepad_deliveries\n  WHERE sender_id = target_user_id OR recipient_id = target_user_id;\n  DELETE FROM public.kt_pet_interactions\n  WHERE visitor_id = target_user_id OR pet_id IN (SELECT id FROM public.kt_pets WHERE user_id = target_user_id);\n  DELETE FROM public.kt_group_members\n  WHERE user_id = target_user_id OR group_id IN (SELECT id FROM public.kt_groups WHERE owner_id = target_user_id);\n  DELETE FROM public.kt_group_rules\n  WHERE group_id IN (SELECT id FROM public.kt_groups WHERE owner_id = target_user_id);\n  DELETE FROM public.kt_book_posts\n  WHERE book_id IN (SELECT id FROM public.kt_books WHERE owner_id = target_user_id) OR post_id IN (SELECT id FROM public.kt_posts WHERE user_id = target_user_id);\n  DELETE FROM public.kt_inks\n  WHERE user_id = target_user_id OR post_id IN (SELECT id FROM public.kt_posts WHERE user_id = target_user_id);\n  DELETE FROM public.kt_tickets\n  WHERE user_id = target_user_id OR post_id IN (SELECT id FROM public.kt_posts WHERE user_id = target_user_id);\n  DELETE FROM public.kt_effects\n  WHERE user_id = target_user_id OR post_id IN (SELECT id FROM public.kt_posts WHERE user_id = target_user_id);\n  DELETE FROM public.kt_follows\n  WHERE follower_id = target_user_id OR followed_id = target_user_id;\n  DELETE FROM public.kt_sessions WHERE user_id = target_user_id;\n  DELETE FROM public.kt_password_resets WHERE user_id = target_user_id::text;\n  DELETE FROM public.kt_purchases WHERE user_id = target_user_id;\n  DELETE FROM public.kt_activity WHERE user_id = target_user_id;\n  DELETE FROM public.kt_ticket_inventory WHERE user_id = target_user_id;\n  DELETE FROM public.kt_seal_profiles WHERE user_id = target_user_id;\n  DELETE FROM public.kt_seal_states WHERE user_id = target_user_id;\n  DELETE FROM public.kt_special_wallets WHERE user_id = target_user_id;\n  DELETE FROM public.kt_pets WHERE user_id = target_user_id;\n  DELETE FROM public.kt_books WHERE owner_id = target_user_id;\n  DELETE FROM public.kt_groups WHERE owner_id = target_user_id;\n  DELETE FROM public.kt_posts WHERE user_id = target_user_id;\n  DELETE FROM public.kt_users WHERE id = target_user_id;\nEND $$;\nCOMMIT;`
}
function sqlDeletePost(userId,postId){
 const user=safeId(userId),post=safeId(postId);
 return `BEGIN;\nDO $$\nDECLARE\n  target_user_id uuid := '${user}'::uuid;\n  target_post_id uuid := '${post}'::uuid;\nBEGIN\n  IF NOT EXISTS (SELECT 1 FROM public.kt_posts WHERE id = target_post_id AND user_id = target_user_id) THEN\n    RAISE EXCEPTION 'A publicação não pertence à conta selecionada ou não existe.';\n  END IF;\n  DELETE FROM public.kt_book_posts WHERE post_id = target_post_id;\n  DELETE FROM public.kt_inks WHERE post_id = target_post_id;\n  DELETE FROM public.kt_tickets WHERE post_id = target_post_id;\n  DELETE FROM public.kt_effects WHERE post_id = target_post_id;\n  DELETE FROM public.kt_posts WHERE id = target_post_id AND user_id = target_user_id;\nEND $$;\nCOMMIT;`
}
function sqlSetBlocked(userId,adminId,blocked){
 const user=safeId(userId),admin=safeId(adminId);
 const value=blocked?'TRUE':'FALSE';
 const guard=blocked?'A conta foi bloqueada e as sessões atuais foram revogadas.':'A conta foi desbloqueada. A pessoa precisará entrar novamente.';
 return `BEGIN;\nDO $$\nDECLARE\n  target_user_id uuid := '${user}'::uuid;\n  admin_user_id uuid := '${admin}'::uuid;\nBEGIN\n  IF target_user_id = admin_user_id THEN\n    RAISE EXCEPTION 'A conta administrativa protegida não pode ser bloqueada por este painel.';\n  END IF;\n  IF NOT EXISTS (SELECT 1 FROM public.kt_users WHERE id = target_user_id) THEN\n    RAISE EXCEPTION 'A conta selecionada não existe neste projeto.';\n  END IF;\n  UPDATE public.kt_users SET is_blocked = ${value} WHERE id = target_user_id;\n  ${blocked?'UPDATE public.kt_sessions SET revoked = TRUE WHERE user_id = target_user_id;':''}\nEND $$;\nCOMMIT;\nSELECT '${guard}' AS resultado;`
}
async function loadData(){
 const [userData,postData]=await Promise.all([api('/admin/users'),api('/admin/posts')]);
 if(!Array.isArray(userData)||!Array.isArray(postData))throw Error('A resposta do servidor não está no formato esperado.');
 users=userData;posts=postData;
 if(!users.some(user=>user.id===selectedUserId))selectedUserId=(users.find(user=>user.id!==currentUser.id)||users[0]||{}).id||'';
 renderUsers();renderPosts();updateControls();
 setMessage(panelMessage,`Lista atualizada: ${users.length} contas e ${posts.length} publicações.`,'success')
}
$('login-form').addEventListener('submit',async event=>{
 event.preventDefault();
 if(!API){setMessage(loginMessage,'A API da Kaystant não está configurada.','error');return}
 const button=$('login-button');button.disabled=true;setMessage(loginMessage,'Verificando a conta no servidor…');
 try{
  const result=await api('/auth/login',{method:'POST',body:{email:$('email').value.trim(),password:$('password').value}});
  token=result.token;currentUser=result.user;$('password').value='';
  const [userData,postData]=await Promise.all([api('/admin/users'),api('/admin/posts')]);
  if(!Array.isArray(userData)||!Array.isArray(postData))throw Error('A resposta do servidor não está no formato esperado.');
  users=userData;posts=postData;selectedUserId=(users.find(user=>user.id!==currentUser.id)||users[0]||{}).id||currentUser.id;
  loginCard.hidden=true;panel.hidden=false;renderUsers();renderPosts();updateControls();
  setMessage(panelMessage,`Acesso autorizado. ${users.length} contas e ${posts.length} publicações carregadas.`,'success')
 }catch(error){
  if(token){const oldToken=token;token='';fetch(API+'/auth/logout',{method:'POST',headers:{Authorization:'Bearer '+oldToken}}).catch(()=>{})}
  currentUser=null;users=[];posts=[];
  setMessage(loginMessage,error.message||'Não foi possível entrar no painel.','error')
 }finally{button.disabled=false}
});
$('refresh-button').addEventListener('click',async()=>{
 $('refresh-button').disabled=true;setMessage(panelMessage,'Atualizando…');
 try{await loadData()}catch(error){setMessage(panelMessage,error.message||'Não foi possível atualizar.','error')}
 finally{$('refresh-button').disabled=false}
});
$('logout-button').addEventListener('click',async()=>{
 const oldToken=token;
 token='';currentUser=null;users=[];posts=[];selectedUserId='';sqlOutput.value='';
 if(oldToken)try{await fetch(API+'/auth/logout',{method:'POST',headers:{Authorization:'Bearer '+oldToken}})}catch(e){}
 panel.hidden=true;loginCard.hidden=false;$('login-form').reset();setMessage(loginMessage,'Você saiu do painel.','success');updateControls()
});
userFilter.addEventListener('input',renderUsers);
actionSelect.addEventListener('change',()=>{sqlOutput.value='';updateControls()});
postSelect.addEventListener('change',()=>{sqlOutput.value='';updateControls()});
$('generate-button').addEventListener('click',()=>{
 const user=selectedUser();
 if(!user||!currentUser){setMessage(panelMessage,'Selecione uma conta.','error');return}
 if(user.id===currentUser.id){setMessage(panelMessage,'A conta administrativa está protegida.','error');return}
 try{
  if(actionSelect.value==='delete-user')sqlOutput.value=sqlDeleteUser(user.id,currentUser.id);
  else if(actionSelect.value==='delete-post')sqlOutput.value=sqlDeletePost(user.id,postSelect.value);
  else if(actionSelect.value==='block')sqlOutput.value=sqlSetBlocked(user.id,currentUser.id,true);
  else if(actionSelect.value==='unblock')sqlOutput.value=sqlSetBlocked(user.id,currentUser.id,false);
  setMessage(panelMessage,'SQL gerado. Revise antes de executar no projeto quytz da Supabase.','success');
  updateControls()
 }catch(error){setMessage(panelMessage,error.message||'Não foi possível gerar o SQL.','error')}
});
copyButton.addEventListener('click',async()=>{
 if(!sqlOutput.value)return;
 try{await navigator.clipboard.writeText(sqlOutput.value);setMessage(panelMessage,'SQL copiado.','success')}
 catch(error){sqlOutput.focus();sqlOutput.select();setMessage(panelMessage,'Código selecionado. Copie-o manualmente.','')}
});
window.addEventListener('pagehide',()=>{
 if(token&&API)fetch(API+'/auth/logout',{method:'POST',headers:{Authorization:'Bearer '+token},keepalive:true}).catch(()=>{})
});
})();
