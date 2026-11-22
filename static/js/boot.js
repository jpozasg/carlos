// Colour-mode bootstrap: a classic script in <head> (before first paint, no flash). External, so the CSP needs no inline script.
try{var md=JSON.parse(localStorage.getItem('carlos.mode')||'"auto"');if(md!=='auto')document.documentElement.dataset.mode=md;if(matchMedia('(prefers-color-scheme: dark)').matches)document.documentElement.classList.add('os-dark')}catch(e){}
