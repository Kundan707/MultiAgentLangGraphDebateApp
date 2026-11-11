const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const topics={phones:'Schools should ban smartphones during the school day.',homework:'Schools should eliminate mandatory homework.',uniforms:'Schools should require students to wear uniforms.',ai:'Students should be allowed to use AI tools for school assignments.'};
let features={memory:false,coordinator:false};let checkingMemory=false;let current=null,tab='debate',running=false,controller=null,ready=false;let sessions=[];try{const saved=JSON.parse(localStorage.getItem('forum-sessions')||'[]');if(Array.isArray(saved))sessions=saved.filter(s=>s?.data&&typeof s.data.resolution==='string').slice(0,20)}catch{}function persist(){try{localStorage.setItem('forum-sessions',JSON.stringify(sessions.slice(0,20)))}catch{}$('#historyCount').textContent=sessions.length}persist();
const audio=ForumSpeech.init(()=>current);
function save(){const i=sessions.findIndex(s=>s.id===current.id);if(i<0)sessions.unshift(current);else sessions[i]=current;sessions=sessions.slice(0,20);persist()}
function sourceLinks(sources=[]){return sources.filter(s=>{try{return ['https:','http:'].includes(new URL(s.url).protocol)}catch{return false}}).map(s=>`<a class="source-link" target="_blank" rel="noopener noreferrer" href="${esc(s.url)}">${esc(s.title||s.url)} ↗</a>`).join('')}
function message(role,title,body,round='OPENING CASE',speechKey=''){const key=speechKey||({Affirmative:round==='REBUTTAL'?'ar':'a',Negative:round==='REBUTTAL'?'nr':'n',Researcher:'research',Judge:'judge',Questioner:'questions',Rebuttal:'challenges',Answers:'aa'}[role]||'');return `<article class="message" data-speech-key="${esc(key)}"><div class="message-head"><span class="pill">${esc(role)}</span>${esc(title)}<small>${esc(round)}</small>${key&&audio.supported?`<button class="listen-button" data-speak="${esc(key)}" aria-label="Listen to ${esc(role)}: ${esc(title)}" aria-pressed="false">▷ Listen</button>`:''}</div>${body}</article>`}
function caseBody(c,sources){return `<h4>1. ${esc(c[0])}</h4><p>${esc(c[1])}</p><h4>2. ${esc(c[2])}</h4><p>${esc(c[3])}</p>${sourceLinks(sources)}`}
function promptsBody(groups,challenge=false){return ['affirmative','negative'].map(side=>`<h4>Questions for the ${side==='affirmative'?'Affirmative':'Negative'}</h4>`+groups[side].map((q,i)=>`<div class="cross-question"><strong>${challenge?'R':'Q'}${i+1}. ${esc(q.question)}</strong><p>${challenge?'Weakness: '+esc(q.weakness)+'<br>Counterargument: '+esc(q.counterargument):'Why it matters: '+esc(q.purpose)}</p></div>`).join('')).join('')}
function answersBody(answers){return answers.map(a=>`<div class="cross-question"><strong>${esc(a.id)}. ${esc(a.question)}</strong><p>${esc(a.answer)}</p></div>`).join('')}
function sideLabel(side, data=current?.data){
  if(!data?.debater)return side;
  return side===data.debater.side?data.debater.name+' ('+side+')':'AI opponent ('+side+')';
}
function resultTitle(data){
  return data.winner==='Tie'?'Both sides are equally convincing':sideLabel(data.winner,data)+' makes the stronger case';
}
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let dictation = null;

function finishDictation(message) {
  if (!dictation) return;
  const {form, button, label} = dictation;
  dictation = null;
  button.textContent = '🎙 Dictate';
  button.setAttribute('aria-label', 'Dictate ' + label);
  form.querySelectorAll('button').forEach(control => { control.disabled = false; });
  form.querySelector('[data-mic-status]').textContent = message;
}

function cancelDictation() {
  if (!dictation) return;
  const {recognition} = dictation;
  finishDictation('Dictation stopped. You can edit the text or continue dictating.');
  recognition.abort();
}

