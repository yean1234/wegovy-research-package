const src=require('fs').readFileSync(__dirname+'/site_template.html','utf8');
const grab=n=>{const i=src.indexOf('function '+n+'(');let d=0,j=src.indexOf('{',i);for(let k=j;k<src.length;k++){if(src[k]=='{')d++;if(src[k]=='}'){d--;if(!d)return src.slice(i,k+1)}}};
eval(['wilson','binStats','krippAlpha'].map(grab).join('\n'));
console.log('wilson 27/30',wilson(27,30).map(x=>x.toFixed(3)),'(expected 0.744-0.965)');
const s=binStats([['yes','yes'],['yes','no'],['no','no'],['no','yes'],['no','no']]);console.log('tp fp fn tn',s.tp,s.fp,s.fn,s.tn,'acc',s.acc,'kappa',s.kappa.toFixed(3));
console.log('alpha perfect',krippAlpha([['a','a'],['b','b'],['a','a']]).alpha);
const A='0 1 0 0 0 0 0 0 1 0'.split(' '),B='1 1 1 0 0 1 0 0 0 0'.split(' ');
console.log('alpha example',krippAlpha(A.map((a,i)=>[a,B[i]])).alpha.toFixed(3),'(expected 0.095)');
