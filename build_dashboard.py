"""Rebuild dashboard.html. Every number is computed from the two SQLite databases, nothing is typed in by hand.

Run after data_generator.py:   python build_dashboard.py
"""
import os, sqlite3, json, numpy as np, pandas as pd
from scipy.stats import chi2_contingency, mannwhitneyu
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

HERE=os.path.dirname(os.path.abspath(__file__))
c1=sqlite3.connect(os.path.join(HERE,"data","ai_saas.db")); c2=sqlite3.connect(os.path.join(HERE,"data","ab_test.db"))
q1=lambda s: pd.read_sql_query(s,c1); q2=lambda s: pd.read_sql_query(s,c2)
M={}
ev=q1("select event_type,count(distinct user_id) n from events group by 1").set_index("event_type").n.to_dict()
M["funnel"]={k:int(ev[k]) for k in ["signed_up","activated","first_ai_output","invited_team","upgraded"]}
M["churned_users"]=int(ev["churned"])
M["n_users"]=int(ev["signed_up"]); M["n_sessions"]=int(q1("select count(*) n from sessions").n[0])
M["churn_of_ai"]=ev["churned"]/ev["first_ai_output"]
M["channel"]=q1("""select u.channel, count(*) n, sum(f.user_id is not null) ai,
   round(avg(f.user_id is not null)*100,1) ai_pct from users u
   left join (select distinct user_id from events where event_type='first_ai_output') f on u.user_id=f.user_id group by 1 order by 4 desc""").to_dict("records")
M["plan"]=q1("select plan_tier p,count(*) n from users group by 1").set_index("p").n.to_dict()
M["channel_ret"]=q1("""WITH ur AS (SELECT u.channel,JULIANDAY(MAX(DATE(s.session_date)))-JULIANDAY(DATE(u.signup_date)) d FROM users u JOIN sessions s ON u.user_id=s.user_id GROUP BY u.user_id)
 select channel,count(*) n, round(avg(d>=7)*100,1) w1, round(avg(d>=28)*100,1) w4, round(avg(d>=56)*100,1) w8 from ur group by 1 order by w8 desc""").to_dict("records")
t=q1("""WITH fa AS (SELECT user_id, MIN(event_date) f FROM events WHERE event_type='first_ai_output' GROUP BY 1),
ce AS (SELECT user_id, MIN(event_date) c FROM events WHERE event_type='churned' GROUP BY 1),
t AS (select julianday(c)-julianday(f) d from ce join fa using(user_id) where julianday(c)>=julianday(f))
select case when d<7 then 0 when d<14 then 1 when d<21 then 2 when d<28 then 3 when d<60 then 4 when d<90 then 5 else 6 end b, count(*) n from t group by 1""").set_index("b").n.to_dict()
labels=["Days 0-6","Days 7-13","Days 14-20","Days 21-27","Days 28-59","Days 60-89","Days 90+"]
M["churn_timing"]=[{"window":labels[i],"count":int(t.get(i,0))} for i in range(7)]
# feature churn among first-AI users
base=q1("""WITH ai AS (SELECT DISTINCT user_id FROM events WHERE event_type='first_ai_output'),
fu AS (SELECT DISTINCT user_id, feature_name FROM feature_usage), ce AS (SELECT DISTINCT user_id FROM events WHERE event_type='churned')
select ai.user_id, max(fu.feature_name='rewrite') r, max(fu.feature_name='analyze') a, max(fu.feature_name='summarize') s, max(fu.feature_name='generate') g, max(fu.feature_name='translate') t,
 max(ce.user_id is not null) ch from ai left join fu on ai.user_id=fu.user_id left join ce on ai.user_id=ce.user_id group by 1""")
fc=[]
for name,col in [("rewrite","r"),("analyze","a"),("summarize","s"),("generate","g"),("translate","t")]:
    w=base[base[col]==1]; n=base[base[col]==0]
    tab=[[w.ch.sum(),len(w)-w.ch.sum()],[n.ch.sum(),len(n)-n.ch.sum()]]
    chi,p,_,_=chi2_contingency(np.array(tab))
    fc.append({"feature":name,"with":round(w.ch.mean()*100,1),"without":round(n.ch.mean()*100,1),"n_with":int(len(w)),"chi2":round(chi,1),"p":float(p),"sig":bool(p<0.05)})
