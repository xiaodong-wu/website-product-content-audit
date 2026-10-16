#!/usr/bin/env node
// Author a workbook from prepared data. The agent owns content judgments.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const args=process.argv.slice(2);
if(args.length<2 || args.includes('--help')) {
  console.log('Usage: node export_xlsx.mjs report.json output.xlsx [--node-modules DIR] [--preview-dir DIR]');
  process.exit(args.includes('--help')?0:2);
}
const [input,output,...options]=args;
const flags={};
for(let i=0;i<options.length;i+=2) {
  if(!['--node-modules','--preview-dir'].includes(options[i]) || !options[i+1]) throw new Error('Invalid option');
  flags[options[i]]=options[i+1];
}
let library;
try {
  if(flags['--node-modules']) {
    const loader=createRequire(path.join(path.dirname(path.resolve(flags['--node-modules'])),'__skill_loader__.cjs'));
    library=await import(pathToFileURL(loader.resolve('@oai/artifact-tool')).href);
  } else library=await import('@oai/artifact-tool');
} catch(error) {
  throw new Error('The host must provide @oai/artifact-tool. Pass its workspace node_modules using --node-modules. '+error.message);
}
const {Workbook,SpreadsheetFile}=library;
const data=JSON.parse(await fs.readFile(input,'utf8'));
if(data.schema_version!==1 || !Array.isArray(data.products) || !Array.isArray(data.issues)) throw new Error('Expected prepared report.json');
const products=data.products,issues=data.issues;
if(new Set(products.map(p=>p.id)).size!==products.length || new Set(issues.map(x=>x.id)).size!==issues.length) throw new Error('Duplicate record ids');
for(const p of products) if(p.issue_count!==issues.filter(x=>x.product_id===p.id).length) throw new Error('Issue count mismatch');
if(issues.some(x=>!products.some(p=>p.id===x.product_id) || !data.priorities.includes(x.priority))) throw new Error('Invalid issue reference or priority');
if(data.summary.affected_products!==products.length || data.summary.issues!==issues.length) throw new Error('Summary mismatch');
const onlyP1=data.priorities.length===1 && data.priorities[0]==='P1';
const names=onlyP1?['P1产品汇总','P1问题明细']:['问题产品汇总','问题明细'];
const workbook=Workbook.create(),summary=workbook.worksheets.add(names[0]),detail=workbook.worksheets.add(names[1]);
const font='Arial',ink='#16324A',muted='#596B78',teal='#147D92';
const pEnd=10+products.length,dEnd=7+issues.length;
// Escape formula-like source text; ordinary strings remain unchanged.
const safe=v=>typeof v==='string' && v.startsWith('=')?"'"+v:v;
function write(sh,addr,rows) {sh.getRange(addr).values=rows.map(row=>row.map(safe));}
function merged(sh,addr,text,size=11,bold=false,color=ink) {
  const r=sh.getRange(addr);r.merge();r.values=[[safe(text)]];
  r.format.font={name:font,size,bold,color};r.format.wrapText=true;r.format.verticalAlignment='center';
}
function base(sh,end,col,widths) {
  sh.showGridLines=false;sh.tabColor=teal;
  const r=sh.getRange(`A1:${col}${end}`);
  r.format.font={name:font,size:11,color:ink};r.format.wrapText=true;r.format.verticalAlignment='top';r.format.rowHeight=23;
  Object.entries(widths).forEach(([c,w])=>sh.getRange(`${c}1:${c}${end}`).format.columnWidth=w);
}
function rows(sh,start,values,widths,last) {
  values.forEach((row,i)=>{
    const rr=sh.getRange(`A${start+i}:${last}${start+i}`);
    rr.format.fill=i%2?'#F1F6FA':'#FFFFFF';
    let lines=1;
    row.forEach((v,c)=>{const n=String(v??'').split('\n').reduce((sum,s)=>sum+Math.max(1,Math.ceil([...s].reduce((a,ch)=>a+(ch.charCodeAt(0)>255?2:1),0)/(widths[c]*.88))),0);lines=Math.max(lines,n);});
    rr.format.rowHeight=Math.min(400,Math.max(56,lines*17+12));
  });
}
function table(sh,start,end,last,name) {
  sh.tables.add(`A${start}:${last}${Math.max(start,end)}`,true,name).showFilterButton=true;
  const r=sh.getRange(`A${start}:${last}${start}`);r.format.fill=ink;r.format.font={name:font,bold:true,color:'#FFFFFF',size:11};r.format.rowHeight=30;
}
function priority(sh,range) {
  for(const [p,color,fill] of [['P1','#B42318','#FDECE9'],['P2','#8A5800','#FFF4D6'],['P3','#25618B','#E8F2FA']])
    sh.getRange(range).conditionalFormats.add('containsText',{text:p,format:{fill,font:{color,bold:true}}});
}
base(summary,Math.max(pEnd,11),'J',{A:12,B:39,C:19,D:18,E:11,F:74,G:11,H:68,I:12,J:29});
merged(summary,'A2:J2',`${data.site.name} · ${data.priorities.join('/')} 产品内容核查`,20,true);summary.getRange('A2:J2').format.rowHeight=36;
merged(summary,'A3:J3',`报告截止：${data.site.checked_at} · 范围：${data.coverage.scope==='site'?'全站产品':'指定产品'}`,11,false,muted);
const c=data.summary;
merged(summary,'A5:D5',`发现 ${c.products_discovered} 个 · 正文已读 ${c.content_reviewed} 个 · 仅访问 ${c.access_only} 个 · 待核查 ${c.pending} 个`,11,true,teal);
merged(summary,'F5:J5','',13,true);
if(products.length) summary.getRange('F5').formulas=[[`="问题产品 "&COUNTA(A11:A${pEnd})&" 个 · 问题 "&SUM(G11:G${pEnd})&" 条"`]];
else summary.getRange('F5').values=[['问题产品 0 个 · 问题 0 条']];
summary.getRange('A5:J5').format.rowHeight=38;
merged(summary,'A6:J6',`产品发现：${data.coverage.discovery_complete?'已完成所选范围遍历':'尚未完成，不能声称已覆盖全部产品'}。访问核查不等于正文核查；零问题不等于没有未查页面。`,11,false,muted);
merged(summary,'A7:J8',`范围说明：${data.coverage.limitations.length?data.coverage.limitations.join('；'):'未记录额外限制。'}${c.pending?' 尚有待核查产品。':''}${c.access_only?' 部分产品正文不可访问。':''}`,11,false,muted);
summary.getRange('A7:J8').format.rowHeight=30;
write(summary,'A10:J10',[['产品编号','产品名称','型号 / SKU','类别','最高级别','问题摘要','问题条数','当前详情链接','HTTP状态','核查时间']]);
// The explicit label prevents ISO timestamps from being coerced to Excel serials.
const pRows=products.map(p=>[p.id,p.name,p.model,p.category,p.highest_priority,p.summary,null,p.current_url,p.http_status??'待确认',`核查于：${p.checked_at}`]);
if(products.length) {
  write(summary,`A11:J${pEnd}`,pRows);
  summary.getRange(`G11:G${pEnd}`).formulas=products.map((p,i)=>[`=COUNTIFS('${names[1]}'!$B$8:$B$${dEnd},A${11+i})`]);
}
table(summary,10,pEnd,'J','ProductSummary');rows(summary,11,pRows,[12,39,19,18,11,74,11,68,12,29],'J');
if(products.length) {priority(summary,`E11:E${pEnd}`);summary.getRange(`H11:H${pEnd}`).format.font.color=teal;summary.getRange(`G11:G${pEnd}`).format.horizontalAlignment='right';}
else merged(summary,'B11:H11','未发现符合所选级别、已确认且尚未解决的问题。',12,false,muted);
summary.freezePanes.freezeRows(10);summary.freezePanes.freezeColumns(2);

