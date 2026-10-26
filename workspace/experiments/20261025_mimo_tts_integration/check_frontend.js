// Deterministic browser-state checks without claiming a real browser test.
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const html=fs.readFileSync(__dirname+"/chat.html","utf8");
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function harness(){
  const elements=new Map(),frames=[],requests=[];
  function element(){
    return {value:"",textContent:"",hidden:false,disabled:false,clientWidth:600,scrollHeight:100,scrollTop:0,
      children:[],classList:{add(){},remove(){}},append(...children){this.children.push(...children)},
      replaceChildren(){this.children=[]},pause(){},getContext(){return{scale(){},beginPath(){},moveTo(){},lineTo(){},stroke(){}}}};
  }
  const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},
    createElement(){return element()}};
  let response;
  class AudioContext{
    constructor(){this.currentTime=0;this.sampleRate=24000;this.destination={}}
    async resume(){}
    createBuffer(channels,length,rate){return{duration:length/rate,copyToChannel(){}}}
    createBufferSource(){return{connect(){},start(){},stop(){}}}
  }
  const sandbox={document,AudioContext,AudioWorkletNode:class{},navigator:{},AbortController,
    Uint8Array,Float32Array,DataView,TextDecoder,Blob,URL,JSON,Math,console,
    performance:{now:()=>0},devicePixelRatio:1,atob,btoa,setTimeout,clearTimeout,
    setInterval(){},requestAnimationFrame(fn){frames.push(fn)},window:{addEventListener(){},AudioWorkletNode:class{}},
    async fetch(url,options){
      if(url==="/api/status")return{json:async()=>({mimo:true,tts:true})};
      requests.push(JSON.parse(options.body));return response;
    }};
  vm.createContext(sandbox);vm.runInContext(script,sandbox);
  document.getElementById("voice").value="vivian";document.getElementById("language").value="Auto";
  return{sandbox,elements,frames,requests,run:code=>vm.runInContext(code,sandbox),setResponse:r=>response=r};
}
function stream(events,hold=false){
  let read=0,resolve;
  const data=Buffer.from(events.map(e=>JSON.stringify({response_id:"turn",...e})).join("\n")+"\n");
  return {response:{ok:true,body:{getReader(){return{read:async()=>{
    if(read++===0)return{done:false,value:new Uint8Array(data)};
    if(hold)return new Promise(r=>{resolve=r});
    return{done:true};
  }}}}},release(){resolve?.({done:true})}};
}
function events(){
  const pcm=Buffer.alloc(4800).toString("base64");
  return[{type:"start",sample_rate:24000},{type:"text",delta:"First. Second."},
    {type:"segment",segment_id:0,end:6},{type:"audio",segment_id:0,pcm,samples:2400},
    {type:"segment_done",segment_id:0},{type:"segment",segment_id:1,end:14},
    {type:"audio",segment_id:1,pcm,samples:2400},{type:"segment_done",segment_id:1},
    {type:"done",text:"First. Second.",samples:4800}];
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function main(){
  {
    const h=harness();h.setResponse(stream(events()).response);
    await h.run('send({role:"user",input:"question"})');
    h.run("ctx.currentTime=1");h.frames.splice(0).forEach(fn=>fn());
    assert.equal(h.run("history.length"),2);
    assert.equal(h.run("history[1].input"),"First. Second.");
    assert.equal(h.elements.get("state").textContent,"Done");
  }
  {
    const h=harness(),s=stream(events().slice(0,-1),true);h.setResponse(s.response);
    const promise=h.run('send({role:"user",input:"question"})');await tick();
    h.run("ctx.currentTime=.15;stop()");
    assert.equal(h.run("history[1].input"),"First.");
    const count=h.elements.get("thread").children.length;s.release();await promise;
    assert.equal(h.elements.get("thread").children.length,count);
    assert.equal(h.run("active"),null);
  }
  {
    const h=harness(),s=stream(events().slice(0,2),true);h.setResponse(s.response);
    const promise=h.run('send({role:"user",input:"question"})');await tick();h.run("stop()");
    assert.equal(h.run("history.length"),0);s.release();await promise;
    assert.equal(h.elements.get("state").textContent,"Stopped");
  }
  {
    const h=harness(),bad=events();bad[3].samples=1;h.setResponse(stream(bad).response);
    await h.run('send({role:"user",input:"question"})');
    assert.equal(h.elements.get("state").textContent,"Invalid PCM size");
    assert.equal(h.run("history.length"),0);
  }
  console.log("Frontend state checks PASS: complete history, played-prefix interruption, stale completion, invalid PCM.");
}
main().catch(error=>{console.error(error);process.exitCode=1});
