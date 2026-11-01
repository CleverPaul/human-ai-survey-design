'use strict';
const $ = id => document.getElementById(id);
const color = {human:'#277d91',ai:'#d78332',target:'#64747d',ink:'#192c3c'};
const state = {scenario:null,result:null,group:0,view:'age',probe:49,busy:false,request:0,frontier:null};
const fmt = (x,n=3) => x == null ? '—' : Number(x).toFixed(n);
const percent = x => (100*x).toFixed(1)+'%';
const config = () => ({seed:Number($('seed').value),coverage:Number($('coverage').value)/100,n_human:Number($('humans').value)});
const design = () => ({budget:Number($('budget').value),tolerance:Number($('tolerance').value)/1000});
function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
function labels(){ $('coverage-value').textContent=$('coverage').value+'%';$('humans-value').textContent=$('humans').value;$('budget-value').textContent=$('budget').value;$('tolerance-value').textContent=(Number($('tolerance').value)/1000).toFixed(3); }
async function api(path,body){
  if(window.SurveyDesktop){await window.SurveyDesktop.ready;if(window.SurveyDesktop.isDesktop)return window.SurveyDesktop.request(path,body);}
  else if(window.location.protocol==='file:')throw Error('The desktop connection is unavailable. Close and reopen Survey Design Lab.');
  const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
  const data=await response.json();if(!response.ok)throw Error(data.error||'Request failed');return data;
}
function setBusy(value){state.busy=value;['optimize','regenerate','frontier','coverage','humans','budget','tolerance','seed'].forEach(id=>$(id).disabled=value);}
async function loadScenario(){
  if(state.busy)return;
  const ticket=++state.request;setBusy(true);status('Learning the bias from paired responses…');
  try{const sc=await api('/api/scenario?'+new URLSearchParams(config()));if(ticket!==state.request)return;state.scenario=sc;state.result=null;state.frontier=null;$('frontier-chart').innerHTML='';$('frontier-note').textContent='';renderAll();await optimize(true);}catch(e){status(e.message,true);}finally{setBusy(false);}
}
async function optimize(alreadyBusy=false){
  if((state.busy&&!alreadyBusy)||!state.scenario)return;
  setBusy(true);status('Selecting AI profiles and optimizing contribution weights…');
  try{const r=await api('/api/solve',{config:state.scenario.config,...design()});state.result=r;renderAll();
    const feasible=r.objective!=null;
    const certified=r.status==='optimal'||r.status==='optimal_within_tolerance';
    status(feasible?`${certified?'Optimal design':'Feasible design'} · ${r.solver} · ${r.elapsed_seconds.toFixed(2)} s${r.gap==null?'':' · gap '+(100*r.gap).toFixed(3)+'%'}`:(r.status==='infeasible'?'No feasible design at this budget and tolerance. Increase the budget or allow more demographic distance.':'No solution returned. Try again or allow more flexibility.'),!feasible);
    $('solver-label').textContent=r.solver+(r.solver_license==='bundled_restricted'?' · restricted license':'');
  }catch(e){status(e.message,true);}finally{if(!alreadyBusy)setBusy(false);}
}
function svgOpen(w,h,title){return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${title}"><title>${title}</title>`;}
function path(points){return points.map((p,i)=>(i?'L':'M')+p.map(v=>v.toFixed(2)).join(',')).join(' ');}
function gridAxes({w,h,l=48,r=16,t=16,b=34,xTicks,yTicks,x,y,xLabel,yFormat}){
  let out='';for(const v of yTicks){out+=`<line class="grid-line" x1="${l}" x2="${w-r}" y1="${y(v)}" y2="${y(v)}"/><text text-anchor="end" x="${l-10}" y="${y(v)+3}">${yFormat?yFormat(v):fmt(v,1)}</text>`;}
  for(const v of xTicks)out+=`<text text-anchor="middle" x="${x(v)}" y="${h-b+18}">${v}</text>`;
  if(xLabel)out+=`<text class="axis-title" text-anchor="end" x="${w-r}" y="${h-2}">${xLabel}</text>`;return out;
}
function renderBias(){
  const sc=state.scenario;if(!sc)return;
  const grid=sc.grid[state.group],obs=sc.human.filter(p=>p.group===state.group),truth=$('truth').checked;
  const w=Math.max(290,Math.min(800,$('bias-chart').clientWidth)),h=245,l=48,r=16,t=18,b=34;
  let vals=grid.biasmean.flatMap((m,i)=>[m-1.96*grid.sd[i],m+1.96*grid.sd[i]]).concat(obs.map(p=>p.delta),[0]);
  if(truth)vals=vals.concat(grid.truebias);
  let lo=Math.floor((Math.min(...vals)-.12)*2)/2,hi=Math.ceil((Math.max(...vals)+.12)*2)/2;if(hi-lo<1){lo-=.5;hi+=.5;}
  const x=v=>l+(v-18)/62*(w-l-r),y=v=>t+(hi-v)/(hi-lo)*(h-t-b);
  const ticks=Array.from({length:5},(_,i)=>lo+(hi-lo)*i/4);
  let out=svgOpen(w,h,'Estimated AI bias by age, with a model-based 95 percent uncertainty interval');
  out+=gridAxes({w,h,l,r,t,b,x,y,xTicks:[20,30,40,50,60,70,80],yTicks:ticks,xLabel:'Age',yFormat:v=>fmt(v,1)});
  const upper=grid.age.map((age,i)=>[x(age),y(grid.biasmean[i]+1.96*grid.sd[i])]);const lower=grid.age.map((age,i)=>[x(age),y(grid.biasmean[i]-1.96*grid.sd[i])]).reverse();
  out+=`<path d="${path(upper.concat(lower))} Z" fill="#f7e8d6"/>`;
  out+=`<line x1="${l}" x2="${w-r}" y1="${y(0)}" y2="${y(0)}" stroke="#c9d1cd" stroke-dasharray="3 4"/>`;
  if(truth)out+=`<path d="${path(grid.age.map((a,i)=>[x(a),y(grid.truebias[i])]))}" stroke="${color.ink}" stroke-width="1.5" stroke-dasharray="5 4" fill="none"/>`;
  out+=`<path d="${path(grid.age.map((a,i)=>[x(a),y(grid.biasmean[i])]))}" stroke="${color.ai}" stroke-width="2.5" fill="none"/>`;
  for(const p of obs)out+=`<circle cx="${x(p.age)}" cy="${y(p.delta)}" r="4.1" fill="${color.human}" stroke="#fffefb" stroke-width="1.5"><title>Human profile: age ${fmt(p.age,1)}; paired difference ${fmt(p.delta)}</title></circle>`;
  // Rug marks show where observations support this group's curve.
  for(const p of obs)out+=`<line x1="${x(p.age)}" x2="${x(p.age)}" y1="${h-b+1}" y2="${h-b+6}" stroke="${color.human}" stroke-width="2" opacity=".6"/>`;
  const idx=Math.max(0,Math.min(80,Math.round((state.probe-18)/62*80))),a=grid.age[idx],m=grid.biasmean[idx],sd=grid.sd[idx];
  out+=`<line x1="${x(a)}" x2="${x(a)}" y1="${t}" y2="${h-b}" stroke="${color.ai}" opacity=".4" stroke-dasharray="3 3"/><circle cx="${x(a)}" cy="${y(m)}" r="5" fill="${color.ai}" stroke="white" stroke-width="2"/>`;
  out+=`<text x="${l}" y="10" class="axis-title">AI − human outcome</text></svg>`;
  $('bias-chart').innerHTML=out;
  $('probe-readout').innerHTML=`Age <b>${Math.round(a)}</b> · debias by <b>${fmt(m,2)}</b> · 95% interval <b>[${fmt(m-1.96*sd,2)}, ${fmt(m+1.96*sd,2)}]</b>`;
}
function validResult(){return state.result&&state.result.objective!=null;}
function currentWeights(){const sc=state.scenario;return validResult()?{wh:state.result.wh,ws:state.result.ws}:{wh:sc.human.map(()=>1/sc.human.length),ws:sc.target.map(()=>0)};}
function renderMetrics(){
  const r=state.result,ok=validResult();
  const cards=[['AI respondents',ok?`${r.budget_used}<small>/ ${r.budget} budget</small>`:'—', 'Selected target profiles','ai-metric'],['AI contribution',ok?percent(r.silicon_mass):'—','Share of total estimate weight','ai-metric'],['Response risk',ok?fmt(r.response_risk,4):'—','Minimized model-based wᵀQw','risk-metric'],['Demographic distance',ok?fmt(r.representation_distance):'—',ok?'Constraint ≤ '+fmt(r.tolerance):'Optimize to see the result','']];
  $('metrics').innerHTML=cards.map(c=>`<div class="metric ${c[3]}"><p class="metric-label">${c[0]}</p><div class="metric-value">${c[1]}</div><p class="metric-sub">${c[2]}</p></div>`).join('');
}
function renderComposition(){
  if(!state.scenario)return;const sc=state.scenario,{wh,ws}=currentWeights();
  const w=Math.max(290,Math.min(800,$('composition-chart').clientWidth)),h=230,l=48,r=16,t=20,b=35;
  if(state.view==='weights'){
    const max=Math.max(.12,...wh,...ws)*1.15,x=a=>l+(a-18)/62*(w-l-r),y=v=>t+(1-v/max)*(h-t-b);
    let out=svgOpen(w,h,'Contribution weight of each human and candidate AI respondent');
    out+=gridAxes({w,h,l,r,t,b,x,y,xTicks:[20,30,40,50,60,70,80],yTicks:[0,max/2,max],xLabel:'Age',yFormat:v=>percent(v)});
    sc.human.forEach((p,i)=>{out+=`<line x1="${x(p.age)}" x2="${x(p.age)}" y1="${y(0)}" y2="${y(wh[i])}" stroke="${color.human}" opacity=".3"/><circle cx="${x(p.age)}" cy="${y(wh[i])}" r="4" fill="${color.human}"><title>Human ${i+1}, group ${p.group?'B':'A'}: ${percent(wh[i])}</title></circle>`;});
    sc.target.forEach((p,i)=>{const px=x(p.age)+(p.group?3:-3),py=y(ws[i]);out+=`<path d="M${px},${py-5}l5,5l-5,5l-5,-5Z" fill="${ws[i]>1e-7?color.ai:'#fffefb'}" stroke="${color.ai}" stroke-width="1.3"><title>AI target ${i+1}, group ${p.group?'B':'A'}: ${percent(ws[i])}</title></path>`;});
    $('composition-chart').innerHTML=out+'</svg>';$('composition-caption').textContent='Each mark is one profile. AI profiles with zero weight are hollow; groups can share the same age.';return;
  }
  const groups=state.view==='group',n=groups?2:6;
  const index=p=>groups?p.group:Math.min(5,Math.floor(p.x*6));
  const target=Array(n).fill(0),human=Array(n).fill(0),ai=Array(n).fill(0);
  sc.target.forEach((p,i)=>{target[index(p)]+=p.mass;ai[index(p)]+=ws[i];});sc.human.forEach((p,i)=>human[index(p)]+=wh[i]);
  const max=Math.ceil(Math.max(.4,...target,...human.map((v,i)=>v+ai[i]))*10)/10;
  const y=v=>t+(1-v/max)*(h-t-b),step=(w-l-r)/n,bar=Math.min(45,step*.28);
  let out=svgOpen(w,h,'Target population share compared with combined human and AI contribution weights');
  out+=gridAxes({w,h,l,r,t,b,x:v=>v,y,xTicks:[],yTicks:[0,max/2,max],yFormat:v=>percent(v)});
  for(let i=0;i<n;i++){
    const center=l+step*(i+.5),a=center-bar-4,c=center+4;
    out+=`<rect x="${a}" y="${y(target[i])}" width="${bar}" height="${y(0)-y(target[i])}" fill="#edf0eb" stroke="${color.target}" stroke-width="1.3"/><rect x="${c}" y="${y(human[i])}" width="${bar}" height="${y(0)-y(human[i])}" fill="${color.human}"/><rect x="${c}" y="${y(human[i]+ai[i])}" width="${bar}" height="${y(human[i])-y(human[i]+ai[i])}" fill="${color.ai}"/>`;
    const label=groups?'Group '+(i?'B':'A'):`${Math.round(18+i*62/6)}–${Math.round(18+(i+1)*62/6)}`;
    out+=`<text text-anchor="middle" x="${center}" y="${h-b+20}">${label}</text>`;
  }
  $('composition-chart').innerHTML=out+'</svg>';
  $('composition-caption').textContent=(validResult()?'Optimized contribution weights. ':'Before optimization: equal human weights. ')+(groups?'Group shares are matched approximately under the joint demographic-distance constraint.':'Target bars are gray; stacked bars combine human and AI weights. Height is weight, not respondent count.');
}
function renderComparison(){
  const sc=state.scenario;if(!sc)return;const r=state.result;
  const raw=r?.baselines?.unweighted||{representation_distance:sc.reference.raw_human_distance,estimated_mean:sc.reference.raw_human_estimate,response_risk:null};
  let out=`<tr><td>Human data, unweighted<span class="cell-note">Equal contribution per respondent</span></td><td>${fmt(raw.representation_distance)}</td><td>${fmt(raw.response_risk,4)}</td><td>${fmt(raw.estimated_mean)}</td></tr>`;
  const human=r?.baselines?.human_only;
  if(human?.feasible)out+=`<tr><td>Human data, reweighted<span class="cell-note">Same demographic constraint</span></td><td>${fmt(human.representation_distance)}</td><td>${fmt(human.response_risk,4)}</td><td>${fmt(human.estimated_mean)}</td></tr>`;
  else out+=`<tr><td>Human data, reweighted<span class="cell-note">Best possible distance: ${fmt(sc.reference.minimum_human_distance)}</span></td><td colspan="3" class="infeasible">${human?'Infeasible at the current tolerance':'Not solved yet'}</td></tr>`;
  out+=`<tr class="featured"><td>Human + AI, optimized<span class="cell-note">Joint selection and contribution weights</span></td><td>${fmt(r?.representation_distance)}</td><td>${fmt(r?.response_risk,4)}</td><td>${fmt(r?.estimated_mean)}</td></tr>`;
  $('comparison').innerHTML=out;
  $('assessment').textContent=$('truth').checked?`Assessment only: the simulated target mean is ${fmt(sc.true_target_mean)}.${validResult()?' This run’s absolute estimation error is '+fmt(r.absolute_error_assessment)+'.':''} One realization need not improve on every baseline.`:'Response risk is a model-based second moment, not the error observed in one simulated run.';
}
function renderAll(){renderBias();renderMetrics();renderComposition();renderComparison();}
async function frontier(){
  if(state.busy||!state.scenario)return;setBusy(true);$('frontier-note').textContent='Solving the same design problem at eight tolerances…';
  try{state.frontier=await api('/api/frontier',{config:state.scenario.config,budget:Number($('budget').value)});const pts=state.frontier.points,feas=pts.filter(p=>p.objective!=null);const w=800,h=220,l=52,r=18,t=20,b=35;
    if(!feas.length){$('frontier-chart').innerHTML='';$('frontier-note').textContent='No feasible designs on this grid. Increase the budget.';return;}
    const max=Math.max(...feas.map(p=>p.objective))*1.15,x=v=>l+v/.35*(w-l-r),y=v=>t+(1-v/max)*(h-t-b);
    let out=svgOpen(w,h,'Minimum model response risk versus allowed demographic distance');out+=gridAxes({w,h,l,r,t,b,x,y,xTicks:[0,.05,.10,.15,.20,.25,.30,.35],yTicks:[0,max/2,max],xLabel:'Allowed demographic distance ε',yFormat:v=>fmt(v,3)});
    out+=`<path d="${path(feas.map(p=>[x(p.tolerance),y(p.objective)]))}" stroke="${color.human}" stroke-width="2" fill="none"/>`;
    for(const p of pts)out+=p.objective==null?`<text x="${x(p.tolerance)}" y="${h-b-5}" text-anchor="middle" fill="#9a5038">×</text>`:`<circle cx="${x(p.tolerance)}" cy="${y(p.objective)}" r="4.5" fill="${color.human}"><title>ε ${fmt(p.tolerance)}; risk ${fmt(p.objective,5)}; status ${p.status}; gap ${fmt(p.gap,6)}</title></circle>`;
    $('frontier-chart').innerHTML=out+'</svg>';
    const uncertified=feas.filter(p=>!['optimal','optimal_within_tolerance'].includes(p.status)).length;
    $('frontier-note').textContent=`Budget: ${state.frontier.budget} AI respondents. × denotes infeasibility. Looser constraints cannot increase the optimum for fixed Q and budget.${uncertified?' Some plotted feasible designs reached the time limit; these are upper bounds, not certified optima.':' All feasible points are solver-certified within tolerance.'}`;
  }catch(e){$('frontier-note').textContent=e.message;}finally{setBusy(false);}
}
let debounce;
['coverage','humans'].forEach(id=>{$(id).addEventListener('input',()=>{labels();clearTimeout(debounce);debounce=setTimeout(()=>loadScenario(),350);});});
['budget','tolerance'].forEach(id=>{$(id).addEventListener('input',()=>{labels();status('Design controls changed. Optimize to update the solution.');});});
$('regenerate').addEventListener('click',()=>loadScenario());$('optimize').addEventListener('click',()=>optimize());$('frontier').addEventListener('click',frontier);
$('group-tabs').addEventListener('click',e=>{if(!e.target.matches('button'))return;state.group=Number(e.target.dataset.group);document.querySelectorAll('#group-tabs button').forEach(b=>b.classList.toggle('active',Number(b.dataset.group)===state.group));renderBias();});
$('composition-tabs').addEventListener('click',e=>{if(!e.target.matches('button'))return;state.view=e.target.dataset.view;document.querySelectorAll('#composition-tabs button').forEach(b=>b.classList.toggle('active',b.dataset.view===state.view));renderComposition();});
$('truth').addEventListener('change',()=>{renderBias();renderComparison();});
let dragging=false;
function probe(event){if(!state.scenario)return;const box=$('bias-chart').getBoundingClientRect(),w=$('bias-chart').querySelector('svg').viewBox.baseVal.width;const fraction=Math.max(0,Math.min(1,((event.clientX-box.left)/box.width*w-48)/(w-48-16)));state.probe=18+fraction*62;renderBias();}
$('bias-chart').addEventListener('pointerdown',e=>{dragging=true;$('bias-chart').setPointerCapture(e.pointerId);probe(e);});
$('bias-chart').addEventListener('pointermove',e=>{if(dragging||e.pointerType==='mouse')probe(e);});
$('bias-chart').addEventListener('pointerup',()=>dragging=false);$('bias-chart').addEventListener('pointercancel',()=>dragging=false);
$('download').addEventListener('click',async()=>{
  if(!state.scenario)return;
  try{
    const sc=await api('/api/scenario?'+new URLSearchParams({...state.scenario.config,matrices:1}));
    const data={prototype:'Survey Design Lab',scenario:sc,solution:state.result,frontier:state.frontier,notes:'Synthetic data. Truth is assessment-only. Q is the full response-error second moment.'};
    const content=JSON.stringify(data,null,2),filename='survey-design-seed-'+sc.config.seed+'.json';
    if(window.SurveyDesktop?.isDesktop){const result=await window.SurveyDesktop.saveJson(content,filename);if(result?.saved)status('Run saved.');return;}
    const blob=new Blob([content],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){status(e.message,true);}
});
window.addEventListener('resize',()=>{if(state.scenario)renderAll();});
labels();loadScenario();