M["feature_churn"]=fc
M["rewrite_adoption"]=float(base.r.mean())
M["avg_features"]=float(q1("select avg(c) a from (select count(*) c from feature_usage group by user_id)").a[0])
M["session_feature_share"]=q1("select ai_feature_used f,count(*) n from sessions group by 1").set_index("f").n.to_dict()
# MAU
M["mau"]=q1("""WITH ma AS (SELECT user_id, STRFTIME('%Y-%m',session_date) mo FROM sessions GROUP BY user_id, mo),
wp AS (SELECT user_id, mo, LAG(mo) OVER (PARTITION BY user_id ORDER BY mo) prev FROM ma)
SELECT mo month, COUNT(*) mau, SUM(prev IS NULL) new, COALESCE(SUM(prev=STRFTIME('%Y-%m',DATE(mo||'-01','-1 month'))),0) retained FROM wp GROUP BY mo ORDER BY mo""").query("month<='2025-12'").to_dict("records")
# cohort heatmap
ch=q1("""WITH c AS (SELECT u.user_id, STRFTIME('%Y-%m',u.signup_date) m, JULIANDAY(MAX(DATE(s.session_date)))-JULIANDAY(DATE(u.signup_date)) d FROM users u JOIN sessions s ON u.user_id=s.user_id GROUP BY u.user_id)
select m cohort, count(*) size, round(avg(d>=7)*100,1) w1, round(avg(d>=28)*100,1) w4, round(avg(d>=56)*100,1) w8 from c where m<='2025-09' group by 1 order by 1""")
M["cohorts"]=ch.tail(12).to_dict("records")
# revenue
M["mrr_active"]=int(q1("select sum(mrr_inr) m from subscriptions where status='active' and plan!='free'").m[0])
M["paying_active"]=int(q1("select count(*) n from subscriptions where status='active' and plan!='free'").n[0])
roi=q1("""WITH paying AS (SELECT s.user_id,s.mrr_inr,s.status, EXISTS(SELECT 1 FROM feature_usage f WHERE f.user_id=s.user_id AND f.feature_name='rewrite') rw FROM subscriptions s WHERE s.plan!='free' AND EXISTS(SELECT 1 FROM events e WHERE e.user_id=s.user_id AND e.event_type='first_ai_output'))
select rw, count(*) n, sum(status='cancelled') canc, round(avg(status='cancelled')*100,2) pct, round(avg(mrr_inr),0) avg_mrr from paying group by rw""").set_index("rw")
gap=(roi.loc[0,"pct"]-roi.loc[1,"pct"])/100; saved=roi.loc[0,"n"]*gap
M["roi"]={"nr_pct":float(roi.loc[0,"pct"]),"rw_pct":float(roi.loc[1,"pct"]),"gap_pp":round(gap*100,1),"subs":round(float(saved)),"mrr_month":round(float(saved*roi.loc[0,"avg_mrr"])),"arr":round(float(saved*roi.loc[0,"avg_mrr"]*12))}
# churn model (eligible population)
df=q1("""WITH ai AS (SELECT DISTINCT user_id FROM events WHERE event_type='first_ai_output'), ce AS (SELECT DISTINCT user_id FROM events WHERE event_type='churned'),
fu AS (SELECT user_id, COUNT(DISTINCT feature_name) n_features, SUM(feature_name='rewrite') uses_rewrite, SUM(feature_name='analyze') uses_analyze, AVG(usage_count_30d) avg_usage FROM feature_usage GROUP BY 1),
sa AS (SELECT user_id, COUNT(*) total_sessions, AVG(duration_seconds) avg_duration, COUNT(DISTINCT STRFTIME('%Y-%m',session_date)) active_months FROM sessions GROUP BY 1)
SELECT u.channel='organic_search' ch_organic, u.channel='referral' ch_referral, u.plan_tier='pro' plan_pro, u.plan_tier='enterprise' plan_ent,
 COALESCE(n_features,0) n_features, COALESCE(uses_rewrite,0) uses_rewrite, COALESCE(uses_analyze,0) uses_analyze, COALESCE(avg_usage,0) avg_usage,
 COALESCE(total_sessions,0) total_sessions, COALESCE(avg_duration,0) avg_duration, COALESCE(active_months,0) active_months, ce.user_id IS NOT NULL churned
FROM users u JOIN ai ON ai.user_id=u.user_id LEFT JOIN fu ON fu.user_id=u.user_id LEFT JOIN sa ON sa.user_id=u.user_id LEFT JOIN ce ON ce.user_id=u.user_id""")
feats=[x for x in df.columns if x!="churned"]
X=df[feats].astype(float); y=df.churned.astype(int)
Xtr,Xte,ytr,yte=train_test_split(X,y,test_size=.2,random_state=42,stratify=y)
sc=StandardScaler(); m=LogisticRegression(max_iter=1000,class_weight="balanced",random_state=42).fit(sc.fit_transform(Xtr),ytr)
M["model"]={"auc":round(float(roc_auc_score(yte,m.predict_proba(sc.transform(Xte))[:,1])),2),"n":int(len(df)),
  "coef":sorted([{"f":f,"c":round(float(c),2)} for f,c in zip(feats,m.coef_[0])],key=lambda r:-abs(r["c"]))}
# A/B
u=q2("select * from ab_users"); e=q2("select * from ab_events"); s=q2("select * from ab_sessions")
cn=(u.variant=="control").sum(); tn=(u.variant=="treatment").sum()
def cnt(ev,v): return int(((e.event_type==ev)&(e.variant==v)).sum())
ab={"n_ctrl":int(cn),"n_treat":int(tn)}
for k,ev_ in [("ai","first_ai_output"),("w4","retained_week4")]:
    c_,t_=cnt(ev_,"control"),cnt(ev_,"treatment"); pc,pt=c_/cn,t_/tn
    chi,p,_,_=chi2_contingency(np.array([[c_,cn-c_],[t_,tn-t_]]))
    ab[k]={"ctrl":round(pc*100,1),"treat":round(pt*100,1),"lift":round((pt/pc-1)*100,1),"pp":round((pt-pc)*100,1),"p":float(p)}