$('#humanTurn').addEventListener('click', event => {
  const button = event.target.closest('[data-dictate]');
  if (!button) return;
  const form = event.currentTarget;
  const status = form.querySelector('[data-mic-status]');
  if (dictation) {
    if (dictation.button !== button || dictation.stopping) return;
    dictation.stopping = true;
    status.textContent = 'Finishing dictation…';
    // Stop returns any final words captured before the click.
    try { dictation.recognition.stop(); } catch { cancelDictation(); }
    return;
  }
  const field = form.elements.namedItem(button.dataset.dictate);
  const label = field.labels[0].textContent;
  let recognition;
  try {
    recognition = new SpeechRecognition();
    recognition.lang = document.documentElement.lang || 'en';
    recognition.continuous = true;
    recognition.interimResults = false;
    const session = {recognition, form, button, label, received: false, stopping: false};
    dictation = session;
    recognition.onstart = () => {
      if (dictation === session && !session.stopping) status.textContent = 'Listening for ' + label + '…';
    };
    recognition.onresult = ({results, resultIndex}) => {
      if (dictation !== session) return;
      const phrases = [];
      for (let i = resultIndex; i < results.length; i++) {
        if (results[i].isFinal) phrases.push(results[i][0].transcript.trim());
      }
      const text = phrases.join(' ').trim();
      if (!text) return;
      const separator = field.value && !/\s$/.test(field.value) ? ' ' : '';
      const room = field.maxLength - field.value.length;
      if (room > separator.length) {
        field.value += (separator + text).slice(0, room);
        field.dispatchEvent(new Event('input', {bubbles: true}));
        session.received = true;
      }
      if (room <= separator.length || field.value.length >= field.maxLength) {
        finishDictation('This field reached its character limit. You can edit the transcript.');
        recognition.abort();
      }
    };
    recognition.onerror = ({error}) => {
      if (dictation !== session) return;
      const messages = {
        'not-allowed': 'Microphone access was denied. Allow access in your browser or type your response.',
        'service-not-allowed': 'This browser could not start speech recognition. Try another browser or type your response.',
        'audio-capture': 'No microphone is available. Check your microphone or type your response.',
        'no-speech': 'No speech was detected. Try again or type your response.',
        'network': 'The browser’s speech service could not connect. Try again or type your response.'
      };
      finishDictation(messages[error] || 'Dictation ended. You can try again or type your response.');
    };
    recognition.onend = () => {
      if (dictation !== session) return;
      finishDictation(session.received ? 'Dictation finished. Review or edit the transcript before submitting.'
        : 'No words were captured. Try again or type your response.');
    };
    audio.stop();
    form.querySelectorAll('button').forEach(control => { control.disabled = control !== button; });
    button.textContent = '■ Stop dictation';
    button.setAttribute('aria-label', 'Stop dictating ' + label);
    status.textContent = 'Starting microphone for ' + label + '…';
    recognition.start();
  } catch {
    finishDictation('The microphone could not start. Try again or type your response.');
    status.textContent = 'The microphone could not start. Try again or type your response.';
  }
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) cancelDictation();
});
window.addEventListener('pagehide', cancelDictation);

