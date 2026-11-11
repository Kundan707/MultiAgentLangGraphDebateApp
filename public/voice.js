(()=>{
  const roles=['Affirmative','Negative','Questioner','Rebuttal','Researcher','Judge'];
  const order=['a','n','questions','challenges','aa','na','ar','nr','research','judge'];
  function clean(text){return String(text||'').replace(/https?:\/\/\S+/g,'').replace(/\b(?:[a-z0-9-]+\.)+(?:com|org|edu|gov|net)\b(?:\/\S*)?/gi,'').replace(/[*#_`]/g,'').replace(/\s+/g,' ').trim()}
  function chunks(text){const words=clean(text).split(/\s+/);const result=[];let part='';for(const word of words){if(part.length+word.length>180&&part){result.push(part);part=''}part+=(part?' ':'')+word}if(part)result.push(part);return result}
  function entries(data={}){
    const result=[];
    for(const [key,role,label] of [['a','Affirmative','Opening case'],['n','Negative','Opening case'],['ar','Affirmative','Rebuttal'],['nr','Negative','Rebuttal']])if(data[key])result.push({key,role,text:role+'. '+label+'. '+(Array.isArray(data[key])?data[key].join('. '):data[key])});
    for(const [key,role] of [['questions','Questioner'],['challenges','Rebuttal']])if(data[key])result.push({key,role,text:role+'. '+['affirmative','negative'].map(side=>'For the '+side+'. '+data[key][side].map((q,i)=>(key==='questions'?'Q':'R')+(i+1)+'. '+q.question+'. '+(q.purpose||'Weakness: '+q.weakness+'. Counterargument: '+q.counterargument)).join(' ')).join(' ')});
    for(const [key,role] of [['aa','Affirmative'],['na','Negative']])if(data[key])result.push({key,role,text:role+'. Answers. '+data[key].map(a=>a.id+'. '+a.question+'. '+a.answer).join(' ')});
    if(data.review)result.push({key:'research',role:'Researcher',text:'Researcher. Evidence review. '+data.review.summary+'. '+data.review.claims.map(c=>c.side+'. '+c.claim+'. '+c.status+'. '+c.explanation).join(' ')});
    if(data.scores){const half=data.scores.length/2;result.push({key:'judge',role:'Judge',text:'Judge. '+(data.winner==='Tie'?'The debate is a tie.':data.winner+' makes the stronger case.')+' Affirmative scores '+data.scores.slice(0,half).reduce((a,b)=>a+b,0)+' out of 100. Negative scores '+data.scores.slice(half).reduce((a,b)=>a+b,0)+' out of 100. '+data.why+'. '+(data.questionFeedback?'Question handling. Affirmative: '+data.questionFeedback.affirmative+'. Negative: '+data.questionFeedback.negative+'. ':'')+(data.improve||'')})}
    return result.sort((a,b)=>order.indexOf(a.key)-order.indexOf(b.key));
  }
  function createPlayer({synth,Utterance,onState=()=>{},getVoice=()=>null,getRate=()=>1}){
    let queue=[],active=null,paused=false,generation=0,error='';
    const state=()=>({speaking:Boolean(active),paused,pending:queue.length,key:active?.key||'',role:active?.role||'',error});
    const update=()=>onState(state());
    function next(){if(active||paused||!queue.length){update();return}const item=queue.shift();const utterance=new Utterance(item.text);const token=generation;active={...item,utterance};const voice=getVoice(item.role);if(voice){utterance.voice=voice;utterance.lang=voice.lang}else utterance.lang='en-US';utterance.rate=getRate();utterance.pitch={Affirmative:1.08,Negative:.92,Researcher:1.02,Judge:.88,Questioner:1.12,Rebuttal:.96}[item.role]||1;utterance.onend=()=>{if(token!==generation)return;active=null;next()};utterance.onerror=e=>{if(token!==generation)return;if(e.error==='interrupted'||e.error==='canceled'){active=null;next();return}error=e.error==='not-allowed'?'Your browser blocked audio. Click Listen to begin.':'Voice playback is unavailable. Try another voice or browser.';generation++;active=null;queue=[];paused=false;update()};update();try{synth.speak(utterance);prepareNext()}catch{utterance.onerror({error:'unavailable'})}}
    function prepareNext(){if(!synth.prepare||!queue.length)return;const item=queue[0];const utterance=new Utterance(item.text);utterance.voice=getVoice(item.role);synth.prepare(utterance)}
    function stop(){generation++;queue=[];active=null;paused=false;error='';synth.cancel();update()}
    function append(items){error='';for(const item of items)for(const text of chunks(item.text))queue.push({...item,text});next();if(active)prepareNext()}
    return {state,stop,append,play(items){stop();append(items)},pause(){if(!active&&!queue.length)return;paused=true;synth.pause();update()},resume(){paused=false;synth.resume();next()},dispose(){stop()}};
  }
  function init(getCurrent){
    const $=s=>document.querySelector(s),supported='Worker' in window&&'Audio' in window&&'WebAssembly' in window;
    const auto=$('#voiceAuto'),status=$('#voiceStatus');let prefs={auto:false,rate:1,engine:'kokoro',voices:{},kokoroVoices:{}};try{const saved=JSON.parse(localStorage.getItem('forum-voice')||'{}');prefs={...prefs,...saved,voices:saved.voices||{},kokoroVoices:saved.kokoroVoices||{}}}catch{}
    const persist=()=>{try{localStorage.setItem('forum-voice',JSON.stringify(prefs))}catch{}};
    if(!supported){status.textContent='Audio is unavailable in this browser. Try Chrome, Edge, or Safari.';document.querySelectorAll('[data-voice-control],#voiceAuto').forEach(el=>el.disabled=true);return {startSession(){},onEvent(){},refresh(){},stop(){},supported:false}}
    let voices=[],included=new Set(),cursor=0,live=false,player;
    const neural=ForumKokoro.createSynth({onStatus:message=>{
      $('#voiceModelStatus').textContent=message.message;
      const progress=$('#voiceModelProgress');progress.hidden=message.phase!=='download';if(Number.isFinite(message.progress))progress.value=message.progress;
      $('#voiceDownload').disabled=['loading','download'].includes(message.phase);$('#voiceDownload').textContent=(message.phase==='ready'||neural.ready())?'✓ Kokoro downloaded':'Download / retry Kokoro';
      if(prefs.engine==='kokoro'&&message.phase==='playing'&&player)sync(player.state());
      if(prefs.engine==='kokoro'&&['loading','download','generating','error'].includes(message.phase))status.textContent=message.message+(message.phase==='download'&&Number.isFinite(message.progress)?' '+message.progress+'%':'');
    }});
    const transport={speak:u=>{if(prefs.engine==='kokoro'){neural.speak(u);return}const native=new window.SpeechSynthesisUtterance(u.text);for(const prop of ['voice','lang','rate','pitch','onend','onerror'])if(u[prop]!=null)native[prop]=u[prop];window.speechSynthesis.speak(native)},cancel:()=>{neural.cancel();window.speechSynthesis?.cancel()},pause:()=>activeSynth().pause(),resume:()=>activeSynth().resume(),prepare:u=>{if(prefs.engine==='kokoro')neural.prepare(u)}};
    function activeSynth(){return prefs.engine==='kokoro'?neural:window.speechSynthesis}
    const Utterance=class{constructor(text){this.text=text}};
    $('#voiceEngine').value=prefs.engine;
    function voicePreference(){return prefs.engine==='kokoro'?prefs.kokoroVoices:prefs.voices}

    function selected(role){const id=voicePreference()[role];if(prefs.engine==='kokoro'){const defaults={Affirmative:'af_heart',Negative:'am_michael',Questioner:'bf_emma',Rebuttal:'am_fenrir',Researcher:'af_bella',Judge:'bm_george'};return voices.find(v=>v.voiceURI===(id||defaults[role]))||voices[0]}const english=voices.filter(v=>/^en[-_]/i.test(v.lang));const natural=english.filter(v=>! /^(Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Good News|Jester|Junior|Organ|Ralph|Superstar|Trinoids|Whisper|Wobble|Zarvox)$/i.test(v.name));const preferred=['Samantha','Daniel','Karen','Moira'].map(name=>natural.find(v=>v.name===name)).filter(Boolean);const defaults=[...new Set([...preferred,...natural])];return voices.find(v=>v.voiceURI===id)||defaults[roles.indexOf(role)]||defaults[0]||voices.find(v=>v.default)||voices[0]||null}
    function sync(state){status.textContent=state.error||(state.speaking?(state.paused?'Paused · ':'Speaking · ')+state.role:state.paused?'Audio paused':'Ready to listen');$('#voicePause').disabled=!state.speaking&&!state.pending;$('#voicePause').textContent=state.paused?'▶ Resume':'Ⅱ Pause';$('#voiceStop').disabled=!state.speaking&&!state.pending;document.querySelectorAll('[data-speech-key]').forEach(el=>el.classList.toggle('is-speaking',el.dataset.speechKey===state.key));document.querySelectorAll('[data-speak]').forEach(el=>{const playing=el.dataset.speak===state.key;el.setAttribute('aria-pressed',String(playing));el.textContent=playing?'◼ Stop':'▷ Listen'})}
    player=createPlayer({synth:transport,Utterance,getVoice:selected,getRate:()=>Number(prefs.rate)||1,onState:sync});
    auto.checked=Boolean(prefs.auto);$('#voiceRate').value=String(prefs.rate);
    function loadVoices(){voices=prefs.engine==='kokoro'?neural.getVoices():(window.speechSynthesis?.getVoices()||[]);for(const role of roles){const select=document.querySelector('[data-role-voice="'+role+'"]');select.replaceChildren();const available=voices.filter(v=>/^en[-_]/i.test(v.lang));const choices=available.length?available:voices;if(!choices.length){const option=document.createElement('option');option.textContent='Browser default';option.value='';select.append(option)}else for(const voice of choices){const option=document.createElement('option');option.value=voice.voiceURI;option.textContent=voice.name+' · '+voice.lang;select.append(option)}select.value=selected(role)?.voiceURI||''}$('#voiceHelp').textContent=prefs.engine==='kokoro'?'Kokoro generates neural speech on this device. Download the model once, then pick a voice for each role.':voices.length?'Voices come from your browser and device. Pick a voice for each role.':'Your browser will use its default voice. Voice choices may load in a moment.'}
    loadVoices();window.speechSynthesis?.addEventListener('voiceschanged',()=>{if(prefs.engine==='browser')loadVoices()});
    $('#voiceDownload').onclick=()=>neural.load().catch(()=>{});
    $('#voiceEngine').onchange=e=>{stop();prefs.engine=e.target.value;if(prefs.engine==='browser'&&!window.speechSynthesis){prefs.engine='kokoro';e.target.value='kokoro';status.textContent='System voices are unavailable in this browser.'}persist();loadVoices()};
    function flush(){if(!live||!prefs.auto)return;const available=new Map(entries(getCurrent()?.data).map(e=>[e.key,e]));while(cursor<order.length&&available.has(order[cursor])){const key=order[cursor++];if(!included.has(key)){included.add(key);player.append([available.get(key)])}}}
    function stop(){live=false;player.stop()}
    auto.onchange=()=>{prefs.auto=auto.checked;persist();if(!auto.checked){stop();return}const session=getCurrent();live=Boolean(session?.live&&!session.complete&&!session.error);if(live){for(const item of entries(session.data))included.add(item.key);flush()}};$('#voiceRate').onchange=e=>{prefs.rate=Number(e.target.value);persist()};
    $('#voiceSettings').onclick=()=>$('#voiceDialog').showModal();$('#closeVoice').onclick=()=>$('#voiceDialog').close();
    document.querySelectorAll('[data-role-voice]').forEach(select=>select.onchange=()=>{voicePreference()[select.dataset.roleVoice]=select.value;persist()});
    document.querySelectorAll('[data-preview-role]').forEach(button=>button.onclick=()=>{stop();const role=button.dataset.previewRole;player.play([{key:'preview',role,text:'Hello. I am the '+role+'. I will help you explore the resolution.'}])});
    $('#voicePlay').onclick=()=>{const items=entries(getCurrent()?.data);if(!items.length)return;live=false;player.play(items)};$('#voicePause').onclick=()=>player.state().paused?player.resume():player.pause();$('#voiceStop').onclick=stop;
    $('#output').addEventListener('click',e=>{const button=e.target.closest('[data-speak]');if(!button)return;const key=button.dataset.speak;if(player.state().key===key){stop();return}let item=entries(getCurrent()?.data).find(item=>item.key===key);if(key.startsWith('claim:')){const claim=getCurrent()?.data.review?.claims[Number(key.split(':')[1])];if(claim)item={key,role:'Researcher',text:'Researcher. '+claim.side+'. '+claim.claim+'. '+claim.status+'. '+claim.explanation}}if(item){live=false;player.play([item])}});
    window.addEventListener('pagehide',()=>{player.stop();neural.dispose()});
    sync(player.state());
    return {supported:true,skipExisting(){for(const item of entries(getCurrent()?.data))included.add(item.key);flush()},startSession(){player.stop();included=new Set();cursor=0;live=Boolean(prefs.auto);if(live)player.play([{key:'intro',role:'Judge',text:'Your debate team is getting ready.'}])},onEvent(event){if(['case','questions','challenges','answers','rebuttal','research','verdict'].includes(event.type))flush()},refresh(){const any=entries(getCurrent()?.data).length>0;$('#voicePlay').disabled=!any;sync(player.state())},stop};
  }
  globalThis.ForumSpeech={createPlayer,entries,chunks,init};
})();
