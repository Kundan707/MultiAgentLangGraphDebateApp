import {readFile,mkdir,writeFile} from 'node:fs/promises';
const assets={};
for(const [path,type] of [['/','text/html'],['/style.css','text/css'],['/app.js','text/javascript'],['/voice.js','text/javascript']]){assets[path]={body:await readFile('public/'+(path==='/'?'index.html':path.slice(1)),'utf8'),type:type+'; charset=utf-8'}}
const backend=await readFile('worker/index.js','utf8');
await mkdir('dist/server',{recursive:true});await mkdir('dist/.openai',{recursive:true});
await writeFile('dist/server/index.js','const ASSETS = '+JSON.stringify(assets)+';\n'+backend.replace("import { ASSETS } from './assets.js';",''));
await writeFile('dist/.openai/hosting.json',await readFile('.openai/hosting.json'));
console.log('Built Worker with embedded assets.');
