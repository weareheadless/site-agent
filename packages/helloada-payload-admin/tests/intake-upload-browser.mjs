import { build } from 'esbuild'
import { compile } from 'sass'
import { mkdir, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

// Exercise the actual workspace with only application API boundaries mocked;
// image upload itself is a real XMLHttpRequest to the localhost fixture server.
const root = process.cwd()
const out = '/tmp/opencode/520-browser'
await mkdir(out, { recursive: true })
const virtual = {
  fetchHelloAda: `export async function fetchHelloAda(path, options={}) {
    const url=String(path); let body={};
    if (url.includes('/media-library')) return fetch(url,options);
    else if (url.includes('/workspace')) body={site:{name:'Fixture site',url:'https://fixture.invalid'},routes:[{path:'/',kind:'page',collection:'pages',sourceId:'page-1'}],documents:[{id:'1',collection:'pages',sourceId:'page-1',slug:'home',title:'Home',status:'draft',draftHash:'draft-hash'}],ada:{configured:true}};
    else if (url.includes('/conversations')) body={conversations:[]};
    else if (url.includes('/drafts')) body={drafts:[]};
    return {ok:true,status:200,json:async()=>body};
  }`,
  translations: `const labels={'owner.publishTitle':'Publish changes?','owner.publishNote':'Review this publication summary.','owner.keepReviewing':'Keep reviewing','owner.publishChanges':'Publish changes','workspace.quickEditLabel':'Quick editing','workspace.quickEditButton':'Edit field','workspace.quickEditFieldButton':'Edit field','workspace.pageClose':'Close','workspace.applyFieldChange':'Apply field change','workspace.attachmentUploading':'Uploading','workspace.attachmentReady':'Ready','workspace.attachmentFailed':'Upload failed','workspace.unsupportedImage':'Unsupported file type','workspace.removeImage':'Remove image','workspace.attachedImages':'Attached images','workspace.pendingAttachments':'Pending attachments','error.imageAttach':'Unable to attach image','workspace.send':'Send','workspace.askAda':'Ask Ada','owner.galleryTitle':'Image gallery','owner.galleryIntro':'Choose or upload images','workspace.pageGalleryBrowse':'Browse gallery','workspace.pageUploadImage':'Upload image','workspace.pageGallerySearchPlaceholder':'Search images','workspace.image':'Image','workspace.pageGalleryNoMatch':'No images found','owner.galleryAnalysing':'Analysing'}; export function useHelloAdaTranslations(){return {language:'en',t:(key)=>labels[key]||key}}`,
  provider: `export function useHelloAdaSite(){return {siteName:'Fixture site',features:{bookings:false},routes:{preview:'/preview'},apiPrefix:'/api/helloada'}}`,
  search: `export function useSearchParams(){return new URLSearchParams(location.search)}`,
  image: `import React from 'react'; export default function Image({unoptimized,...props}){return React.createElement('img',props)}`,
  components: `export function HelloAdaChatMessage(){return null} export function HelloAdaHistory(){return null} export function HelloAdaGrowth(){return null} export function HelloAdaGallery(){return null} export function MailflarePayloadView(){return null} export function EditableRichTextEditor(){return null}`,
}
const entry=`import React from 'react'; import {createRoot} from 'react-dom/client'; import {WebsiteWorkspace} from ${JSON.stringify(resolve(root,'src/components/WebsiteWorkspace.tsx'))}; createRoot(document.getElementById('root')).render(React.createElement(WebsiteWorkspace));`
await build({stdin:{contents:entry,resolveDir:root,sourcefile:'fixture-entry.jsx',loader:'jsx'},bundle:true,format:'iife',platform:'browser',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"','process.env':'window.__process.env'},outfile:`${out}/bundle.js`,plugins:[{name:'mocks',setup(p){p.onResolve({filter:/.*/},args=>{const s=args.path;if(s.endsWith('/api/fetchHelloAda'))return{path:'fetchHelloAda',namespace:'mock'};if(s.endsWith('/api/useHelloAdaTranslations'))return{path:'translations',namespace:'mock'};if(s.endsWith('/config/provider'))return{path:'provider',namespace:'mock'};if(s==='next/navigation')return{path:'search',namespace:'mock'};if(s==='next/image')return{path:'image',namespace:'mock'};if(/HelloAdaChatMessage|HelloAdaHistory|HelloAdaGrowth|HelloAdaGallery|MailflarePayloadView|EditableRichTextEditor/.test(s))return{path:'components',namespace:'mock'};return null});p.onLoad({filter:/.*/,namespace:'mock'},args=>({contents:virtual[args.path],loader:'js',resolveDir:root}))}}]})
await writeFile(`${out}/admin.css`,compile('src/styles/admin.scss',{quietDeps:true}).css)
await writeFile(`${out}/index.html`,`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><script>window.__process={env:{NODE_ENV:'development'}}</script><link rel="stylesheet" href="admin.css"><div id="root"></div><script src="bundle.js"></script>`)
const result=spawnSync('/SOCIAL/site-agent/.venv/bin/python',[resolve(root,'tests/intake-upload-browser-runner.py'),out],{stdio:'inherit'})
if(result.status!==0)process.exit(result.status||1)