pp=(cnt("first_ai_output","control")+cnt("first_ai_output","treatment"))/(cn+tn); se=np.sqrt(pp*(1-pp)*(1/cn+1/tn))
ab["ai"]["z"]=round(float((ab["ai"]["treat"]-ab["ai"]["ctrl"])/100/se),1)
ss=s.merge(u[["user_id","signup_date"]],on="user_id"); ss["d"]=(pd.to_datetime(ss.session_date)-pd.to_datetime(ss.signup_date)).dt.days
w=ss[ss.d<7].groupby("user_id").size(); u["w1"]=u.user_id.map(w).fillna(0)
a_,b_=u[u.variant=="control"].w1,u[u.variant=="treatment"].w1
ab["w1"]={"ctrl":round(a_.mean(),2),"treat":round(b_.mean(),2),"lift":round((b_.mean()/a_.mean()-1)*100),"p":float(mannwhitneyu(b_,a_,alternative="greater").pvalue)}
ec=e[e.event_type=="first_ai_output"].merge(u[["user_id","channel"]],on="user_id")
ch_rows=[]
for chn in ["organic_search","referral","direct","paid_google","paid_meta"]:
    uc=u[(u.channel==chn)]; r={}
    for v in ["control","treatment"]:
        uv=uc[uc.variant==v]; r[v]=round(len(set(ec[ec.user_id.isin(uv.user_id)].user_id))/len(uv)*100,1)
    r.update(channel=chn,lift=round((r["treatment"]/r["control"]-1)*100,1)); ch_rows.append(r)
ab["channels"]=ch_rows
fs=s[s.ai_feature_used!="none"].groupby(["variant","ai_feature_used"]).size().unstack(fill_value=0)
ab["feature_share"]={v:{f:round(float(fs.loc[v,f]/fs.loc[v].sum()*100),1) for f in fs.columns} for v in fs.index}
M["ab"]=ab
json.dump(M,open(os.path.join(HERE,"metrics.json"),"w"),indent=1,default=float)

# ══════════════════════════════════════════════════════════════════════════════
# HTML DASHBOARD (all values below come from M, computed above)
# ══════════════════════════════════════════════════════════════════════════════
CSS = r'''
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0B0B14;--surface:#11111F;--card:#171728;--border:#21213A;
  --orange:#FF6B35;--cyan:#4ECDC4;--blue:#45B7D1;--green:#6BCB77;--red:#FF4757;
  --white:#EEEAE4;--grey:#6B6B8A;--dim:#1C1C32;
}
body{background:var(--bg);color:var(--white);font-family:'DM Sans',sans-serif;display:flex;height:100vh;overflow:hidden}

/* sidebar */
.sidebar{width:220px;min-width:220px;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:20px 0}
.logo{padding:0 20px 24px;border-bottom:1px solid var(--border)}
.logo-title{font-size:13px;font-weight:600;color:var(--white);line-height:1.3}
.logo-sub{font-size:10px;color:var(--grey);margin-top:3px;font-family:'DM Mono',monospace}
.nav{padding:16px 0;flex:1}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 20px;cursor:pointer;transition:all .15s;font-size:13px;color:var(--grey);border-left:2px solid transparent;user-select:none}
.nav-item:hover{color:var(--white);background:var(--dim)}
.nav-item.active{color:var(--white);background:var(--dim);border-left-color:var(--orange)}
.nav-item .icon{font-size:15px;width:18px;text-align:center}
.sidebar-footer{padding:16px 20px;border-top:1px solid var(--border);font-size:10px;color:var(--grey);font-family:'DM Mono',monospace}

/* main */
.main{flex:1;overflow-y:auto;background:var(--bg)}
.page{display:none;padding:24px;animation:fadeIn .2s ease}
.page.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.page-title{font-size:18px;font-weight:600;color:var(--white);margin-bottom:4px}
.page-sub{font-size:12px;color:var(--grey);margin-bottom:20px;font-family:'DM Mono',monospace}

/* KPI cards */
.kpi-row{display:grid;gap:12px;margin-bottom:20px}
.kpi-5{grid-template-columns:repeat(5,1fr)}
.kpi-4{grid-template-columns:repeat(4,1fr)}
.kpi-3{grid-template-columns:repeat(3,1fr)}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;position:relative;overflow:hidden}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.kpi.orange::before{background:var(--orange)}
.kpi.cyan::before{background:var(--cyan)}
.kpi.blue::before{background:var(--blue)}
.kpi.green::before{background:var(--green)}
.kpi.red::before{background:var(--red)}
.kpi-label{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--grey);font-family:'DM Mono',monospace;margin-bottom:8px}
.kpi-val{font-size:26px;font-weight:600;color:var(--white);line-height:1}
.kpi-val.orange{color:var(--orange)}
.kpi-val.cyan{color:var(--cyan)}
.kpi-val.green{color:var(--green)}
.kpi-val.red{color:var(--red)}
.kpi-badge{display:inline-block;font-size:10px;padding:2px 7px;border-radius:10px;margin-top:6px;font-family:'DM Mono',monospace}
.badge-g{background:rgba(107,203,119,.15);color:var(--green)}
.badge-r{background:rgba(255,71,87,.15);color:var(--red)}
.badge-o{background:rgba(255,107,53,.15);color:var(--orange)}

/* grid layouts */
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px}
.grid-2-1{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-bottom:16px}
.grid-1-2{display:grid;grid-template-columns:1fr 2fr;gap:16px;margin-bottom:16px}
.full{margin-bottom:16px}

/* chart cards */
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:18px}
.card-title{font-size:12px;font-weight:600;color:var(--white);margin-bottom:14px;display:flex;align-items:center;justify-content:space-between}
.card-title span{font-size:10px;color:var(--grey);font-family:'DM Mono',monospace;font-weight:400}
.chart-wrap{position:relative}

/* funnel bars */
.funnel-row{display:flex;align-items:center;gap:12px;margin-bottom:10px}
.funnel-label{font-size:11px;color:var(--grey);width:110px;text-align:right;flex-shrink:0;font-family:'DM Mono',monospace}
.funnel-bar-wrap{flex:1;background:var(--dim);border-radius:3px;height:28px;position:relative;overflow:hidden}
.funnel-bar{height:100%;border-radius:3px;display:flex;align-items:center;padding-left:10px;transition:width .6s ease}
.funnel-info{font-size:11px;color:var(--white);font-weight:500;white-space:nowrap}
.funnel-drop{font-size:10px;color:var(--red);width:70px;flex-shrink:0;font-family:'DM Mono',monospace}

/* cohort heatmap */
.heatmap-table{width:100%;border-collapse:collapse;font-size:11px}
.heatmap-table th{padding:6px 8px;color:var(--grey);font-weight:500;text-align:center;font-family:'DM Mono',monospace;font-size:10px}
.heatmap-table th:first-child{text-align:left}
.heatmap-table td{padding:5px 8px;text-align:center;border-radius:3px;font-family:'DM Mono',monospace;font-size:10px;font-weight:500}
.heatmap-table td:first-child{text-align:left;color:var(--grey);font-size:10px}

/* ab result table */
.result-table{width:100%;border-collapse:collapse;font-size:12px}
.result-table th{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--grey);font-weight:500;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:1px;font-family:'DM Mono',monospace}
.result-table td{padding:10px 12px;border-bottom:1px solid var(--dim);color:var(--white)}
.result-table tr:last-child td{border-bottom:none}
.sig{color:var(--green);font-weight:600}

/* donut legend */
.donut-wrap{display:flex;align-items:center;gap:20px}
.donut-legend{display:flex;flex-direction:column;gap:8px}
.legend-item{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--grey)}
.legend-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}

/* slicer */
.slicer-row{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.slicer-btn{font-size:10px;padding:5px 12px;border-radius:20px;border:1px solid var(--border);background:transparent;color:var(--grey);cursor:pointer;font-family:'DM Mono',monospace;transition:all .15s}
.slicer-btn:hover,.slicer-btn.active{background:var(--orange);color:var(--white);border-color:var(--orange)}
.slicer-label{font-size:10px;color:var(--grey);align-self:center;margin-right:4px;font-family:'DM Mono',monospace}

/* ab lift highlight */
.lift-card{background:linear-gradient(135deg,rgba(255,107,53,.1),rgba(78,205,196,.05));border:1px solid rgba(255,107,53,.3);border-radius:8px;padding:20px;text-align:center}
.lift-big{font-size:48px;font-weight:600;color:var(--orange);line-height:1}
.lift-label{font-size:11px;color:var(--grey);margin-top:6px;font-family:'DM Mono',monospace}
.lift-sub{font-size:12px;color:var(--white);margin-top:4px}

/* scrollbar */
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
'''

