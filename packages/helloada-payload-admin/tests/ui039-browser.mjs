import { build } from 'esbuild'
import { compile } from 'sass'
import { mkdir, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

// Bundle the actual production component. Only application boundaries are
// replaced; dialogs, attachment handlers and layout remain the package source.
const root = process.cwd()
const out = '/tmp/opencode/ui039'
await mkdir(out, { recursive: true })
const virtual = {
  'fetchHelloAda': `export async function fetchHelloAda(path, options={}) {
    const url = String(path);
    let body = {};
    if (url.includes('/workspace')) body = {site:{name:'Fixture site',url:'https://fixture.invalid'},routes:[{path:'/',kind:'page',collection:'pages',sourceId:'page-1'}],documents:[{id:'1',collection:'pages',sourceId:'page-1',slug:'home',title:'Home',status:'draft',draftHash:'draft-hash'}],ada:{configured:true}};
    else if (url.includes('/api/helloada/ada?')) body = {phase:'workspace',website_present:true};
    else if (url.includes('/page-fields')) body = {fields:Array.from({length:18},(_,i)=>{const text=('Body '+i+' ').repeat(i===0?24:12); return {id:'field-'+i,key:'field-'+i,label:i===0?'Heading — '+('long field title ').repeat(12):'Long body '+i,section:'Main content — '+('section details ').repeat(12),editorVisible:true,editable:true,status:'editable',type:'text',value:text,text,contentEdit:{collection:'pages',documentId:'1',field:'field-'+i,expectedValue:text}}})};
    else if (url.includes('/drafts')) body = {drafts:[]};
    else if (url.includes('/conversations')) body = {conversations:[]};
    else if (url.includes('/api/helloada/ada')) body = {jobs:[]};
    if (url.includes('/page-fields')) window.__pageFieldCount = body.fields.length;
    return {ok:true,status:200,json:async()=>body};
  }`,
  'translations': `const labels={'owner.publishTitle':'Publish changes?','owner.publishNote':'Review this long publication summary. '.repeat(32),'owner.keepReviewing':'Keep reviewing','owner.publishChanges':'Publish changes','workspace.quickEditLabel':'Quick editing','workspace.quickEditButton':'Edit field','workspace.quickEditFieldButton':'Edit field','workspace.pageClose':'Close','workspace.applyFieldChange':'Apply field change'}; const t=(key)=>labels[key]||key; export function useHelloAdaTranslations(){ return {language:'en', t}; }`,
  'provider': `export function useHelloAdaSite(){ return {siteName:'Fixture site',features:{bookings:false},routes:{preview:'/preview'},apiPrefix:'/api/helloada'}; }`,
  'search': `export function useSearchParams(){return new URLSearchParams(location.search)}`,
  'image': `import React from 'react'; export default function Image(props){return React.createElement('img',props)}`,
  'components': `export function HelloAdaChatMessage(){return null} export function HelloAdaHistory(){return null} export function HelloAdaGrowth(){return null} export function HelloAdaGallery(){return null} export function MailflarePayloadView(){return null} export function EditableRichTextEditor(){return null}`,
}
const entry = `import React from 'react'; import {createRoot} from 'react-dom/client'; import {WebsiteWorkspace} from ${JSON.stringify(resolve(root,'src/components/WebsiteWorkspace.tsx'))}; createRoot(document.getElementById('root')).render(React.createElement(WebsiteWorkspace));`
await build({ stdin:{contents:entry,resolveDir:root,sourcefile:'harness-entry.jsx',loader:'jsx'}, bundle:true,format:'iife',platform:'browser',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"','process.env':'window.__process.env'},outfile:`${out}/bundle.js`,plugins:[{name:'mocks',setup(p){p.onResolve({filter:/.*/},args=>{const spec=args.path; if(spec.endsWith('/api/fetchHelloAda'))return{path:'fetchHelloAda',namespace:'mock'};if(spec.endsWith('/api/useHelloAdaTranslations'))return{path:'translations',namespace:'mock'};if(spec.endsWith('/config/provider'))return{path:'provider',namespace:'mock'};if(spec==='next/navigation')return{path:'search',namespace:'mock'};if(spec==='next/image')return{path:'image',namespace:'mock'};if(/HelloAdaChatMessage|HelloAdaHistory|HelloAdaGrowth|HelloAdaGallery|MailflarePayloadView|EditableRichTextEditor/.test(spec))return{path:'components',namespace:'mock'};return null});p.onLoad({filter:/.*/,namespace:'mock'},args=>({contents:virtual[args.path],loader:'js',resolveDir:root}))}}] })
await writeFile(`${out}/admin.css`, compile('src/styles/admin.scss',{quietDeps:true}).css)
await writeFile(`${out}/index.html`, `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><script>window.__calls=[];window.__process={env:{NODE_ENV:'development'}}</script><link rel="stylesheet" href="admin.css"><div id="root"></div><script src="bundle.js"></script>`)
const result = spawnSync('python3',[resolve(root,'tests/ui039-browser-runner.py'),out],{stdio:'inherit'})
if(result.status !== 0) process.exit(result.status || 1)
