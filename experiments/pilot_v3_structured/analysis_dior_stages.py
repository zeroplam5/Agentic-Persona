"""Dior 단계별 수렴 분석 보조 스크립트 (2026-11-19).

읽기 전용: data/generations.jsonl, data/buckets.jsonl 만 읽는다. 호출 없음.
출력: results/dior_stage_features.csv  (실행별 선택 후보·묶음·수정/최종안 키워드 표시)
키워드 표시는 원문 판독을 돕는 검색 보조다. 같은 발상 여부는 원문을 읽고 판단했다(results/dior_convergence_analysis.md).
사용: python -I analysis_dior_stages.py . results/dior_stage_features.csv
"""
import json, re, sys, csv
from collections import defaultdict, Counter
base=sys.argv[1]; out=sys.argv[2]
rows=[json.loads(l) for l in open(base+'/data/generations.jsonl',encoding='utf-8')]
B={}
for l in open(base+'/data/buckets.jsonl',encoding='utf-8'):
    b=json.loads(l)
    if b['brand']=='Dior' and b['phase']=='assign': B[b['item_id']]=(str(b['bucket']),b['text'])
F={
 'MARK': r"signature|signed|sign(s|ed)? (the|each|it)|initials|mend mark|lucky (stitch|thread)|fitting (card|number|mark|label|no)|mark of (life|montaigne)|muguet sprig|stitched (star|label|mark|signature)|star stitched|numbered (mark|label|'second)|card (noting|signed)|signed by",
 'CHOICE': r"invisibl|opt-in|optional|choose|choice|whispers or shines|how visible",
 'RECORD': r"ledger|passport|registry|lineage|life record|provenance|certificate|record(s|ing)? (its|each|the|who)|logged|logs|history travels",
 'ARTISAN': r"petites? mains|artisan|atelier hand|repairer|couturi|premi[eè]res|hands",
 'PILOT': r"pilot|phased|few cities|limited (number|capacity)|flagship cities|city by city|launch(es)? only once|capacity|appointment",
 'NOCLAIM': r"greenwash|no (environmental|sustainability)|environmental (claim|stat)|sustainability claim|statistic|figures|verif",
 'SECONDHAND': r"secondhand|second-hand|pre-owned|pre-loved|vintage|resale|inherited|thrifted|found in a vintage",
 'FILM': r"film|portrait",
 'SALON': r"salon|pop-up|open atelier|open hours|live atelier|repair counter|fitting room|open days|window",
 'ICON': r"bar jacket|lady dior|saddle",
}
order=['BASE','SB_AVG','SB_O_H','SB_O_L','LK_AVG','LK_O_H','LK_O_L','NODEDUP']
def has(t,k): return bool(re.search(F[k],t,re.I))
res=[]
runs=defaultdict(dict)
for r in rows:
    if r['brand']=='Dior': runs[r['run_id']][r.get('k')]=r
# which NODEDUP k was chosen as final: match final text
for c in order:
  for rep in range(4):
    rid=f'Dior|{c}|{rep}'
    fb,ft=B[rid+'|final']
    if c!='NODEDUP':
        p=runs[rid][None]['parsed']; sel=p['selection']['selected_id']
        selc=[x for x in p['candidates'] if x['id']==sel][0]
        revt=' '.join(v['change'] for v in p['revisions_after_selection'])
        final=p['final_proposal']['title']+': '+p['final_proposal']['idea']
        reasons=' '.join(p['selection']['reasons_for_selection'])
        row=dict(run=rid,cond=c,rep=rep,sel=sel,sel_bucket=B.get(f'{rid}|{sel}',('?',))[0],final_bucket=fb,
                 absorb=bool(re.search(r'absorb|fold|borrow|carr(y|ies) over|kept in|is kept|survives',reasons+' '+revt+' '+' '.join(x['reason'] for x in p['selection']['rejected']),re.I)),
                 sel_has_MARK=has(selc['core_idea'],'MARK'), rev_has_MARK=has(revt,'MARK'))
        for k in F: row['rev_'+k]=has(revt,k); row['fin_'+k]=has(final,k)
    else:
        kk=[k for k in range(4) if (runs[rid][k]['parsed']['final_proposal']['title']+': '+runs[rid][k]['parsed']['final_proposal']['idea'])==ft]
        final=ft
        row=dict(run=rid,cond=c,rep=rep,sel='k%s'%kk,sel_bucket='-',final_bucket=fb,absorb='',sel_has_MARK='',rev_has_MARK='')
        for k in F: row['rev_'+k]=''; row['fin_'+k]=has(final,k)
    res.append(row)
w=csv.DictWriter(open(out,'w',newline='',encoding='utf-8-sig'),fieldnames=list(res[0].keys())); w.writeheader(); w.writerows(res)
S=[r for r in res if r['cond']!='NODEDUP']
print('structured runs',len(S))
print('selected C1:',sum(r['sel']=='C1' for r in S))
print('selected cand bucket3:',sum(r['sel_bucket']=='3' for r in S))
ns=[r for r in S if r['sel_bucket']!='3']
print('non-b3 selections',len(ns),'-> rev adds MARK:',sum(r['rev_has_MARK'] for r in ns), [ (r['run'],r['rev_has_MARK']) for r in ns])
print('absorb language in selection/rejection/revision:',sum(r['absorb'] for r in S))
for k in F:
    print(k.ljust(10),'final(all32)=',sum(r['fin_'+k] for r in res),' rev(28)=',sum(bool(r['rev_'+k]) for r in S))