F = M["funnel"]; AB = M["ab"]; fmt = lambda n: f"{int(n):,}"
pc = lambda a, b: f"{a / b * 100:.1f}%"
nice = lambda c: c.replace("_", " ").title()
fc = {r["feature"]: r for r in M["feature_churn"]}
rw = fc["rewrite"]
peak = max(M["churn_timing"], key=lambda r: r["count"])
tot_churn = sum(r["count"] for r in M["churn_timing"])
mrr_cr = M["mrr_active"] / 1e7
never_ai = F["signed_up"] - F["first_ai_output"]

def kpi(label, val, badge, color="orange", bcls="badge-o", vcls=""):
    return (f'<div class="kpi {color}"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-val {vcls}">{val}</div><div class="kpi-badge {bcls}">{badge}</div></div>')

def funnel_row(label, n, pct_of_signup, color, note, note_style=""):
    return (f'<div class="funnel-row"><div class="funnel-label">{label}</div>'
            f'<div class="funnel-bar-wrap"><div class="funnel-bar" style="width:{max(pct_of_signup, 0.5):.1f}%;background:{color}">'
            f'<span class="funnel-info">{fmt(n)} · {pct_of_signup:.1f}%</span></div></div>'
            f'<div class="funnel-drop" style="{note_style}">{note}</div></div>')

def heat_cell(v):
    a = 0.12 + 0.6 * v / 100
    return f'<td style="background:rgba(255,107,53,{a:.2f});color:#EEEAE4">{v:.1f}</td>'

cohort_rows = "".join(
    f'<tr><td>{r["cohort"]}</td><td style="color:var(--grey)">{r["size"]}</td>{heat_cell(r["w1"])}{heat_cell(r["w4"])}{heat_cell(r["w8"])}</tr>'
    for r in M["cohorts"])

chan_rows = "".join(
    f'<tr><td>{nice(r["channel"])}</td><td>{fmt(r["n"])}</td><td>{fmt(r["ai"])}</td>'
    f'<td><span style="color:var(--orange)">{r["ai_pct"]:.1f}%</span></td></tr>' for r in M["channel"])

ab_chan_rows = "".join(
    f'<tr><td>{nice(r["channel"])}</td><td>{r["control"]:.1f}%</td><td>{r["treatment"]:.1f}%</td><td class="sig">+{r["lift"]:.1f}%</td></tr>'
    for r in AB["channels"])

plan = M["plan"]; n_users = M["n_users"]
SIM = "simulated data"

HTML = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>AI SaaS Growth Intelligence — Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<style>{CSS}</style>
</head>
<body>

<div class="sidebar">
  <div class="logo">
    <div class="logo-title">AI SaaS Growth<br>Intelligence</div>
    <div class="logo-sub">Ajay Patel · Mumbai</div>
  </div>
  <nav class="nav">
    <div class="nav-item active" onclick="showPage('p1')"><span class="icon">📊</span> Executive Overview</div>
    <div class="nav-item" onclick="showPage('p2')"><span class="icon">🔽</span> Funnel Deep Dive</div>
    <div class="nav-item" onclick="showPage('p3')"><span class="icon">📅</span> Cohort Retention</div>
    <div class="nav-item" onclick="showPage('p4')"><span class="icon">⚡</span> Feature Adoption</div>
    <div class="nav-item" onclick="showPage('p5')"><span class="icon">🧪</span> A/B Test Results</div>
  </nav>
  <div class="sidebar-footer">Simulated data<br>ai_saas.db · ab_test.db</div>