base(detail,Math.max(dEnd,8),'K',{A:12,B:12,C:38,D:10,E:22,F:42,G:82,H:46,I:65,J:68,K:13});
merged(detail,'A2:K2',`${data.priorities.join('/')} 问题、证据与修改建议`,19,true);detail.getRange('A2:K2').format.rowHeight=35;
merged(detail,'A3:K3',`共 ${issues.length} 条；保留稳定编号，来源链接采用当前地址。问题级别表示修订优先级，不代表产品质量评级。`,11,false,muted);
merged(detail,'A5:K5','证据与建议来自页面核查；技术真值仍以厂家批准资料为准。完整覆盖情况见产品汇总顶部。',11,false,muted);
write(detail,'A7:K7',[['问题编号','产品编号','产品名称','优先级','页面位置','具体问题','页面证据 / 对比值','实际影响','修改建议','当前详情链接','问题类别']]);
const dRows=issues.map(x=>[x.id,x.product_id,x.product_name,x.priority,x.location,x.title,x.evidence,x.impact,x.recommendation,x.current_url,x.kind==='access'?'访问':'内容']);
if(issues.length) write(detail,`A8:K${dEnd}`,dRows);
table(detail,7,dEnd,'K','IssueDetails');rows(detail,8,dRows,[12,12,38,10,22,42,82,46,65,68,13],'K');
if(issues.length) {priority(detail,`D8:D${dEnd}`);detail.getRange(`J8:J${dEnd}`).format.font.color=teal;}
else merged(detail,'C8:I8','没有可导出的问题记录；请结合覆盖统计查看未核查范围。',12,false,muted);
detail.freezePanes.freezeRows(7);detail.freezePanes.freezeColumns(3);
workbook.recalculate();
const previewDir=flags['--preview-dir']||path.join(path.dirname(path.resolve(output)),'previews');
await fs.mkdir(previewDir,{recursive:true});
for(const [sh,range,file] of [[summary,`A1:G${Math.min(Math.max(pEnd,11),14)}`,'products.png'],[detail,`A1:I${Math.min(Math.max(dEnd,8),11)}`,'issues.png']]) {
  // Include full merged title width in render to avoid clipping merged text.
  const full=range.replace(/^A1:[A-Z]+/,'A1:'+(sh===summary?'J':'K'));
  const png=await workbook.render({sheetName:sh.name,range:full,scale:1,format:'png'});
  await fs.writeFile(path.join(previewDir,file),new Uint8Array(await png.arrayBuffer()));
}
await fs.mkdir(path.dirname(path.resolve(output)),{recursive:true});
const xlsx=await SpreadsheetFile.exportXlsx(workbook);await xlsx.save(output);
console.log(JSON.stringify({output,products:products.length,issues:issues.length,previewDir}));
