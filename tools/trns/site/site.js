(function(){
  /* theme */
  var root=document.documentElement,btn=document.getElementById('theme');
  try{var s=localStorage.getItem('trns-theme');if(s)root.dataset.theme=s}catch(e){}
  btn.addEventListener('click',function(){
    var dark=root.dataset.theme?root.dataset.theme==='dark':!matchMedia('(prefers-color-scheme: light)').matches;
    root.dataset.theme=dark?'light':'dark';
    try{localStorage.setItem('trns-theme',root.dataset.theme)}catch(e){}
  });

  /* PWA: offline-capable + installable (needs https or localhost) */
  if('serviceWorker' in navigator && (location.protocol==='https:'||location.hostname==='localhost')){
    navigator.serviceWorker.register('sw.js').catch(function(){});
  }

  /* install tabs */
  var tabs=[].slice.call(document.querySelectorAll('[role=tab]'));
  tabs.forEach(function(t){t.addEventListener('click',function(){
    tabs.forEach(function(o){var on=o===t;o.setAttribute('aria-selected',on);
      document.getElementById(o.getAttribute('aria-controls')).hidden=!on});
  })});

  /* copy buttons */
  [].forEach.call(document.querySelectorAll('[data-copy]'),function(b){
    b.addEventListener('click',function(){
      var txt=b.parentNode.querySelector('code').innerText;
      (navigator.clipboard?navigator.clipboard.writeText(txt):Promise.reject()).then(function(){
        b.textContent='Copied';setTimeout(function(){b.textContent='Copy'},1500);
      }).catch(function(){b.textContent='Press Ctrl+C';setTimeout(function(){b.textContent='Copy'},1800)});
    });
  });

  /* terminal demo */
  var body=document.getElementById('body'),typed=document.getElementById('typed'),
      chip=document.getElementById('chip'),foot=document.getElementById('foot'),
      pills=foot.innerHTML;
  var script=[
    {d:['EN','PL'],a:'Good morning, how are you?',b:'Dzień dobry, jak się masz?'},
    {d:['EN','PL'],a:'Where is the train station?',b:'Gdzie jest dworzec kolejowy?'},
    {swap:1},
    {d:['PL','EN'],a:'Dziękuję za pomoc!',b:'Thank you for your help!'},
    {copy:1}
  ];
  var reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
  function sleep(ms){return new Promise(function(r){setTimeout(r,reduce?0:ms)})}
  function card(cls,l,t){var c=document.createElement('div');c.className='card '+cls;
    c.innerHTML='<span class="l"></span><span class="r">▎</span><span class="x"></span>';
    c.children[0].textContent=l;c.children[2].textContent=t;body.appendChild(c);
    while(body.scrollHeight>body.clientHeight&&body.children.length>1)body.removeChild(body.firstChild);}
  async function run(){
    if(reduce){card('from','EN','Good morning, how are you?');card('to','PL','Dzień dobry, jak się masz?');return}
    var dir=['EN','PL'],last='';
    for(;;){
      body.innerHTML='';chip.textContent='EN ⇄ PL';dir=['EN','PL'];
      for(var i=0;i<script.length;i++){
        var s=script[i];
        if(s.swap){await sleep(700);dir=[dir[1],dir[0]];chip.textContent=dir[0]+' ⇄ '+dir[1];
          chip.style.transform='scale(.94)';await sleep(150);chip.style.transform='';await sleep(700);continue}
        if(s.copy){foot.innerHTML='<div class="toast">✓ copied translation</div>';await sleep(1800);foot.innerHTML=pills;continue}
        for(var k=1;k<=s.a.length;k++){typed.textContent=s.a.slice(0,k);await sleep(38)}
        await sleep(350);typed.textContent='⠋ translating…';await sleep(650);typed.textContent='';
        card('from',s.d[0],s.a);await sleep(250);card('to',s.d[1],s.b);last=s.b;await sleep(1700);
      }
      await sleep(1500);
    }
  }
  var vis=true;
  run();
})();