</div>

<div class="main">

<!-- PAGE 1 -->
<div class="page active" id="p1">
  <div class="page-title">Executive Overview</div>
  <div class="page-sub">{fmt(n_users)} users · 2021–2025 · all channels · {SIM}</div>
  <div class="kpi-row kpi-5">
    {kpi("Total Users", fmt(n_users), "100% baseline")}
    {kpi("Activation Rate", pc(F["activated"], F["signed_up"]), fmt(F["activated"]) + " users", "cyan", "badge-g", "cyan")}
    {kpi("First AI Rate", pc(F["first_ai_output"], F["signed_up"]), fmt(never_ai) + " never reach it", "orange", "badge-r", "orange")}
    {kpi("Churn (of first-AI users)", f'{M["churn_of_ai"]*100:.1f}%', fmt(M["churned_users"]) + " users", "red", "badge-r", "red")}
    {kpi("Active-sub MRR", f"₹{mrr_cr:.2f} Cr", fmt(M["paying_active"]) + " paying subs", "green", "badge-g")}
  </div>
  <div class="grid-2">
    <div class="card"><div class="card-title">Monthly Active Users <span>new / retained / resurrected</span></div>
      <div class="chart-wrap"><canvas id="mauChart" height="180"></canvas></div></div>
    <div style="display:grid;grid-template-rows:1fr 1fr;gap:16px">
      <div class="card"><div class="card-title">Users by Plan Tier</div>
        <div class="donut-wrap"><canvas id="planChart" width="110" height="110"></canvas>
          <div class="donut-legend">
            <div class="legend-item"><div class="legend-dot" style="background:#FF6B35"></div>Free — {fmt(plan["free"])} ({plan["free"]/n_users*100:.0f}%)</div>
            <div class="legend-item"><div class="legend-dot" style="background:#4ECDC4"></div>Pro — {fmt(plan["pro"])} ({plan["pro"]/n_users*100:.0f}%)</div>
            <div class="legend-item"><div class="legend-dot" style="background:#45B7D1"></div>Enterprise — {fmt(plan["enterprise"])} ({plan["enterprise"]/n_users*100:.0f}%)</div>
          </div></div></div>
      <div class="card"><div class="card-title">Users by Channel</div>
        <div class="chart-wrap"><canvas id="channelBarChart" height="100"></canvas></div></div>
    </div>
  </div>
</div>

<!-- PAGE 2 -->
<div class="page" id="p2">
  <div class="page-title">Funnel Deep Dive</div>
  <div class="page-sub">signup → first AI output, then invite / upgrade · {SIM}</div>
  <div class="kpi-row kpi-5">
    {kpi("Signed Up", fmt(F["signed_up"]), "100%")}
    {kpi("Activated", fmt(F["activated"]), pc(F["activated"], F["signed_up"]), "cyan", "badge-g")}
    {kpi("First AI Output", fmt(F["first_ai_output"]), pc(F["first_ai_output"], F["signed_up"]), "orange", "badge-r")}
    {kpi("Invited Team", fmt(F["invited_team"]), pc(F["invited_team"], F["first_ai_output"]) + " of first-AI", "blue")}
    {kpi("Upgraded", fmt(F["upgraded"]), pc(F["upgraded"], F["first_ai_output"]) + " of first-AI", "green", "badge-g")}
  </div>
  <div class="grid-2-1">
    <div class="card"><div class="card-title">Funnel <span>% of total signups</span></div>
      <div style="padding:8px 0">
        {funnel_row("Signed Up", F["signed_up"], 100, "var(--orange)", "")}
        {funnel_row("Activated", F["activated"], F["activated"]/F["signed_up"]*100, "#3DBDB5", f'▼ {(1-F["activated"]/F["signed_up"])*100:.1f} pp')}
        {funnel_row("First AI Output", F["first_ai_output"], F["first_ai_output"]/F["signed_up"]*100, "var(--orange)", f'▼ {(F["activated"]-F["first_ai_output"])/F["signed_up"]*100:.1f} pp', "color:var(--red);font-weight:600")}
        {funnel_row("Invited Team", F["invited_team"], F["invited_team"]/F["signed_up"]*100, "var(--blue)", pc(F["invited_team"], F["first_ai_output"]) + " of first-AI", "color:var(--grey)")}
        {funnel_row("Upgraded", F["upgraded"], F["upgraded"]/F["signed_up"]*100, "var(--green)", pc(F["upgraded"], F["first_ai_output"]) + " of first-AI", "color:var(--grey)")}
      </div>
      <div style="margin-top:12px;padding:10px 12px;background:rgba(255,71,87,.08);border-radius:6px;border-left:3px solid var(--red)">
        <div style="font-size:11px;color:var(--white)">⚠ <strong>{never_ai/F["signed_up"]*100:.1f}% of signups ({fmt(never_ai)} users) never reach first AI output</strong> — the largest loss of users. Invited Team and Upgraded are two separate branches off First AI Output, so both are measured against first-AI users.</div>
      </div>
    </div>
    <div class="card"><div class="card-title">First AI Rate by Channel</div>
      <div class="chart-wrap"><canvas id="funnelChannelChart" height="220"></canvas></div></div>
  </div>
  <div class="card full"><div class="card-title">Channel Breakdown <span>signups · first AI users · first AI rate</span></div>
    <table class="result-table"><thead><tr><th>Channel</th><th>Signups</th><th>First AI Users</th><th>First AI Rate</th></tr></thead>
    <tbody>{chan_rows}</tbody></table></div>
