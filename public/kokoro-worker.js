// Kokoro runs on this device in a worker; debate text is never sent to a TTS API.
let modelPromise=null,model=null,sequence=Promise.resolve(),generation=0;
const send=data=>self.postMessage(data);
async function load(){
  if(model)return model;
  if(!modelPromise)modelPromise=(async()=>{
    send({type:'status',phase:'loading',message:'Loading Kokoro runtime…'});
    const {KokoroTTS}=await import('/kokoro-lib.js');
    const files=new Map();
    model=await KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX',{
      dtype:'q8',device:'wasm',progress_callback:event=>{
        if(event.status==='progress'){
          files.set(event.file,{loaded:event.loaded||0,total:event.total||0});
          const all=[...files.values()],total=all.reduce((a,f)=>a+f.total,0),loaded=all.reduce((a,f)=>a+f.loaded,0);
          send({type:'status',phase:'download',message:'Downloading Kokoro model…',progress:total?Math.round(loaded/total*100):null,loaded,total});
        }else if(event.status==='done')send({type:'status',phase:'loading',message:'Preparing neural voices…'});
      }
    });
    send({type:'status',phase:'ready',message:'Kokoro ready · runs on your device'});return model;
  })().catch(error=>{modelPromise=null;throw error});
  return modelPromise;
}
self.onmessage=event=>{
  const request=event.data;
  if(request.type==='cancel'){generation=request.generation;return}
  if(request.type==='load'){load().then(()=>send({type:'loaded',id:request.id})).catch(error=>send({type:'error',id:request.id,message:String(error.message||error)}));return}
  sequence=sequence.catch(()=>{}).then(async()=>{
    if(request.generation!==generation){send({type:'cancelled',id:request.id});return}
    const tts=await load();
    if(request.generation!==generation){send({type:'cancelled',id:request.id});return}
    const audio=await tts.generate(request.text,{voice:request.voice,speed:1});
    if(request.generation!==generation){send({type:'cancelled',id:request.id});return}
    send({type:'audio',id:request.id,blob:audio.toBlob()});
  }).catch(error=>send({type:'error',id:request.id,message:String(error.message||error)}));
};
