(()=>{
 const API=window.KAYSTANT_API||'';
 const $=s=>document.querySelector(s);
 const note=(html,kind='')=>{const n=$('#notice');n.innerHTML=html;n.className=kind};
 function showRecovery(){
  $('#login-form').hidden=true;$('#signup-form').hidden=true;$('#recover-form').hidden=false;
  $('#login-tab').classList.remove('active');$('#signup-tab').classList.remove('active');
  $('#kicker').textContent='RECUPERE SEU ACESSO';$('#title').textContent='Esqueci minha senha';
 }
 $('#forgot').onclick=showRecovery;
 $('#recover-form').onsubmit=async e=>{
  e.preventDefault(); const email=$('#recover-email').value.trim().toLowerCase();
  if(!email.endsWith('@kaystant.org')){
   const subject=encodeURIComponent('Recuperação de acesso à Kaystant');
   const body=encodeURIComponent('Nome completo utilizado no cadastro:\nSenha que você lembra ter utilizado:\nNome de usuário lembrado:\nE-mail utilizado na conta, se lembrar:\n\nMáximo possível de informações sobre a conta e contexto do problema.\n\nEssas informações serão usadas para localizar e verificar a conta. A Kayepad pode levar até 72 horas para responder.');
   note(`Envie nome completo, senha que lembra, username, e-mail da conta e o máximo possível de informações para <b>kayepad.bird@gmail.com</b>.<br><a href="mailto:kayepad.bird@gmail.com?subject=${subject}&body=${body}">Abrir modelo de e-mail</a><br><small>A Kayepad pode levar até 72 horas para responder.</small>`,'ok'); return;
  }
  note('Sua conta usa e-mail Kaystant. <button type="button" id="black-ink">Tinta preta</button>','ok');
  $('#black-ink').onclick=()=>openModal();
 };
 function openModal(){
  const d=document.createElement('dialog');
  d.innerHTML='<form method="dialog" class="modal-card"><button class="close">×</button><p class="eyebrow">recuperação protegida</p><h2>Tinta preta</h2><p>Informe os três dados exatamente como foram cadastrados.</p><label>Nome completo<input id="rn" required></label><label>E-mail Kaystant<input id="re" type="email" required></label><label>Nome de usuário<input id="ru" required></label><div id="rr"></div><div class="modal-actions"><button class="btn ghost">Cancelar</button><button class="btn primary" id="rv" type="button">Confirmar e continuar</button></div></form>';
  document.body.append(d); d.showModal();
  $('#rv').onclick=async()=>{
   const result=$('#rr');
   if(!$('#rn').value.trim()||!$('#re').value.trim()||!$('#ru').value.trim()){result.textContent='Preencha os três campos.';return}
   const response=await fetch(API+'/auth/recover-kaystant',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({full_name:$('#rn').value.trim(),email:$('#re').value.trim().toLowerCase(),username:$('#ru').value.trim()})});
   const data=await response.json();
   if(!response.ok){result.textContent=data.detail||'Os dados não correspondem.';return}
   result.innerHTML='<p>Dados conferidos. Por segurança, defina uma nova senha.</p><label>Nova senha<input id="rp" type="password" minlength="8" required></label><button class="btn primary" id="rs" type="button">Salvar nova senha</button>';
   $('#rs').onclick=async()=>{const z=await fetch(API+'/auth/reset-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:data.reset_token,password:$('#rp').value})});result.innerHTML=z.ok?'<p class="auth-note ok">Senha redefinida com segurança. Agora você já pode entrar.</p>':'<p class="auth-note error">Não foi possível concluir a recuperação.</p>'};
  };
 }
})();