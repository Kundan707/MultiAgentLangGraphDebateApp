import {runDebate} from '../worker/index.js';
try{await runDebate(process.env,'Schools should ban smartphones during the school day.',e=>{if(e.type!=='heartbeat')console.log(JSON.stringify(e))},{signal:AbortSignal.timeout(230000)});console.log('LIVE_SMOKE_PASSED')}catch(e){console.error('LIVE_SMOKE_FAILED: '+e.message);process.exitCode=1}
