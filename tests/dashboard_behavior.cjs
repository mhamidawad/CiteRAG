'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../citerag/web.html'),'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function harness(overrides={}){
  const elements=new Map(),calls=[],blobs=[],saved=[];
  const element=id=>({id,textContent:'',value:id==='question'?'Question':'',disabled:false,hidden:true,children:[],addEventListener(){},append(...items){this.children.push(...items)},appendChild(item){this.children.push(item)},replaceChildren(){this.children=[]},focus(){},click(){}});
  const get=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id)};
  let badRegistry=false;
  const replies={
    '/api/adapters':{adapters:[{name:'retrieval-only',available:true,status:'ready'},{name:'opencode',available:false,status:'unavailable'}]},
    '/api/health':{status:'ok',status_scope:'HTTP process liveness only',retrieval_index:'present',generation:'not_configured',native_opencode:'unavailable',busy:false},
    '/api/context':{imported_documents:2,indexed_chunks:4,freshness:null},
    '/api/sources':{workspace:'project-one',management:'operator-configured',sources:[{name:'sample',state:'ready',documents:2,excluded:1,revision:'abc123'}]},
    ...overrides
  };
  const context={
    console,AbortController,JSON,Number,Date,Error,Promise,
    setTimeout(callback,ms){if(ms===1500)callback();return 1},clearTimeout(){},
    localStorage:{getItem(){return null},setItem(...args){saved.push(args)}},
    document:{getElementById:get,createElement:tag=>element(tag),querySelectorAll:()=>[]},
    URL:{createObjectURL(blob){blobs.push(blob);return 'blob:test'},revokeObjectURL(){}},
    Blob:class {constructor(parts){this.parts=parts}},
    fetch:async(url,options)=>{
      calls.push({url,options});
      const data=url==='/api/adapters'&&badRegistry?{error:'Unauthorized'}:replies[url];
      const status=url==='/api/adapters'&&badRegistry?401:200;
      return {ok:status===200,status,json:async()=>data};
    }
  };
  vm.createContext(context);vm.runInContext(script,context);
  return {get,calls,blobs,saved,context,setBadRegistry(){badRegistry=true},replies,async flush(){for(let i=0;i<12;i++)await Promise.resolve()}};
}
(async()=>{
  const good=harness();await good.flush();
  assert.equal(good.get('agent-adapter').value,'retrieval-only');
  assert.equal(good.get('submit').disabled,false);
  assert.equal(good.get('reindex-sources').disabled,false);
  assert.match(good.get('workspace-status').textContent,/project-one/);
  assert.equal(good.get('source-inventory').children[0].children[0].textContent,'sample');
  assert.equal(good.get('agent-adapter').children[1].disabled,true);
  assert.equal(good.get('diag-index').textContent,'present');
  assert.equal(good.get('diag-generation').textContent,'not_configured');
  assert.ok(!good.get('context-scope').textContent.includes('undefined'));
  good.get('question').value='PRIVATE QUESTION';
  good.get('export-settings').onclick();
  assert.equal(good.blobs.length,1);
  const exported=JSON.parse(good.blobs[0].parts.join(''));
  assert.deepEqual(Object.keys(exported).sort(),['adapter','format','version']);
  assert.equal(exported.adapter,'retrieval-only');
  assert.ok(!JSON.stringify(exported).includes('PRIVATE'));
  const malicious='<img src=x onerror=alert(1)>';
  good.replies['/api/ask']={job_id:'job-one'};
  good.replies['/api/jobs/job-one']={state:'completed',status:'completed',answer:malicious,evidence:[{source:malicious,id:'chunk',text:malicious}],elapsed_ms:10,mode:'retrieval_only'};
  await good.get('form').onsubmit({preventDefault(){}});
  assert.equal(good.get('answer').textContent,malicious);
  assert.equal(good.get('sources').children[0].children[0].textContent,malicious);
  assert.equal(good.calls.filter(call=>call.url==='/api/ask').length,1);
  assert.equal(good.get('submit').disabled,false);
  good.replies['/api/reindex']={job_id:'reindex-one'};
  good.replies['/api/jobs/reindex-one']={state:'completed',status:'completed',chunks:4};
  await good.get('reindex-sources').onclick();
  assert.match(good.get('source-status').textContent,/Reindex complete/);
  assert.equal(good.calls.filter(call=>call.url==='/api/reindex').length,1);
  const reindexRequest=good.calls.find(call=>call.url==='/api/reindex');
  assert.equal(reindexRequest.options.method,'POST');
  assert.equal(reindexRequest.options.body,'{}');
  assert.equal(good.get('reindex-sources').disabled,false);
  good.replies['/api/sources']={workspace:'project-one',sources:[{name:malicious,state:'unavailable'}]};
  await vm.runInContext('loadSources()',good.context);
  assert.equal(good.get('source-inventory').children[0].children[0].textContent,malicious);
  good.replies['/api/sources']={sources:'invalid'};
  await vm.runInContext('loadSources()',good.context);
  assert.equal(good.get('reindex-sources').disabled,true);
  await good.get('reindex-sources').onclick();
  assert.equal(good.calls.filter(call=>call.url==='/api/reindex').length,1);
  good.setBadRegistry();
  await vm.runInContext('loadAdapters()',good.context);
  assert.equal(good.get('submit').disabled,true);
  assert.equal(good.get('export-settings').disabled,true);
  assert.match(good.get('status').textContent,/Authentication required/);
  await good.get('form').onsubmit({preventDefault(){}});
  assert.equal(good.calls.filter(call=>call.url==='/api/ask').length,1);
  const native=harness({
    '/api/adapters':{adapters:[{name:'opencode',available:true,status:'verified'}]},
    '/api/ask':{job_id:'native-job'},
    '/api/jobs/native-job':{state:'completed',status:'completed',mode:'native_opencode',answer:'LanceDB source citation',sources:['docs/architecture.md'],evidence:[],elapsed_ms:100,grounding_contract:'verbatim-extractive'}
  });
  await native.flush();
  native.get('agent-adapter').value='opencode';
  await native.get('form').onsubmit({preventDefault(){}});
  assert.equal(native.get('sources').children[0].children[0].textContent,'docs/architecture.md');
  assert.match(native.get('sources').children[0].children[1].textContent,/Citation verified/);
  const invalid=harness({'/api/adapters':{adapters:[]}});
  await invalid.flush();
  assert.equal(invalid.get('submit').disabled,true);
  assert.equal(invalid.get('agent-adapter').disabled,true);
  const pending=harness({'/api/ask':{}});
  await pending.flush();
  await pending.get('form').onsubmit({preventDefault(){}});
  assert.match(pending.get('status').textContent,/request identifier/);
  assert.equal(pending.calls.filter(call=>call.url.startsWith('/api/jobs/')).length,0);
  console.log('Dashboard behavior PASS: diagnostics, null context, safe export, inert source text, auth failure, no resubmission, malformed job, source inventory, reindex, invalid sources, native citation fallback.');
})().catch(error=>{console.error(error);process.exitCode=1});