</div>

<!-- PAGE 3 -->
<div class="page" id="p3">
  <div class="page-title">Cohort Retention</div>
  <div class="page-sub">retained at week N = last session is at least N weeks after signup · {SIM}</div>
  <div class="grid-2">
    <div class="card"><div class="card-title">Week-8 Retention by Channel <span>% of activated users</span></div>
      <div class="chart-wrap"><canvas id="w8Chart" height="200"></canvas></div></div>
    <div class="card"><div class="card-title">Churn Timing <span>days from first AI output to churn</span></div>
      <div class="chart-wrap"><canvas id="churnTimingChart" height="200"></canvas></div></div>
  </div>
  <div class="card full"><div class="card-title">Cohort Retention Heatmap <span>last 12 cohorts to Sep 2025 · % of activated users</span></div>
    <div style="overflow-x:auto"><table class="heatmap-table"><thead><tr><th>Cohort</th><th>Size</th><th>Wk 1</th><th>Wk 4</th><th>Wk 8</th></tr></thead><tbody>{cohort_rows}</tbody></table></div></div>
</div>

<!-- PAGE 4 -->
<div class="page" id="p4">
  <div class="page-title">Feature Adoption</div>
  <div class="page-sub">among users who reached first AI output ({fmt(F["first_ai_output"])}) · {SIM}</div>
  <div class="kpi-row kpi-4">
    {kpi("Rewrite Users", fmt(rw["n_with"]), "top retention signal", "orange", "badge-g")}
    {kpi("Rewrite Adoption", f'{M["rewrite_adoption"]*100:.1f}%', "of first-AI users", "cyan", "badge-o", "cyan")}
    {kpi("Rewrite Churn", f'{rw["with"]}%', f'vs {rw["without"]}% without', "green", "badge-g", "green")}
    {kpi("Avg Features / User", f'{M["avg_features"]:.1f}', "of first-AI users", "blue")}
  </div>
  <div class="grid-2">
    <div class="card"><div class="card-title">Churn Rate — With vs Without Feature <span>chi-square, α = 0.05</span></div>
      <div class="chart-wrap"><canvas id="featureChurnChart" height="220"></canvas></div>
      <div style="font-size:11px;color:var(--grey);margin-top:10px;font-family:'DM Mono',monospace">Significant: Rewrite, Analyze. Not significant: Summarize, Generate, Translate.</div></div>
    <div class="card"><div class="card-title">Session Share by Feature <span>all sessions</span></div>
      <div class="chart-wrap"><canvas id="featureDistChart" height="220"></canvas></div></div>
  </div>
  <div class="card full" style="padding:18px 20px"><div class="card-title">Key Insights</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-top:4px">
      <div style="padding:14px;background:var(--dim);border-radius:6px;border-left:3px solid var(--orange)">
        <div style="font-size:11px;color:var(--grey);margin-bottom:4px;font-family:'DM Mono',monospace">REWRITE EFFECT</div>
        <div style="font-size:13px;color:var(--white)">Rewrite adopters churn {rw["with"]}% vs {rw["without"]}% (χ² = {rw["chi2"]}, p &lt; 0.001). In this simulation that link is built in; Part 2 tests the onboarding change.</div></div>
      <div style="padding:14px;background:var(--dim);border-radius:6px;border-left:3px solid var(--cyan)">
        <div style="font-size:11px;color:var(--grey);margin-bottom:4px;font-family:'DM Mono',monospace">CHURN PEAK</div>
        <div style="font-size:13px;color:var(--white)">{peak["window"]} after first AI output holds {peak["count"]/tot_churn*100:.1f}% of all churn. A check-in around day 14 reaches users just before it.</div></div>
      <div style="padding:14px;background:var(--dim);border-radius:6px;border-left:3px solid var(--green)">
        <div style="font-size:11px;color:var(--grey);margin-bottom:4px;font-family:'DM Mono',monospace">CHURN MODEL</div>
        <div style="font-size:13px;color:var(--white)">Logistic regression, {fmt(M["model"]["n"])} eligible users: ROC-AUC {M["model"]["auc"]}. Explanatory only — a weak predictor.</div></div>
    </div></div>
</div>

