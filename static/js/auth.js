const inv=location.pathname.match(/^\/invite\/([\w-]+)$/),f=document.getElementById('f'),e=document.getElementById('e');
async function j(m,u,b){const r=await fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):null});return [r.status,await r.json()]}
if(inv){document.getElementById('t').textContent='Set your password';document.getElementById('b').textContent='Save and sign in';
  document.getElementById('u').readOnly=true;document.getElementById('p').autocomplete='new-password';document.getElementById('p').minLength=8;document.getElementById('pl').textContent='New password (8+ characters)';
  j('GET','/api/auth/invite/'+inv[1]).then(([s,d])=>{if(s!==200){e.textContent=d.error;f.querySelectorAll('input,button').forEach(x=>x.disabled=true)}else document.getElementById('u').value=d.username})}
f.onsubmit=async ev=>{ev.preventDefault();e.textContent='';
  const [s,d]=inv?await j('POST','/api/auth/invite/'+inv[1],{password:f.p.value}):await j('POST','/api/auth/login',{username:f.u.value,password:f.p.value});
  if(s<300)location.href='/';else e.textContent=d.error||('HTTP '+s)};