function renderHumanTurn(){
  const form=$('#humanTurn');
  const turn=current?.humanTurn;
  form.hidden=!turn||running||Boolean(current.handoff);
  const key=turn?current.coordinatorId+':'+turn.phase:'';
  if(form.hidden||form.dataset.turn!==key)cancelDictation();
  if(form.dataset.turn===key)return;
  form.dataset.turn=key;
  if(!turn){form.replaceChildren();return}
  const opening=turn.phase==='opening';
  const field=(label,id,max)=>`<div class="dictation-field"><label for="${id}">${esc(label)}</label><button type="button" class="dictate-button" data-dictate="${id}" aria-label="Dictate ${esc(label)}" aria-describedby="micStatus"${SpeechRecognition?'':' disabled'}>🎙 Dictate</button></div><textarea class="notes" id="${id}" name="${id}" maxlength="${max}" required></textarea>`;
  form.innerHTML=`<h3>${esc(current.data.debater.name)}, it’s your turn</h3><p>${esc(current.data.resolution)}</p><p>You are ${esc(current.data.debater.side)}. ${opening?'Make two claims and support each with reasoning and evidence. Include source links if you have them.':'Answer the four questions and write a rebuttal to the AI’s opening case.'}</p>`+
    `<p class="mic-status" id="micStatus" data-mic-status role="status">${SpeechRecognition?'Select Dictate beside a field. Your browser may send audio to its speech service.':'This browser does not expose speech recognition. Open this app in a browser with speech recognition, or use your device’s dictation directly in a text field.'}</p>`+
    (opening?field('Claim 1','claim1',2000)+field('Reasoning and evidence for claim 1','evidence1',2000)+field('Claim 2','claim2',2000)+field('Reasoning and evidence for claim 2','evidence2',2000):
      turn.questions.map(q=>field(q.id+'. '+q.question,q.id,1500)).join('')+field('Your rebuttal','rebuttal',2000))+
    `<button type="submit">${opening?'Submit opening case':'Submit answers and rebuttal'}</button>`;
}
$('#humanTurn').onsubmit=e=>{
  e.preventDefault();
  if(dictation)return;
  const form=e.currentTarget;
  const turn=current.humanTurn;
  const ids=turn.phase==='opening'?['claim1','evidence1','claim2','evidence2']:[...turn.questions.map(q=>q.id),'rebuttal'];
  const fields=ids.map(id=>form.elements.namedItem(id));
  for(const field of fields){
    field.setCustomValidity(field.value.trim()?'':'Please enter a response.');
    if(!field.reportValidity())return;
  }
  const values=fields.map(field=>field.value.trim());
  const submission=turn.phase==='opening'?{phase:'opening',case:values}:{phase:'response',answers:values.slice(0,4),rebuttal:values[4]};
  startDebate({resumeId:current.coordinatorId,resolutionOverride:current.data.resolution,submission});
};
$('#humanTurn').oninput=e=>e.target.setCustomValidity?.('');
$('#debateSetup').onchange=()=>{
  $('#humanSetup').hidden=$('input[name=debateFormat]:checked').value!=='human';
};
$('#debaterName').oninput=e=>e.target.setCustomValidity('');
function render(){if(!current)return;const d=current.data;const live=current.live;const half=d.scores?.length===8?4:3;const rubric=half===4?['Reasoning & feasibility / 25','Evidence quality / 25','Rebuttal effectiveness / 25','Question handling / 25']:['Reasoning / 35','Response & feasibility / 35','Evidence / 30'];$('#flags').textContent=d.review?.claims?.filter(c=>c.status!=='Supported').length??d.claims?.length??0;$('#sessionState').textContent=running?(current.stage||'STARTING AGENTS').toUpperCase():(current.handoff||current.humanTurn)?'WAITING FOR YOUR INPUT':current.error?'SESSION INTERRUPTED':current.complete?'SESSION COMPLETE':'SAVED PRACTICE';$('#export').disabled=false;$('#output').setAttribute('aria-busy',String(running));const progress=running?`<div class="notice running" role="status">${esc(current.stage||'Connecting your debate team…')}…</div>`:'';const error=current.error?`<div class="notice error" role="alert">${esc(current.error)} Your completed rounds are preserved. Start again to run a new debate.</div>`:'';const handoff=current.handoff||(!running&&!current.complete&&!current.humanTurn&&current.coordinatorId&&current.error?{reason:current.error,question:'You can resume from the last completed step.'}:null);const intervention=handoff?`<div class="handoff-panel" role="region" aria-label="Coordinator needs your input"><strong>The coordinator needs your input</strong><p>${esc(handoff.reason)}</p><p>${esc(handoff.question)}</p><label for="handoffReply">Clarification or what you fixed (optional)</label><textarea id="handoffReply" class="notes" maxlength="2000" placeholder="Clarify the policy, or describe the issue you fixed…"></textarea><button data-resume-current>Resume from saved step</button></div>`:'';const disclosure=`<div class="notice">${live?(current.fromMemory?'Saved debate · '+new Date(current.date).toLocaleDateString()+' · ':(d.debater?'Human vs. AI · ':'Live AI debate · '))+esc(current.model||'claude-sonnet-5')+' · Check important claims against the linked sources.':'Archived practice simulation · Prepared cases and fixed illustrative scores from the earlier version.'}</div>`;
if(tab==='debate'){$('#output').innerHTML=disclosure+(d.a?message('Affirmative',d.debater?sideLabel('Affirmative'):'The case for',caseBody(d.a,d.aSources)):'')+(d.n?message('Negative',d.debater?sideLabel('Negative'):'The case against',caseBody(d.n,d.nSources)):'')+(d.questions?message('Questioner','Testing both sides',promptsBody(d.questions),'CROSS-EXAMINATION'):'')+(d.challenges?message('Rebuttal','Challenging the cases',promptsBody(d.challenges,true),'REBUTTAL CHALLENGES'):'')+(d.aa?message('Affirmative','Answering the questions',answersBody(d.aa),'CROSS-EXAMINATION','aa'):'')+(d.na?message('Negative','Answering the questions',answersBody(d.na),'CROSS-EXAMINATION','na'):'')+(d.ar?message('Affirmative','Responding to the challenge',`<p>${esc(d.ar)}</p>`,'REBUTTAL'):'')+(d.nr?message('Negative','Testing the response',`<p>${esc(d.nr)}</p>`,'REBUTTAL'):'')+(d.review?message('Researcher','Following the evidence',`<p>${esc(d.review.summary)}</p><p>Open Evidence review for the claim-by-claim source audit.</p>`,'SOURCE AUDIT'):'')+progress+error+intervention;
}else if(tab==='evidence'){$('#output').innerHTML=disclosure+(d.review?`<div class="notice">${esc(d.review.summary)}</div>`+d.review.claims.map((c,i)=>message(c.status,`Claim ${i+1} · ${c.side}`,`<h4>${esc(c.claim)}</h4><p>${esc(c.explanation)}</p>${sourceLinks(c.source_urls.map(url=>(d.review.sources||[]).find(s=>s.url===url)||{url,title:url}))}`,'SOURCE REVIEW',`claim:${i}`)).join('')+`<div class="message"><h4>Sources consulted</h4>${sourceLinks(d.review.sources)}</div>`:d.claims?d.claims.map((c,i)=>message('Unverified',`Claim ${i+1}`,`<p>${esc(c)}</p>`)).join(''):`<div class="empty"><h3>The Researcher is waiting for both cases.</h3><p>The source audit will appear here when research finishes.</p></div>`)+progress+error+intervention+`<div class="message"><h4>Your evidence notes</h4><p>Record citations, limitations, and which claim each source supports.</p><textarea id="notes" class="notes" aria-label="Evidence notes" placeholder="Author, title, year, URL, and what the evidence supports…">${esc(current.notes||'')}</textarea></div>`;$('#notes').oninput=e=>{current.notes=e.target.value;if(current.complete||current.error)save()};
}else{$('#output').innerHTML=disclosure+(d.scores?message('Judge',resultTitle(d),`<div class="scorecards"><div class="score"><span>${esc(sideLabel("Affirmative"))}</span><strong>${d.scores.slice(0,half).reduce((a,b)=>a+b,0)}<small>/100</small></strong></div><div class="score"><span>${esc(sideLabel("Negative"))}</span><strong>${d.scores.slice(half).reduce((a,b)=>a+b,0)}<small>/100</small></strong></div></div>${rubric.map((name,i)=>`<div class="criterion"><span>${name}</span><span>${d.scores[i]} — ${d.scores[i+half]}</span></div>`).join('')}${d.questionFeedback?`<h4>How the questions affected the result</h4><p><strong>Affirmative:</strong> ${esc(d.questionFeedback.affirmative)}</p><p><strong>Negative:</strong> ${esc(d.questionFeedback.negative)}</p>`:''}<h4>What made the difference</h4><p>${esc(d.why)}</p><h4>Make your next case stronger</h4><p>${esc(d.improve||'Support disputed claims with relevant research and respond to the strongest opposing argument.')}</p><span class="pill">${live?'AI evaluation of this debate · advisory scores':'Fixed illustrative assessment'}</span>`,'EXPLAINED VERDICT'):`<div class="empty"><h3>The Judge is listening.</h3><p>The Judge scores reasoning, evidence, rebuttal effectiveness, and question handling — 25 points each. A verdict follows both sides’ answers and the source review.</p></div>`)+progress+error+intervention}renderHumanTurn();audio.refresh()}
function setTab(t){tab=t;document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===t));render()}
function lock(value){running=value;$('#run').disabled=value||(!ready&&!features.memory);$('#run').innerHTML=value?'Debating… <span>↗</span>':'Start debate <span>↗</span>';$('#cancel').hidden=!value;$('#resolution').disabled=value;$('#debateSetup').disabled=value;document.querySelectorAll('[data-topic]').forEach(b=>b.disabled=value);$('#history').disabled=value;$('.status').innerHTML=value?'<i></i> Your team is debating':'<i></i> '+(ready?'Live agents ready':'Setup needed')}
function event(e){if(e.type==='heartbeat')return;if(e.type==='session'){current.coordinatorId=e.session_id;if(e.debater)current.data.debater=e.debater;return}if(e.type==='replay_start'){current.replaying=true;return}if(e.type==='replay_end'){current.replaying=false;audio.skipExisting?.();return}if(e.type==='coordinator'){current.coordinatorStatus=e.message;$('#coordinatorStatus').textContent=e.message;return}if(e.type==='human_turn')current.humanTurn={phase:e.phase,questions:e.questions};if(e.type==='handoff'){current.handoff={reason:e.reason,question:e.question};current.coordinatorId=e.session_id}if(e.type==='memory_saved'){$('#memoryNotice').textContent='Debate saved for next time.';current.memoryId=e.id}const d=current.data;if(e.type==='progress')current.stage=e.role+' is working';if((e.type==='case'||e.type==='rebuttal')&&e.role===d.debater?.side)delete current.humanTurn;if(e.type==='case'){const key=e.role==='Affirmative'?'a':'n';d[key]=e.case;d[key+'Sources']=e.sources}if(e.type==='questions')d.questions={affirmative:e.affirmative,negative:e.negative};if(e.type==='challenges')d.challenges={affirmative:e.affirmative,negative:e.negative};if(e.type==='answers')d[e.role==='Affirmative'?'aa':'na']=e.answers;if(e.type==='rebuttal')d[e.role==='Affirmative'?'ar':'nr']=e.rebuttal;if(e.type==='research')d.review={claims:e.claims,summary:e.summary,sources:e.sources};if(e.type==='verdict')Object.assign(d,{winner:e.winner,scores:e.scores,why:e.why,improve:e.improve,questionFeedback:e.question_feedback,rubricVersion:e.rubricVersion});if(e.type==='error'){current.error=e.error;throw Error(e.error)}if(e.type==='complete'){current.complete=true;current.model=e.model;if(d.debater)setTab('verdict')}render();if(!current.replaying)audio.onEvent(e)}
async function memoryChoice(result){
  const dialog=$('#memoryDialog');$('#memoryExplanation').textContent=result.error||'We found previous debates related to this resolution. Open one, or run a new debate.';
  $('#memoryMatches').innerHTML=(result.matches||[]).map(match=>`<button class="history-item" data-memory-id="${esc(match.id)}">${esc(match.resolution)}<small>${new Date(match.date).toLocaleString()} · ${match.exact?'Same resolution':'Related resolution'} · ${esc(match.winner||'Judged debate')}</small></button>`).join('');
  return new Promise(resolve=>{const finish=value=>{dialog.close();dialog.oncancel=null;resolve(value)};$('#closeMemory').onclick=()=>finish({action:'cancel'});$('#newMemory').onclick=()=>finish({action:'new'});dialog.oncancel=e=>{e.preventDefault();finish({action:'cancel'})};$('#memoryMatches').querySelectorAll('[data-memory-id]').forEach(button=>button.onclick=()=>finish({action:'open',id:button.dataset.memoryId}));dialog.showModal()});
}
async function openRemembered(id){const response=await fetch('/api/debates/'+encodeURIComponent(id));if(!response.ok)throw Error('The saved debate could not be opened.');audio.stop();current=await response.json();current.fromMemory=true;$('#resolution').value=current.data.resolution;save();setTab('debate');$('#memoryNotice').textContent='Opened a saved debate. No agents were run.'}
async function startDebate({resumeId=null,humanInput='',resolutionOverride=null,submission=null}={}){
  if(running||checkingMemory)return;const resolution=(resolutionOverride||$('#resolution').value).trim();if(resolution.length<12){$('#resolution').setCustomValidity('Enter a complete resolution of at least 12 characters.');$('#resolution').reportValidity();return}$('#resolution').setCustomValidity('');
  let debater;
  if(!resumeId&&$('input[name=debateFormat]:checked').value==='human'){
    const name=$('#debaterName');
    const side=$('#debaterSide');
    name.setCustomValidity(name.value.trim()?'':'Enter your name.');
    if(!name.reportValidity()||!side.reportValidity())return;
    debater={name:name.value.trim(),side:side.value};
  }
  let forceNew=false;checkingMemory=true;$('#run').disabled=true;$('#debateSetup').disabled=true;
  try{if(features.memory&&!resumeId){$('#run').textContent='Checking previous debates…';$('#memoryNotice').textContent='Searching previous debates…';const check=await fetch('/api/debates/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resolution})});const result=await check.json();if(!check.ok)throw Error(result.error||'Memory lookup failed.');if(result.matches?.length||result.requires_human){const choice=await memoryChoice(result);if(choice.action==='cancel'){$('#memoryNotice').textContent='No debate started.';return}if(choice.action==='open'){await openRemembered(choice.id);return}forceNew=true}$('#memoryNotice').textContent=forceNew?'You chose a fresh debate.':'No related debate found. Starting fresh.'}}
  catch(error){$('#memoryNotice').textContent=error.message;return}
  finally{checkingMemory=false;$('#debateSetup').disabled=false;$('#run').disabled=!ready&&!features.memory;$('#run').innerHTML='Start debate <span>↗</span>'}
  audio.stop();if(!resumeId||current?.coordinatorId!==resumeId)current={id:Date.now(),date:new Date().toISOString(),live:true,model:$('.demo').dataset.model,data:{resolution,...(debater?{debater}:{})},notes:''};delete current.error;delete current.handoff;current.complete=false;current.fromMemory=false;current.stage=resumeId?'Resuming saved steps':'Connecting your debate team';audio.startSession();controller=new AbortController();lock(true);setTab('debate');$('.debate-section').scrollIntoView({behavior:'smooth',block:'start'});
  try{const response=await fetch('/api/debate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resolution,force_new:forceNew,...(debater?{debater}:{}),...(submission?{submission}:{}),...(resumeId?{session_id:resumeId,human_input:humanInput}:{})}),signal:controller.signal});if(!response.ok){let err;try{err=(await response.json()).error}catch{}throw Error(err||'The debate service could not be reached. Please try again.')}if(!response.headers.get('content-type')?.includes('application/x-ndjson'))throw Error('Please sign in again and reload the debate room.');const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';while(true){const {done,value}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});let end;while((end=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);if(line.trim())event(JSON.parse(line))}if(done)break}if(!current.complete&&!current.handoff&&!current.humanTurn)throw Error('The connection ended before the debate finished. You can resume saved steps.')}catch(error){current.error=error.name==='AbortError'?'Debate stopped.':error.message}finally{lock(false);save();render();controller=null;if(!$('#humanTurn').hidden){$('#humanTurn').scrollIntoView({block:'nearest'});$('#humanTurn textarea')?.focus({preventScroll:true})}}
}
$('#run').onclick=()=>startDebate();
$('#output').addEventListener('click',e=>{if(e.target.closest('[data-resume-current]')&&current?.coordinatorId)startDebate({resumeId:current.coordinatorId,humanInput:$('#handoffReply')?.value||'',resolutionOverride:current.data.resolution})});

$('#cancel').onclick=()=>{audio.stop();controller?.abort()};document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));document.querySelectorAll('[data-topic]').forEach(b=>b.onclick=()=>{$('#resolution').value=topics[b.dataset.topic];document.querySelectorAll('[data-topic]').forEach(x=>x.classList.toggle('selected',x===b))});$('#resolution').oninput=()=>{$('#resolution').setCustomValidity('');document.querySelectorAll('[data-topic]').forEach(x=>x.classList.toggle('selected',topics[x.dataset.topic]===$('#resolution').value.trim()))};
$('#history').onclick=async()=>{const list=$('#historyList');list.innerHTML=sessions.length?sessions.map((s,i)=>`<button class="history-item" data-session="${i}">${esc(s.data.resolution)}<small>${new Date(s.date).toLocaleString()} · ${s.live?(s.complete?(s.data.debater?'Human vs. AI':'Live AI debate'):s.humanTurn?'Waiting for your turn':'Unfinished live debate'):'Archived practice simulation'}</small></button>`).join(''):'<p class="notice">Your saved debates will appear here after your first session.</p>';list.querySelectorAll('button').forEach(b=>b.onclick=()=>{audio.stop();current=sessions[Number(b.dataset.session)];$('#resolution').value=current.data.resolution;setTab('debate');$('#historyDialog').close()});if(features.coordinator){try{const response=await fetch('/api/sessions');const pending=(await response.json()).sessions||[];if(pending.length){list.insertAdjacentHTML('beforeend','<h3 class="pending-title">Resume unfinished debates</h3>'+pending.map(item=>`<button class="history-item" data-checkpoint="${esc(item.id)}" data-resolution="${esc(item.resolution)}">${esc(item.resolution)}<small>${esc(item.status)} · Saved coordinator checkpoint</small></button>`).join(''));list.querySelectorAll('[data-checkpoint]').forEach(button=>button.onclick=()=>{$('#historyDialog').close();$('#resolution').value=button.dataset.resolution;startDebate({resumeId:button.dataset.checkpoint,resolutionOverride:button.dataset.resolution})})}}catch{}}$('#historyDialog').showModal()};$('#closeHistory').onclick=()=>$('#historyDialog').close();$('#workspace').onclick=()=>window.scrollTo({top:0,behavior:'smooth'});
$('#export').onclick=()=>{if(!current)return;const d=current.data;const crossNotes=[['QUESTIONER',d.questions],['REBUTTAL AGENT',d.challenges],['AFFIRMATIVE ANSWERS',d.aa],['NEGATIVE ANSWERS',d.na],['JUDGE — QUESTION HANDLING',d.questionFeedback]].filter(([,v])=>v).map(([label,v])=>label+'\n'+JSON.stringify(v,null,2)).join('\n\n');const txt=`THE FORUM — ${current.live?(d.debater?'HUMAN VS. AI':'LIVE AI DEBATE'):'ARCHIVED PRACTICE SIMULATION'}\nResolution: ${d.resolution}${d.debater?'\nDebater: '+sideLabel(d.debater.side,d):''}\n\nAFFIRMATIVE\n${d.a?.join('\n\n')||'Pending'}\nRebuttal: ${d.ar||'Pending'}\n\nNEGATIVE\n${d.n?.join('\n\n')||'Pending'}\nRebuttal: ${d.nr||'Pending'}\n\nRESEARCH REVIEW\n${d.review?d.review.claims.map(c=>c.side+': '+c.claim+'\n'+c.status+' — '+c.explanation+'\n'+c.source_urls.join('\n')).join('\n\n'):'Pending'}\n\nJUDGE\n${d.winner?resultTitle(d):'Pending'}\n${d.why||''}\nScores: ${d.scores?.join(', ')||'Pending'}\n${d.improve||''}\n\n${crossNotes}\n\nYOUR NOTES\n${current.notes||''}`;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([txt],{type:'text/plain'}));a.download='forum-debate-notes.txt';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
$('#run').disabled=true;fetch('/api/config').then(r=>{if(!r.ok)throw Error();return r.json()}).then(config=>{ready=config.ready;features={memory:Boolean(config.memory),coordinator:Boolean(config.coordinator)};$('#coordinatorBar').hidden=!features.coordinator;$('#humanModeLabel').hidden=!features.coordinator;$('input[value=human]').disabled=!features.coordinator;$('.demo').textContent=ready?'Live AI · web research enabled':'Live agents · setup needed';$('.demo').dataset.model=config.model;lock(false)}).catch(()=>{ready=false;$('.demo').textContent='Live service unavailable · reload to retry';lock(false)});