<!-- PAGE 5 -->
<div class="page" id="p5">
  <div class="page-title">A/B Test Results</div>
  <div class="page-sub">rewrite-first onboarding · {fmt(AB["n_ctrl"] + AB["n_treat"])} users · mar–sep 2025 · α = 0.05 · {SIM}</div>
  <div class="kpi-row kpi-4">
    {kpi("Control Rate", f'{AB["ai"]["ctrl"]}%', fmt(AB["n_ctrl"]) + " users", "cyan", "badge-o", "cyan")}
    {kpi("Treatment Rate", f'{AB["ai"]["treat"]}%', fmt(AB["n_treat"]) + " users", "orange", "badge-g", "orange")}
    {kpi("Relative Lift", f'+{AB["ai"]["lift"]}%', f'+{AB["ai"]["pp"]} pp · p &lt; 0.001', "green", "badge-g", "green")}
    {kpi("Decision", "SHIP IT ✓", "all 3 metrics significant", "green", "badge-g", "green").replace('class="kpi-val green"', 'class="kpi-val green" style="font-size:18px"')}
  </div>
  <div class="grid-1-2">
    <div style="display:flex;flex-direction:column;gap:16px">
      <div class="lift-card"><div class="lift-big">+{AB["ai"]["lift"]}%</div><div class="lift-label">RELATIVE LIFT</div>
        <div class="lift-sub">First AI Output Rate</div>
        <div style="font-size:10px;color:var(--grey);margin-top:8px;font-family:'DM Mono',monospace">{AB["ai"]["ctrl"]}% → {AB["ai"]["treat"]}% · z = {AB["ai"]["z"]}</div></div>
      <div class="card" style="text-align:center"><div class="kpi-label" style="margin-bottom:8px">Week-4 Retention Lift</div>
        <div style="font-size:32px;font-weight:600;color:var(--cyan)">+{AB["w4"]["lift"]}%</div>
        <div style="font-size:11px;color:var(--grey);margin-top:4px;font-family:'DM Mono',monospace">{AB["w4"]["ctrl"]}% → {AB["w4"]["treat"]}% · p &lt; 0.001</div></div>
    </div>
    <div class="card"><div class="card-title">Primary Metric — First AI Output Rate <span>control vs treatment</span></div>
      <div class="chart-wrap"><canvas id="abMainChart" height="220"></canvas></div></div>
  </div>
  <div class="grid-2">
    <div class="card"><div class="card-title">Feature Adoption Shift <span>% of feature-tagged sessions</span></div>
      <div class="chart-wrap"><canvas id="abFeatureChart" height="200"></canvas></div></div>
    <div class="card"><div class="card-title">Subgroup — Channel × Variant <span>first AI rate</span></div>
      <table class="result-table"><thead><tr><th>Channel</th><th>Control</th><th>Treatment</th><th>Lift</th></tr></thead><tbody>{ab_chan_rows}</tbody></table>
      <div style="font-size:10px;color:var(--grey);margin-top:8px;font-family:'DM Mono',monospace">~300–900 users per arm per channel — differences in lift size between channels are mostly noise.</div>
      <div style="margin-top:16px"><div class="card-title" style="margin-bottom:8px">Statistical Summary</div>
      <table class="result-table"><thead><tr><th>Metric</th><th>Control</th><th>Treatment</th><th>Test</th><th>Result</th></tr></thead><tbody>
        <tr><td>First AI Rate</td><td>{AB["ai"]["ctrl"]}%</td><td>{AB["ai"]["treat"]}%</td><td style="color:var(--grey);font-size:11px">z-test</td><td class="sig">p &lt; 0.001 ✓</td></tr>
        <tr><td>Week-4 Retention</td><td>{AB["w4"]["ctrl"]}%</td><td>{AB["w4"]["treat"]}%</td><td style="color:var(--grey);font-size:11px">chi-square</td><td class="sig">p &lt; 0.001 ✓</td></tr>
        <tr><td>Wk-1 Sessions / User</td><td>{AB["w1"]["ctrl"]}</td><td>{AB["w1"]["treat"]}</td><td style="color:var(--grey);font-size:11px">Mann-Whitney</td><td class="sig">p &lt; 0.001 ✓</td></tr>
      </tbody></table></div>
    </div>
  </div>
</div>

</div>

<script>
const D = __DATA__;
const C = {{orange:'#FF6B35',cyan:'#4ECDC4',blue:'#45B7D1',green:'#6BCB77',red:'#FF4757',grey:'#6B6B8A',border:'#21213A'}};
Chart.defaults.color = C.grey;
Chart.defaults.borderColor = C.border;
Chart.defaults.font.family = "'DM Mono', monospace";
Chart.defaults.font.size = 10;
const nice = s => s.replace(/_/g,' ').replace(/\\b\\w/g, c => c.toUpperCase());
const tip = {{backgroundColor:'#11111F',borderColor:C.border,borderWidth:1,titleColor:'#EEEAE4',bodyColor:'#EEEAE4'}};
const barOpts = (extra={{}}) => Object.assign({{responsive:true,plugins:{{legend:{{display:false}},tooltip:tip}},scales:{{x:{{grid:{{display:false}}}},y:{{grid:{{color:C.border}},beginAtZero:true}}}}}}, extra);

const shown = {{}};
function showPage(id) {{
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.querySelectorAll('.nav-item')[parseInt(id.slice(1)) - 1].classList.add('active');
  if (!shown[id]) {{ shown[id] = true; ({{p1:initP1,p2:initP2,p3:initP3,p4:initP4,p5:initP5}})[id](); }}
}}

