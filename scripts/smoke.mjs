import {runDebate} from '../worker/index.js';
import {writeFile} from 'node:fs/promises';
const events=[];
try{await runDebate(process.env,'Schools should ban smartphones during the school day.',e=>{events.push(e);console.log(JSON.stringify({type:e.type,role:e.role,...(e.type==='verdict'?{winner:e.winner,scores:e.scores,questionFeedback:Boolean(e.question_feedback)}:{})}))},{signal:AbortSignal.timeout(350000)});await writeFile('/private/tmp/forum-six-role-smoke.json',JSON.stringify(events));console.log('LIVE_SMOKE_PASSED')}catch(e){console.error('LIVE_SMOKE_FAILED: '+e.message);process.exitCode=1}
