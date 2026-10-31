(()=>{
  const voices=[['af_heart','Heart · American'],['af_bella','Bella · American'],['af_nicole','Nicole · American'],['af_sarah','Sarah · American'],['af_kore','Kore · American'],['af_nova','Nova · American'],['am_michael','Michael · American'],['am_fenrir','Fenrir · American'],['am_puck','Puck · American'],['bm_george','George · British'],['bm_fable','Fable · British'],['bf_emma','Emma · British'],['bf_isabella','Isabella · British']].map(([voiceURI,name])=>({voiceURI,name,lang:voiceURI[0]==='b'?'en-GB':'en-US'}));
  function createSynth({onStatus=()=>{},WorkerClass=Worker,AudioClass=Audio,URLApi=URL}={}){
    let worker=null,loading=null,id=0,generation=0,current=null,paused=false,ready=false;
    const pending=new Map(),cache=new Map();
    const key=u=>[u.voice?.voiceURI||'af_heart',u.text].join('|');
    function startWorker(){
      if(worker)return;
      worker=new WorkerClass('/kokoro-worker.js',{type:'module'});
      worker.onmessage=event=>{const message=event.data;if(message.type==='status'){if(message.phase==='ready')ready=true;onStatus(message);return}const task=pending.get(message.id);if(!task)return;pending.delete(message.id);if(message.type==='audio')task.resolve(message.blob);else if(message.type==='loaded')task.resolve();else task.reject(new Error(message.type==='cancelled'?'cancelled':message.message||'Kokoro request failed'))};
      worker.onerror=()=>{const error=new Error('Kokoro worker could not start.');for(const task of pending.values())task.reject(error);pending.clear();worker?.terminate();worker=null;loading=null;ready=false;onStatus({phase:'error',message:'Kokoro could not load. Retry the download or choose system voices in Voices.'})};
      worker.postMessage({type:'cancel',generation});
    }
    function request(type,data={}){startWorker();const requestId=++id;return new Promise((resolve,reject)=>{pending.set(requestId,{resolve,reject,type});worker.postMessage({type,id:requestId,...data})})}
    async function load(){if(ready)return;if(!loading)loading=request('load').catch(error=>{loading=null;onStatus({phase:'error',message:'Kokoro download failed. Check your connection and retry, or choose system voices.'});throw error});return loading}
    function generated(utterance){const k=key(utterance);if(cache.has(k))return cache.get(k);const token=generation;const result=load().then(()=>{if(token!==generation)throw Error('cancelled');return request('generate',{text:utterance.text,voice:utterance.voice?.voiceURI||'af_heart',generation:token})});cache.set(k,result);while(cache.size>12)cache.delete(cache.keys().next().value);result.catch(()=>{if(cache.get(k)===result)cache.delete(k)});return result}
    function release(){if(!current)return;current.audio?.pause();if(current.url)URLApi.revokeObjectURL(current.url);current=null}
    return {
      load,getVoices:()=>voices,addEventListener(){},ready:()=>ready,
      prepare(utterance){generated(utterance).catch(()=>{})},
      speak(utterance){const token=generation;release();current={utterance,token};onStatus({phase:ready?'generating':'loading',message:ready?'Preparing Kokoro speech…':'Loading Kokoro for first use…'});generated(utterance).then(blob=>{if(token!==generation||current?.utterance!==utterance)return;const url=URLApi.createObjectURL(blob),audio=new AudioClass(url);current={utterance,token,url,audio};audio.playbackRate=utterance.rate||1;audio.onended=()=>{if(token!==generation)return;release();utterance.onend?.()};audio.onerror=()=>{if(token!==generation)return;release();utterance.onerror?.({error:'unavailable'})};onStatus({phase:'playing',message:'Kokoro neural voice'});if(!paused)audio.play().catch(error=>{if(token!==generation)return;release();utterance.onerror?.({error:error.name==='NotAllowedError'?'not-allowed':'unavailable'})})}).catch(error=>{if(token!==generation)return;release();if(error.message!=='cancelled'){onStatus({phase:'error',message:'Kokoro could not generate speech. Retry or choose system voices in Voices.'});utterance.onerror?.({error:'unavailable'})}})},
      pause(){paused=true;current?.audio?.pause()},
      resume(){paused=false;const active=current;if(active?.audio)active.audio.play().catch(()=>{if(active.token===generation)active.utterance.onerror?.({error:'not-allowed'})})},
      cancel(){generation++;paused=false;release();worker?.postMessage({type:'cancel',generation});for(const [requestId,task]of pending)if(task.type!=='load'){task.reject(Error('cancelled'));pending.delete(requestId)}cache.clear()},
      dispose(){this.cancel();worker?.terminate();worker=null;for(const task of pending.values())task.reject(Error('cancelled'));pending.clear();ready=false;loading=null}
    };
  }
  globalThis.ForumKokoro={createSynth,voices};
})();