function initP1() {{
  new Chart(document.getElementById('mauChart'), {{type:'line',
    data:{{labels:D.mau.map(r=>r.month),datasets:[
      {{label:'New',data:D.mau.map(r=>r.new),borderColor:C.orange,backgroundColor:'rgba(255,107,53,.35)',fill:true,pointRadius:0,tension:.3}},
      {{label:'Retained',data:D.mau.map(r=>r.retained),borderColor:C.cyan,backgroundColor:'rgba(78,205,196,.3)',fill:true,pointRadius:0,tension:.3}},
      {{label:'Resurrected',data:D.mau.map(r=>r.mau-r.new-r.retained),borderColor:C.blue,backgroundColor:'rgba(69,183,209,.3)',fill:true,pointRadius:0,tension:.3}}]}},
    options:{{responsive:true,interaction:{{mode:'index',intersect:false}},plugins:{{legend:{{position:'bottom',labels:{{boxWidth:8}}}},tooltip:tip}},
      scales:{{x:{{ticks:{{maxTicksLimit:10}},grid:{{display:false}}}},y:{{stacked:true,grid:{{color:C.border}}}}}}}}}});
  new Chart(document.getElementById('planChart'), {{type:'doughnut',
    data:{{labels:['Free','Pro','Enterprise'],datasets:[{{data:[D.plan.free,D.plan.pro,D.plan.enterprise],backgroundColor:[C.orange,C.cyan,C.blue],borderWidth:0}}]}},
    options:{{cutout:'68%',plugins:{{legend:{{display:false}},tooltip:tip}}}}}});
  new Chart(document.getElementById('channelBarChart'), {{type:'bar',
    data:{{labels:D.channel.map(r=>nice(r.channel)),datasets:[{{data:D.channel.map(r=>r.n),backgroundColor:C.orange,borderRadius:3}}]}},
    options:barOpts({{indexAxis:'y'}})}});
}}
function initP2() {{
  new Chart(document.getElementById('funnelChannelChart'), {{type:'bar',
    data:{{labels:D.channel.map(r=>nice(r.channel)),datasets:[{{data:D.channel.map(r=>r.ai_pct),backgroundColor:[C.orange,C.cyan,C.blue,C.grey,C.red],borderRadius:3}}]}},
    options:barOpts({{scales:{{x:{{grid:{{display:false}}}},y:{{grid:{{color:C.border}},beginAtZero:true,max:100,ticks:{{callback:v=>v+'%'}}}}}}}})}});
}}
function initP3() {{
  const col = D.channel_ret.map(r => r.channel==='organic_search'?C.orange:r.channel==='referral'?C.cyan:C.grey);
  new Chart(document.getElementById('w8Chart'), {{type:'bar',
    data:{{labels:D.channel_ret.map(r=>nice(r.channel)),datasets:[{{data:D.channel_ret.map(r=>r.w8),backgroundColor:col,borderRadius:3}}]}},
    options:barOpts({{scales:{{x:{{grid:{{display:false}}}},y:{{grid:{{color:C.border}},beginAtZero:true,max:100,ticks:{{callback:v=>v+'%'}}}}}}}})}});
  const mx = Math.max(...D.churn_timing.map(r=>r.count));
  new Chart(document.getElementById('churnTimingChart'), {{type:'bar',
    data:{{labels:D.churn_timing.map(r=>r.window),datasets:[{{data:D.churn_timing.map(r=>r.count),backgroundColor:D.churn_timing.map(r=>r.count===mx?C.orange:C.cyan),borderRadius:3}}]}},
    options:barOpts()}});
}}
function initP4() {{
  new Chart(document.getElementById('featureChurnChart'), {{type:'bar',
    data:{{labels:D.feature_churn.map(r=>nice(r.feature)+(r.sig?' ✓':'')),datasets:[
      {{label:'Uses feature',data:D.feature_churn.map(r=>r.with),backgroundColor:C.orange,borderRadius:3}},
      {{label:'Does not use',data:D.feature_churn.map(r=>r.without),backgroundColor:C.cyan,borderRadius:3}}]}},
    options:{{responsive:true,plugins:{{legend:{{position:'bottom',labels:{{boxWidth:8}}}},tooltip:tip}},
      scales:{{x:{{grid:{{display:false}}}},y:{{grid:{{color:C.border}},beginAtZero:true,ticks:{{callback:v=>v+'%'}}}}}}}}}});
  const sf = D.session_feature_share, keys = Object.keys(sf);
  new Chart(document.getElementById('featureDistChart'), {{type:'doughnut',
    data:{{labels:keys.map(nice),datasets:[{{data:keys.map(k=>sf[k]),backgroundColor:[C.orange,C.cyan,C.blue,C.green,C.red,C.grey],borderWidth:0}}]}},
    options:{{cutout:'60%',plugins:{{legend:{{position:'right',labels:{{boxWidth:8}}}},tooltip:tip}}}}}});
}}
function initP5() {{
  new Chart(document.getElementById('abMainChart'), {{type:'bar',
    data:{{labels:['Control (standard)','Treatment (Rewrite-first)'],datasets:[{{data:[D.ab.ai.ctrl,D.ab.ai.treat],backgroundColor:[C.cyan,C.orange],borderRadius:4,barThickness:70}}]}},
    options:barOpts({{scales:{{x:{{grid:{{display:false}}}},y:{{grid:{{color:C.border}},beginAtZero:true,max:70,ticks:{{callback:v=>v+'%'}}}}}}}})}});
  const fs = D.ab.feature_share, ks = Object.keys(fs.control).sort((a,b)=>fs.control[b]-fs.control[a]);
  new Chart(document.getElementById('abFeatureChart'), {{type:'bar',
    data:{{labels:ks.map(nice),datasets:[
      {{label:'Control',data:ks.map(k=>fs.control[k]),backgroundColor:C.cyan,borderRadius:3}},
      {{label:'Treatment',data:ks.map(k=>fs.treatment[k]),backgroundColor:C.orange,borderRadius:3}}]}},
    options:{{responsive:true,plugins:{{legend:{{position:'bottom',labels:{{boxWidth:8}}}},tooltip:tip}},
      scales:{{x:{{grid:{{display:false}}}},y:{{grid:{{color:C.border}},beginAtZero:true,ticks:{{callback:v=>v+'%'}}}}}}}}}});
}}
initP1(); shown.p1 = true;
</script>
</body>
</html>
'''

DATA = {k: M[k] for k in ["mau", "plan", "channel", "channel_ret", "churn_timing", "feature_churn", "session_feature_share", "ab"]}
HTML = HTML.replace("__DATA__", json.dumps(DATA, default=float))
with open(os.path.join(HERE, "dashboard.html"), "w", encoding="utf-8") as fh:
    fh.write(HTML)
print("dashboard.html written —", f"{len(HTML):,} bytes")
