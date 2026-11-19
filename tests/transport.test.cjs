const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const create=require('../campus_bot/web/transport.js');
const reply=(status,body)=>({ok:status===200,status,json:async()=>body});
test('expired authorization renews a session before retrying an unprocessed write',async()=>{
  const calls=[];
  const api=create({initData:()=>'signed',fetchImpl:async(url,opts)=>{
    calls.push([url,opts]);return calls.length===1?reply(403,{error:'expired'}):reply(200,{ok:true});
  }});
  await api('task',{title:'one'});
  assert.deepEqual(calls.map(x=>x[0]),['./api/task','./api/session','./api/task']);
  assert.equal(calls[0][1].credentials,'same-origin');
  assert.equal(calls[0][1].headers['X-Campus-Session'],'1');
});
test('a network failure after saving is not replayed automatically',async()=>{
  let count=0;const api=create({fetchImpl:async()=>{count++;throw Error('offline')}});
  await assert.rejects(api('task',{title:'one'}),/offline/);assert.equal(count,1);
});
test('read recovers after a temporary connection failure',async()=>{
  let count=0;const api=create({fetchImpl:async()=>{if(++count===1)throw Error('offline');return reply(200,{events:[]})}});
  assert.deepEqual(await api('state'),{events:[]});assert.equal(count,2);
});
test('stalled requests end in bounded time',async()=>{
  const api=create({timeoutMs:5,fetchImpl:async(url,opts)=>new Promise((resolve,reject)=>{
    opts.signal.addEventListener('abort',()=>{let e=Error('aborted');e.name='AbortError';reject(e)});
  })});
  await assert.rejects(api('task',{title:'one'}),/Соединение прервалось/);
});
test('an expired session cannot become an infinite retry loop',async()=>{
  let count=0;const api=create({fetchImpl:async()=>{count++;return reply(403,{error:'reopen'})}});
  await assert.rejects(api('state'),/reopen/);assert.equal(count,2);
});

test('a refused login link is reported as is, without a session retry',async()=>{
  const calls=[];const api=create({fetchImpl:async(url)=>{calls.push(url);return reply(403,{error:'Ссылка устарела'})}});
  await assert.rejects(api('login',{token:'x'}),/Ссылка устарела/);assert.deepEqual(calls,['./api/login']);
});

function boot(hash, saved=new Map()) {
  const window={};
  window.parent=window;
  const scripts=[];
  const document={
    createElement:()=>({addEventListener(){}}),
    head:{append:script=>scripts.push(script)},
  };
  vm.runInNewContext(fs.readFileSync(require.resolve('../campus_bot/web/js/boot.js'),'utf8'),{
    window, document, URLSearchParams, location:{hash},
    sessionStorage:{getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value)},
  });
  return {telegram:window.campusTelegram,scripts};
}

test('signed launch data is available before the optional Telegram SDK loads',async()=>{
  const raw='user=%7B%22id%22%3A42%7D&auth_date=123&hash=signature%2Bvalue';
  const stored=new Map();
  const {telegram,scripts}=boot('#calendar?tgWebAppData='+encodeURIComponent(raw)+'&tgWebAppPlatform=tdesktop',stored);
  assert.equal(scripts.length,1);
  assert.equal(scripts[0].async,true);
  assert.equal(telegram.embedded(),true);
  const api=create({initData:telegram.initData,fetchImpl:async(_,options)=>{
    assert.equal(options.headers['X-Telegram-Init-Data'],raw);
    return reply(200,{events:[]});
  }});
  assert.deepEqual(await api('state'),{events:[]});
  assert.equal(boot('',stored).telegram.initData(),raw);
  assert.equal(boot('#tgWebAppPlatform=tdesktop',stored).telegram.initData(),'');
});

test('an ordinary browser opens with no Telegram SDK or launch credentials',()=>{
  const {telegram,scripts}=boot('#login=browser-token');
  assert.equal(telegram.embedded(),false);
  assert.equal(telegram.initData(),'');
  assert.equal(scripts.length,0);
});
