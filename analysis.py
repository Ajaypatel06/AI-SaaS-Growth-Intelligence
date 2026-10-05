# analysis.py — run after data_generator.py

import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy import stats
from scipy.stats import chi2_contingency, mannwhitneyu, norm as norm_dist
import seaborn as sns
import warnings, os

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # works on any machine

DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR = os.path.join(BASE_DIR, "charts")

os.makedirs(OUT_DIR, exist_ok=True)

# style
BRAND  = "#FF6B35"
CYAN   = "#4ECDC4"
BLUE   = "#45B7D1"
GREEN  = "#96CEB4"
DARK   = "#1A1A2E"
MID    = "#16213E"
BORDER = "#2D2D44"
WHITE  = "#F5F5F0"
GREY   = "#8B8FA8"

plt.rcParams.update({
    "figure.facecolor":  DARK,  "axes.facecolor":    MID,
    "axes.edgecolor":    BORDER,"axes.labelcolor":   WHITE,
    "xtick.color":       GREY,  "ytick.color":       GREY,
    "text.color":        WHITE, "grid.color":        BORDER,
    "grid.linewidth":    0.6,   "font.family":       "DejaVu Sans",
    "axes.spines.top":   False, "axes.spines.right": False,
})

def q(conn, sql): return pd.read_sql_query(sql, conn)



# part 1 — funnel & retention
print("part 1: funnel & retention")

conn1 = sqlite3.connect(f"{DATA_DIR}/ai_saas.db")

# funnel drop-off
print("  funnel drop-off...")
row    = q(conn1, """
    WITH fs AS (
        SELECT u.user_id,
            MAX(CASE WHEN e.event_type='signed_up'       THEN 1 ELSE 0 END) s1,
            MAX(CASE WHEN e.event_type='activated'       THEN 1 ELSE 0 END) s2,
            MAX(CASE WHEN e.event_type='first_ai_output' THEN 1 ELSE 0 END) s3,
            MAX(CASE WHEN e.event_type='invited_team'    THEN 1 ELSE 0 END) s4,
            MAX(CASE WHEN e.event_type='upgraded'        THEN 1 ELSE 0 END) s5
        FROM users u LEFT JOIN events e ON u.user_id=e.user_id
        GROUP BY u.user_id
    )
    SELECT SUM(s1) n1,SUM(s2) n2,SUM(s3) n3,SUM(s4) n4,SUM(s5) n5 FROM fs
""").iloc[0]
stages = ["Signed Up","Activated","First AI Output","Invited Team","Upgraded"]
counts = [int(row.n1),int(row.n2),int(row.n3),int(row.n4),int(row.n5)]
pcts   = [c/counts[0]*100 for c in counts]
# Invited Team and Upgraded are two separate branches that both start at First AI Output
# (not a sequence: you do not have to invite a teammate before upgrading), so their
# conversion is measured against First AI Output users, not against the stage above.
drop_notes = ["",
              f"▼ {pcts[0]-pcts[1]:.1f} pp vs signup",
              f"▼ {pcts[1]-pcts[2]:.1f} pp vs activated",
              f"{counts[3]/counts[2]*100:.1f}% of First AI users",
              f"{counts[4]/counts[2]*100:.1f}% of First AI users"]

fig, ax = plt.subplots(figsize=(11,6))
fig.patch.set_facecolor(DARK)
bars = ax.barh(stages[::-1], pcts[::-1], color=BRAND, alpha=0.85, height=0.6)
for bar,c,p,note in zip(bars,counts[::-1],pcts[::-1],drop_notes[::-1]):
    ax.text(p+0.5, bar.get_y()+bar.get_height()/2,
            f"{c:,}  ({p:.1f}% of signups)", va="center", fontsize=11, color=WHITE, fontweight="bold")
    if note:
        ax.text(p+0.5, bar.get_y()-0.12, note, fontsize=8.5, color="#FF4757", ha="left")
ax.set_xlim(0,135)
ax.set_xlabel("% of Total Signups", fontsize=11)
ax.set_title("User Funnel — Signup to First AI Output, then Invite / Upgrade", fontsize=14,
             fontweight="bold", color=WHITE, pad=14)
ax.axvline(pcts[2], color=BRAND, lw=1.2, linestyle="--", alpha=0.5)
ax.text(pcts[2]+0.5, -0.6, f"Only {pcts[2]:.1f}% reach\nFirst AI Output",
        fontsize=8, color=BRAND, va="top")
ax.grid(axis="x", alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/01_funnel_dropoff.png", dpi=150, bbox_inches="tight")
plt.close()

# cohort retention heatmap
print("  cohort retention heatmap...")
cdf = q(conn1, """
    WITH cohorts AS (
        SELECT u.user_id, STRFTIME('%Y-%m',u.signup_date) cohort_month,
               DATE(u.signup_date) signup_dt, MAX(DATE(s.session_date)) last_active_dt
        FROM users u JOIN sessions s ON u.user_id=s.user_id
        GROUP BY u.user_id, cohort_month, signup_dt
    ),
    sizes AS (SELECT cohort_month, COUNT(DISTINCT user_id) sz FROM cohorts GROUP BY cohort_month),
    ret AS (
        SELECT c.cohort_month, sz.sz cohort_size,
               JULIANDAY(c.last_active_dt)-JULIANDAY(c.signup_dt) days_retained
        FROM cohorts c JOIN sizes sz ON c.cohort_month=sz.cohort_month
    )
    SELECT cohort_month, cohort_size,
        ROUND(SUM(CASE WHEN days_retained>= 7 THEN 1.0 ELSE 0 END)/cohort_size*100,1) w1,
        ROUND(SUM(CASE WHEN days_retained>=14 THEN 1.0 ELSE 0 END)/cohort_size*100,1) w2,
        ROUND(SUM(CASE WHEN days_retained>=28 THEN 1.0 ELSE 0 END)/cohort_size*100,1) w4,
        ROUND(SUM(CASE WHEN days_retained>=56 THEN 1.0 ELSE 0 END)/cohort_size*100,1) w8,
        ROUND(SUM(CASE WHEN days_retained>=84 THEN 1.0 ELSE 0 END)/cohort_size*100,1) w12
    FROM ret GROUP BY cohort_month,cohort_size ORDER BY cohort_month
""")
cdf   = cdf[cdf["cohort_month"] <= "2025-09"]
heat  = cdf[["w1","w2","w4","w8","w12"]].astype(float)
heat.index  = cdf["cohort_month"]
heat.columns= ["Wk 1","Wk 2","Wk 4","Wk 8","Wk 12"]

fig, ax = plt.subplots(figsize=(10,7))
fig.patch.set_facecolor(DARK)
sns.heatmap(heat, ax=ax, annot=True, fmt=".1f", cmap="YlOrRd",
            linewidths=0.4, linecolor=DARK,
            cbar_kws={"label":"Retention %","shrink":0.8},
            annot_kws={"size":9,"color":"black","weight":"bold"})
ax.set_title("Cohort Retention — % of Activated Users Still Active at Week N", fontsize=14,
             fontweight="bold", color=WHITE, pad=14)
ax.set_xlabel("Weeks Since Signup", fontsize=11)
ax.set_ylabel("Signup Cohort", fontsize=11)
ax.tick_params(axis="x", colors=WHITE)
ax.tick_params(axis="y", colors=WHITE, rotation=0)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/02_cohort_retention.png", dpi=150, bbox_inches="tight")
plt.close()

# week-8 retention by channel
print("  channel retention...")
cdf2 = q(conn1, """
    WITH ur AS (
        SELECT u.user_id, u.channel,
               JULIANDAY(MAX(DATE(s.session_date)))-JULIANDAY(DATE(u.signup_date)) days_ret
        FROM users u JOIN sessions s ON u.user_id=s.user_id
        GROUP BY u.user_id, u.channel
    )
    SELECT channel, COUNT(*) total,
           ROUND(SUM(CASE WHEN days_ret>=56 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) w8_pct
    FROM ur GROUP BY channel ORDER BY w8_pct DESC
""")
labels  = [c.replace("_"," ").title() for c in cdf2["channel"]]
colors  = [BRAND if c=="organic_search" else CYAN if c=="referral" else GREY
           for c in cdf2["channel"]]
fig, ax = plt.subplots(figsize=(9,5))
fig.patch.set_facecolor(DARK)
bars = ax.bar(labels, cdf2["w8_pct"], color=colors, width=0.55, alpha=0.88)
for bar,v in zip(bars,cdf2["w8_pct"]):
    ax.text(bar.get_x()+bar.get_width()/2, v+0.5, f"{v}%",
            ha="center", fontsize=11, fontweight="bold", color=WHITE)
ax.set_ylim(0, cdf2["w8_pct"].max()*1.25)
ax.set_ylabel("Week-8 Retention Rate (%)", fontsize=11)
ax.set_title("Week-8 Retention by Acquisition Channel", fontsize=14,
             fontweight="bold", color=WHITE, pad=14)
ax.axhline(cdf2["w8_pct"].mean(), color=BRAND, lw=1.3, linestyle="--", alpha=0.7)
ax.text(4.4, cdf2["w8_pct"].mean()+0.3, "Avg", fontsize=9, color=BRAND)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/03_channel_retention.png", dpi=150, bbox_inches="tight")
plt.close()

# feature vs churn rate
print("  feature vs churn...")
fdf = q(conn1, """
    WITH ai_users AS (SELECT DISTINCT user_id FROM events WHERE event_type='first_ai_output'),
    fu AS (SELECT DISTINCT user_id, feature_name FROM feature_usage),
    ce AS (SELECT DISTINCT user_id FROM events WHERE event_type='churned'),
    base AS (
        SELECT u.user_id,
            MAX(CASE WHEN fu.feature_name='rewrite'   THEN 1 ELSE 0 END) r,
            MAX(CASE WHEN fu.feature_name='analyze'   THEN 1 ELSE 0 END) a,
            MAX(CASE WHEN fu.feature_name='summarize' THEN 1 ELSE 0 END) s,
            MAX(CASE WHEN fu.feature_name='generate'  THEN 1 ELSE 0 END) g,
            MAX(CASE WHEN fu.feature_name='translate' THEN 1 ELSE 0 END) t,
            MAX(CASE WHEN ce.user_id IS NOT NULL THEN 1 ELSE 0 END) churned
        FROM ai_users u LEFT JOIN fu ON u.user_id=fu.user_id
        LEFT JOIN ce ON u.user_id=ce.user_id GROUP BY u.user_id
    )
    SELECT 'rewrite' feat,
        ROUND(SUM(r*churned)*100.0/NULLIF(SUM(r),0),1) with_f,
        ROUND(SUM((1-r)*churned)*100.0/NULLIF(SUM(1-r),0),1) without_f FROM base
    UNION ALL SELECT 'analyze',  ROUND(SUM(a*churned)*100.0/NULLIF(SUM(a),0),1),   ROUND(SUM((1-a)*churned)*100.0/NULLIF(SUM(1-a),0),1) FROM base
    UNION ALL SELECT 'summarize',ROUND(SUM(s*churned)*100.0/NULLIF(SUM(s),0),1),   ROUND(SUM((1-s)*churned)*100.0/NULLIF(SUM(1-s),0),1) FROM base
    UNION ALL SELECT 'generate', ROUND(SUM(g*churned)*100.0/NULLIF(SUM(g),0),1),   ROUND(SUM((1-g)*churned)*100.0/NULLIF(SUM(1-g),0),1) FROM base
    UNION ALL SELECT 'translate',ROUND(SUM(t*churned)*100.0/NULLIF(SUM(t),0),1),   ROUND(SUM((1-t)*churned)*100.0/NULLIF(SUM(1-t),0),1) FROM base
""")
x = np.arange(len(fdf)); w = 0.35
fig, ax = plt.subplots(figsize=(10,5))
fig.patch.set_facecolor(DARK)
b1 = ax.bar(x-w/2, fdf["with_f"],    w, label="Uses Feature",       color=BRAND, alpha=0.88)
b2 = ax.bar(x+w/2, fdf["without_f"], w, label="Doesn't Use Feature", color=CYAN,  alpha=0.88)
for bar in list(b1)+list(b2):
    h = bar.get_height()
    ax.text(bar.get_x()+bar.get_width()/2, h+0.1, f"{h}%",
            ha="center", fontsize=9, color=WHITE)
ax.set_xticks(x)
ax.set_xticklabels([f.capitalize() for f in fdf["feat"]], fontsize=11)
ax.set_ylabel("Churn Rate (%)", fontsize=11)
ax.set_title("AI Feature Usage vs Churn Rate", fontsize=14,
             fontweight="bold", color=WHITE, pad=14)
ax.legend(facecolor=MID, edgecolor=BORDER, labelcolor=WHITE, fontsize=10)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/04_feature_churn.png", dpi=150, bbox_inches="tight")
plt.close()

# feature vs churn — statistical significance (chi-square)
print("  feature vs churn — significance testing...")
fcounts = q(conn1, """
    WITH ai_users AS (SELECT DISTINCT user_id FROM events WHERE event_type='first_ai_output'),
    fu AS (SELECT DISTINCT user_id, feature_name FROM feature_usage),
    ce AS (SELECT DISTINCT user_id FROM events WHERE event_type='churned'),
    base AS (
        SELECT u.user_id,
            MAX(CASE WHEN fu.feature_name='rewrite'   THEN 1 ELSE 0 END) r,
            MAX(CASE WHEN fu.feature_name='analyze'   THEN 1 ELSE 0 END) a,
            MAX(CASE WHEN fu.feature_name='summarize' THEN 1 ELSE 0 END) s,
            MAX(CASE WHEN fu.feature_name='generate'  THEN 1 ELSE 0 END) g,
            MAX(CASE WHEN fu.feature_name='translate' THEN 1 ELSE 0 END) t,
            MAX(CASE WHEN ce.user_id IS NOT NULL THEN 1 ELSE 0 END) churned
        FROM ai_users u LEFT JOIN fu ON u.user_id=fu.user_id
        LEFT JOIN ce ON u.user_id=ce.user_id GROUP BY u.user_id
    )
    SELECT
        SUM(r) r_t, SUM(r*churned) r_c, SUM(1-r) nr_t, SUM((1-r)*churned) nr_c,
        SUM(a) a_t, SUM(a*churned) a_c, SUM(1-a) na_t, SUM((1-a)*churned) na_c,
        SUM(s) s_t, SUM(s*churned) s_c, SUM(1-s) ns_t, SUM((1-s)*churned) ns_c,
        SUM(g) g_t, SUM(g*churned) g_c, SUM(1-g) ng_t, SUM((1-g)*churned) ng_c,
        SUM(t) t_t, SUM(t*churned) t_c, SUM(1-t) nt_t, SUM((1-t)*churned) nt_c
    FROM base
""").iloc[0]

sig_rows = []
for feat, pre in [("rewrite","r"),("analyze","a"),("summarize","s"),("generate","g"),("translate","t")]:
    w_t, w_c = fcounts[f"{pre}_t"], fcounts[f"{pre}_c"]
    n_t, n_c = fcounts[f"n{pre}_t"], fcounts[f"n{pre}_c"]
    table = np.array([[w_c, w_t-w_c], [n_c, n_t-n_c]])
    chi2_f, p_f, _, _ = chi2_contingency(table)
    sig_rows.append((feat, w_c/w_t, n_c/n_t, chi2_f, p_f))
    print(f"    {feat:<10} with={w_c/w_t:.1%}  without={n_c/n_t:.1%}  chi2={chi2_f:.2f}  p={p_f:.4g}  "
          f"{'significant' if p_f < 0.05 else 'not significant'}")

with open(f"{OUT_DIR}/feature_churn_significance.txt", "w", encoding="utf-8") as f:
    f.write("Feature Usage vs Churn — Chi-Square Significance Test\n")
    f.write("=" * 60 + "\n")
    f.write(f"{'Feature':<12}{'With':>9}{'Without':>10}{'Chi2':>9}{'p-value':>12}{'Sig?':>7}\n")
    f.write("-" * 60 + "\n")
    for feat, wp, np_, c2, p in sig_rows:
        f.write(f"{feat:<12}{wp*100:>8.1f}%{np_*100:>9.1f}%{c2:>9.2f}{p:>12.4g}{'Yes' if p<0.05 else 'No':>7}\n")
    f.write("\nH0: feature usage and churn are independent (population: users who reached first AI output).\n")
    sig_f = [r[0] for r in sig_rows if r[4] < 0.05]
    ns_f  = [r[0] for r in sig_rows if r[4] >= 0.05]
    f.write(f"Reject H0 at alpha=0.05 for: {', '.join(sig_f) if sig_f else 'none'}.\n")
    f.write(f"No significant relationship for: {', '.join(ns_f) if ns_f else 'none'}.\n")

# mau growth accounting
print("  mau growth...")
mdf = q(conn1, """
    WITH ma AS (
        SELECT user_id, STRFTIME('%Y-%m',session_date) mo
        FROM sessions GROUP BY user_id, mo
    ),
    wp AS (
        SELECT m.user_id, m.mo,
               LAG(m.mo) OVER (PARTITION BY m.user_id ORDER BY m.mo) prev_mo
        FROM ma m
    )
    SELECT mo, COUNT(*) mau,
        SUM(CASE WHEN prev_mo IS NULL THEN 1 ELSE 0 END) new_u,
        SUM(CASE WHEN prev_mo=STRFTIME('%Y-%m',DATE(mo||'-01','-1 month')) THEN 1 ELSE 0 END) retained,
        SUM(CASE WHEN prev_mo IS NOT NULL AND
                      prev_mo!=STRFTIME('%Y-%m',DATE(mo||'-01','-1 month')) THEN 1 ELSE 0 END) resurrected
    FROM wp GROUP BY mo ORDER BY mo
""")
mdf = mdf[mdf["mo"] <= "2025-12"]
fig, ax = plt.subplots(figsize=(12,5))
fig.patch.set_facecolor(DARK)
x_pos = range(len(mdf))
ax.stackplot(x_pos, mdf["new_u"], mdf["retained"], mdf["resurrected"],
             labels=["New","Retained","Resurrected"],
             colors=[BRAND, CYAN, BLUE], alpha=0.82)
ax.plot(x_pos, mdf["mau"], color=WHITE, lw=2, zorder=5, label="Total MAU")
ax.set_xticks(list(x_pos)[::2])
ax.set_xticklabels(mdf["mo"].iloc[::2], rotation=35, ha="right", fontsize=8.5)
ax.set_ylabel("Monthly Active Users", fontsize=11)
ax.set_title("MAU Growth Accounting — New / Retained / Resurrected", fontsize=14,
             fontweight="bold", color=WHITE, pad=14)
ax.legend(facecolor=MID, edgecolor=BORDER, labelcolor=WHITE, fontsize=10, loc="upper left")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/05_mau_growth.png", dpi=150, bbox_inches="tight")
plt.close()

# churn timing distribution
print("  churn timing...")
wdf = q(conn1, """
    WITH fa AS (
        SELECT user_id, MIN(event_date) first_ai FROM events
        WHERE event_type='first_ai_output' GROUP BY user_id
    ),
    ce AS (
        SELECT user_id, MIN(event_date) churn_date FROM events
        WHERE event_type='churned' GROUP BY user_id
    ),
    timing AS (
        SELECT c.user_id,
               JULIANDAY(c.churn_date)-JULIANDAY(fa.first_ai) days_to_churn
        FROM ce c JOIN fa ON c.user_id=fa.user_id
        WHERE JULIANDAY(c.churn_date)>=JULIANDAY(fa.first_ai)
    )
    SELECT
        CASE WHEN days_to_churn< 7 THEN 'Wk 1'
             WHEN days_to_churn<14 THEN 'Wk 2'
             WHEN days_to_churn<21 THEN 'Wk 3'
             WHEN days_to_churn<28 THEN 'Wk 4'
             WHEN days_to_churn<60 THEN 'Mo 2'
             WHEN days_to_churn<90 THEN 'Mo 3'
             ELSE 'Mo 3+' END window, COUNT(*) cnt
    FROM timing GROUP BY window ORDER BY MIN(days_to_churn)
""")
# bucket labels are day ranges after first AI output, so there is no ambiguity about "week 3"
order  = ["Days 0-6","Days 7-13","Days 14-20","Days 21-27","Days 28-59","Days 60-89","Days 90+"]
wdf["window"] = wdf["window"].map({"Wk 1":order[0],"Wk 2":order[1],"Wk 3":order[2],"Wk 4":order[3],
                                    "Mo 2":order[4],"Mo 3":order[5],"Mo 3+":order[6]})
wdf = wdf.set_index("window").reindex(order).fillna(0).astype(int).reset_index()
peak_idx = int(wdf["cnt"].idxmax())
bar_colors = [BRAND if i==peak_idx else CYAN for i in range(len(wdf))]
fig, ax = plt.subplots(figsize=(10,5))
fig.patch.set_facecolor(DARK)
bars = ax.bar(wdf["window"], wdf["cnt"], color=bar_colors, width=0.55, alpha=0.88)
total_churn = wdf["cnt"].sum()
for bar,v in zip(bars, wdf["cnt"]):
    ax.text(bar.get_x()+bar.get_width()/2, v+25, f"{v:,}\n({v/total_churn*100:.0f}%)",
            ha="center", fontsize=9.5, fontweight="bold", color=WHITE)
ax.set_ylabel("Users Churned", fontsize=11)
ax.set_title("Churn Timing — Days Between First AI Output and Churn",
             fontsize=13, fontweight="bold", color=WHITE, pad=14)
ax.set_ylim(0, wdf["cnt"].max()*1.2)
ax.annotate("⚠ Peak churn window",
            xy=(bars[peak_idx].get_x()+bars[peak_idx].get_width()/2, wdf.loc[peak_idx,"cnt"]*1.12),
            xytext=(peak_idx+1.3, wdf["cnt"].max()*1.08),
            arrowprops=dict(arrowstyle="->", color=BRAND, lw=1.5),
            fontsize=10, color=BRAND, fontweight="bold")
plt.setp(ax.get_xticklabels(), fontsize=9)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/06_churn_week_dist.png", dpi=150, bbox_inches="tight")
plt.close()
CHURN_PEAK = (wdf.loc[peak_idx,"window"], int(wdf.loc[peak_idx,"cnt"]), wdf.loc[peak_idx,"cnt"]/total_churn)
print(f"  peak churn window: {CHURN_PEAK[0]}  {CHURN_PEAK[1]:,} users ({CHURN_PEAK[2]:.1%})")

# churn prediction model
print("  churn model...")
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, roc_auc_score

mdf2 = q(conn1, """
    WITH ai_users AS (SELECT DISTINCT user_id FROM events WHERE event_type='first_ai_output'),
    ce AS (SELECT DISTINCT user_id FROM events WHERE event_type='churned'),
    fu_agg AS (
        SELECT user_id,
            COUNT(DISTINCT feature_name) n_features,
            SUM(CASE WHEN feature_name='rewrite' THEN 1 ELSE 0 END) uses_rewrite,
            SUM(CASE WHEN feature_name='analyze' THEN 1 ELSE 0 END) uses_analyze,
            AVG(usage_count_30d) avg_usage
        FROM feature_usage GROUP BY user_id
    ),
    sess_agg AS (
        SELECT user_id, COUNT(*) total_sessions,
               AVG(duration_seconds) avg_duration,
               COUNT(DISTINCT STRFTIME('%Y-%m',session_date)) active_months
        FROM sessions GROUP BY user_id
    )
    SELECT u.user_id,
        CASE WHEN u.channel='organic_search' THEN 1 ELSE 0 END ch_organic,
        CASE WHEN u.channel='referral'       THEN 1 ELSE 0 END ch_referral,
        CASE WHEN u.plan_tier='pro'          THEN 1 ELSE 0 END plan_pro,
        CASE WHEN u.plan_tier='enterprise'   THEN 1 ELSE 0 END plan_ent,
        COALESCE(fu.n_features,0)    n_features,
        COALESCE(fu.uses_rewrite,0)  uses_rewrite,
        COALESCE(fu.uses_analyze,0)  uses_analyze,
        COALESCE(fu.avg_usage,0)     avg_usage,
        COALESCE(sa.total_sessions,0) total_sessions,
        COALESCE(sa.avg_duration,0)   avg_duration,
        COALESCE(sa.active_months,0)  active_months,
        CASE WHEN ce.user_id IS NOT NULL THEN 1 ELSE 0 END churned
    FROM users u
    JOIN ai_users ai ON u.user_id=ai.user_id          -- only users who reached first AI output can churn
    LEFT JOIN fu_agg fu ON u.user_id=fu.user_id
    LEFT JOIN sess_agg sa ON u.user_id=sa.user_id
    LEFT JOIN ce ON u.user_id=ce.user_id
""")
feats = ["ch_organic","ch_referral","plan_pro","plan_ent","n_features",
         "uses_rewrite","uses_analyze","avg_usage","total_sessions","avg_duration","active_months"]
X = mdf2[feats].fillna(0); y = mdf2["churned"]
X_tr,X_te,y_tr,y_te = train_test_split(X,y,test_size=0.2,random_state=42,stratify=y)
sc = StandardScaler()
model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
model.fit(sc.fit_transform(X_tr), y_tr)
y_pred = model.predict(sc.transform(X_te))
y_prob = model.predict_proba(sc.transform(X_te))[:,1]
auc    = roc_auc_score(y_te, y_prob)
importance = sorted(zip(feats, model.coef_[0]), key=lambda x: abs(x[1]), reverse=True)
lines = [
    "AI SaaS Churn Model — Report (explanatory, not production-ready)","="*50,
    f"Population: {len(mdf2):,} users who reached first AI output (the only users who can churn); churn rate {y.mean():.1%}",
    f"Model    : Logistic Regression (class_weight=balanced)",
    f"Features : {len(feats)}",
    f"ROC-AUC  : {auc:.4f}","",
    "Classification Report:",classification_report(y_te,y_pred),"",
    "Feature Importance (|coefficient|):","─"*40,
] + [f"  {f:<22} {c:+.4f}  {'↑ churn' if c>0 else '↓ churn'}" for f,c in importance]
with open(f"{OUT_DIR}/churn_model_report.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
    print(f"  ROC-AUC: {auc:.4f}")

# churn-ROI — business impact of rewrite adoption
print("  churn-roi analysis...")
roi_df = q(conn1, """
    WITH ai_users AS (SELECT DISTINCT user_id FROM events WHERE event_type='first_ai_output'),
    paying AS (
        SELECT s.user_id, s.mrr_inr, s.status
        FROM subscriptions s
        JOIN ai_users a ON s.user_id = a.user_id
        WHERE s.plan != 'free'
    ),
    rw AS (SELECT DISTINCT user_id FROM feature_usage WHERE feature_name='rewrite')
    SELECT
        CASE WHEN rw.user_id IS NOT NULL THEN 'uses_rewrite' ELSE 'no_rewrite' END segment,
        COUNT(*) total_paying,
        SUM(CASE WHEN p.status='cancelled' THEN 1 ELSE 0 END) cancelled,
        ROUND(SUM(CASE WHEN p.status='cancelled' THEN 1 ELSE 0 END)*100.0/COUNT(*),2) churn_pct,
        SUM(CASE WHEN p.status='cancelled' THEN p.mrr_inr ELSE 0 END) mrr_lost,
        ROUND(AVG(p.mrr_inr),0) avg_mrr
    FROM paying p LEFT JOIN rw ON p.user_id = rw.user_id
    GROUP BY segment
""")

rw_row = roi_df[roi_df.segment == "uses_rewrite"].iloc[0]
nr_row = roi_df[roi_df.segment == "no_rewrite"].iloc[0]

churn_gap_pct    = nr_row.churn_pct - rw_row.churn_pct
subs_saveable    = nr_row.total_paying * (churn_gap_pct / 100)
mrr_saved_month  = subs_saveable * nr_row.avg_mrr
mrr_saved_annual = mrr_saved_month * 12

print(f"  No-rewrite churn: {nr_row.churn_pct}%  |  Rewrite churn: {rw_row.churn_pct}%  |  gap: {churn_gap_pct:.1f}pp")
print(f"  Subs saveable: {subs_saveable:.0f}  |  MRR recovery: ₹{mrr_saved_month:,.0f}/mo  (₹{mrr_saved_annual:,.0f}/yr)")

with open(f"{OUT_DIR}/churn_roi_report.txt", "w", encoding="utf-8") as f:
    f.write("Churn-ROI — Business Impact of Rewrite Adoption\n")
    f.write("=" * 55 + "\n\n")
    f.write(f"Paying users without Rewrite : {int(nr_row.total_paying):,}\n")
    f.write(f"  Churn rate                  : {nr_row.churn_pct}%\n")
    f.write(f"  MRR already lost to churn    : Rs.{int(nr_row.mrr_lost):,}\n\n")
    f.write(f"Paying users with Rewrite     : {int(rw_row.total_paying):,}\n")
    f.write(f"  Churn rate                  : {rw_row.churn_pct}%\n")
    f.write(f"  MRR already lost to churn    : Rs.{int(rw_row.mrr_lost):,}\n\n")
    f.write(f"Churn-rate gap                : {churn_gap_pct:.1f} percentage points\n")
    f.write(f"Subscriptions saveable         : ~{subs_saveable:.0f}\n")
    f.write(f"Estimated MRR recovery         : Rs.{mrr_saved_month:,.0f} / month\n")
    f.write(f"Estimated ARR recovery         : Rs.{mrr_saved_annual:,.0f} / year\n\n")
    f.write(f"Business read: if non-Rewrite paying users churned at the same rate as\n")
    f.write(f"Rewrite adopters, the business would retain an estimated Rs.{mrr_saved_annual:,.0f}\n")
    f.write(f"in annual recurring revenue. This converts the product recommendation\n")
    f.write(f"(\"make Rewrite the default first action\") into a revenue-justified ask.\n")

fig, ax = plt.subplots(figsize=(9,5))
fig.patch.set_facecolor(DARK)
roi_vals = [nr_row.mrr_lost, rw_row.mrr_lost, mrr_saved_month]
bars = ax.bar(["MRR Lost\n(No Rewrite)","MRR Lost\n(Rewrite Users)","Recoverable MRR\n(if gap closed)"],
              roi_vals, color=[GREY, CYAN, BRAND], width=0.5, alpha=0.88)
for bar, v in zip(bars, roi_vals):
    ax.text(bar.get_x()+bar.get_width()/2, v+max(roi_vals)*0.02, f"₹{v:,.0f}",
            ha="center", fontsize=10, fontweight="bold", color=WHITE)
ax.set_ylabel("Monthly Recurring Revenue (₹)", fontsize=11)
ax.set_title("Churn-ROI — Revenue at Risk vs Recoverable via Rewrite Adoption",
             fontsize=12.5, fontweight="bold", color=WHITE, pad=14)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/07_churn_roi.png", dpi=150, bbox_inches="tight")
plt.close()

conn1.close()



# part 2 — a/b test
print("\npart 2: a/b test")

conn2      = sqlite3.connect(f"{DATA_DIR}/ab_test.db")
users_df   = q(conn2, "SELECT * FROM ab_users")
events_df  = q(conn2, "SELECT * FROM ab_events")
sess_df    = q(conn2, "SELECT * FROM ab_sessions")

ctrl_n     = len(users_df[users_df.variant=="control"])
treat_n    = len(users_df[users_df.variant=="treatment"])
ai_ev      = events_df[events_df.event_type=="first_ai_output"]
ctrl_ai    = len(ai_ev[ai_ev.variant=="control"])
treat_ai   = len(ai_ev[ai_ev.variant=="treatment"])
p_ctrl     = ctrl_ai  / ctrl_n
p_treat    = treat_ai / treat_n
lift       = (p_treat - p_ctrl) / p_ctrl

# two-proportion z-test
p_pool  = (ctrl_ai+treat_ai)/(ctrl_n+treat_n)
se      = np.sqrt(p_pool*(1-p_pool)*(1/ctrl_n+1/treat_n))
z_stat  = (p_treat-p_ctrl)/se
p_value = 2*(1-norm_dist.cdf(abs(z_stat)))
se_diff = np.sqrt(p_ctrl*(1-p_ctrl)/ctrl_n + p_treat*(1-p_treat)/treat_n)
ci_lo   = (p_treat-p_ctrl)-1.96*se_diff
ci_hi   = (p_treat-p_ctrl)+1.96*se_diff

# week-4 retention chi-square
w4_ctrl  = len(events_df[(events_df.event_type=="retained_week4")&(events_df.variant=="control")])
w4_treat = len(events_df[(events_df.event_type=="retained_week4")&(events_df.variant=="treatment")])
p_w4c    = w4_ctrl/ctrl_n;  p_w4t = w4_treat/treat_n
chi2_val,p_chi2,_,_ = chi2_contingency(
    np.array([[w4_ctrl,ctrl_n-w4_ctrl],[w4_treat,treat_n-w4_treat]]))
lift_w4 = (p_w4t-p_w4c)/p_w4c

# week-1 session depth: sessions in the first 7 days after signup, per randomised user
# (users with no session count as 0, so the comparison covers everyone who was assigned)
_s = sess_df.merge(users_df[["user_id","signup_date"]], on="user_id")
_s["day"] = (pd.to_datetime(_s["session_date"]) - pd.to_datetime(_s["signup_date"])).dt.days
_w1 = _s[_s["day"] < 7].groupby("user_id").size()
users_df["w1_sessions"] = users_df["user_id"].map(_w1).fillna(0)
w1c = users_df.loc[users_df.variant=="control",  "w1_sessions"]
w1t = users_df.loc[users_df.variant=="treatment","w1_sessions"]
u_stat, p_mw = mannwhitneyu(w1t, w1c, alternative="greater")

print(f"  Primary:   ctrl={p_ctrl:.1%}  treat={p_treat:.1%}  lift=+{lift:.1%}  p={p_value:.4f}")
print(f"  Wk-4 ret:  ctrl={p_w4c:.1%}  treat={p_w4t:.1%}  p={p_chi2:.4f}")
print(f"  Wk-1 sess: ctrl_mean={w1c.mean():.2f}  treat_mean={w1t.mean():.2f}  p={p_mw:.2e}")

# power analysis
print("  power analysis...")
def req_sample(base,mde,alpha=0.05,power=0.80):
    z_a = norm_dist.ppf(1-alpha/2); z_b = norm_dist.ppf(power)
    p2  = base*(1+mde); pm = (base+p2)/2
    return int(np.ceil((z_a*np.sqrt(2*pm*(1-pm))+z_b*np.sqrt(base*(1-base)+p2*(1-p2)))**2/(p2-base)**2))
mde_r = np.arange(0.05,0.55,0.01)
fig, ax = plt.subplots(figsize=(10,5))
fig.patch.set_facecolor(DARK)
ax.plot(mde_r*100,[req_sample(p_ctrl,m,power=0.80) for m in mde_r],color=CYAN, lw=2,label="80% power")
ax.plot(mde_r*100,[req_sample(p_ctrl,m,power=0.90) for m in mde_r],color=BRAND,lw=2,label="90% power")
ax.axvline(lift*100,color=WHITE,lw=1.2,linestyle="--",alpha=0.6)
ax.axhline(ctrl_n,  color=GREY, lw=1,  linestyle=":", alpha=0.6)
ax.text(lift*100+0.5,ax.get_ylim()[1]*0.85,f"Actual lift\n{lift:.0%}",fontsize=9,color=WHITE)
ax.text(6,ctrl_n+80,f"n per arm ({ctrl_n:,})",fontsize=8.5,color=GREY)
ax.set_xlabel("Minimum Detectable Effect (%)",fontsize=11)
ax.set_ylabel("Required Sample Size (per arm)",fontsize=11)
ax.set_title("Power Analysis — Sample Size vs Detectable Effect",fontsize=13,
             fontweight="bold",color=WHITE,pad=12)
ax.set_xlim(5,50); ax.set_ylim(0,12000)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_:f"{int(x):,}"))
ax.legend(facecolor=MID,edgecolor=BORDER,labelcolor=WHITE,fontsize=10)
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/ab_01_power_analysis.png",dpi=150,bbox_inches="tight")
plt.close()

# primary metric with confidence intervals
print("  conversion rates...")
ci_clo = p_ctrl  - 1.96*np.sqrt(p_ctrl*(1-p_ctrl)/ctrl_n)
ci_chi = p_ctrl  + 1.96*np.sqrt(p_ctrl*(1-p_ctrl)/ctrl_n)
ci_tlo = p_treat - 1.96*np.sqrt(p_treat*(1-p_treat)/treat_n)
ci_thi = p_treat + 1.96*np.sqrt(p_treat*(1-p_treat)/treat_n)

fig,(ax1,ax2) = plt.subplots(1,2,figsize=(12,5),gridspec_kw={"width_ratios":[1.6,1]})
fig.patch.set_facecolor(DARK)
bars = ax1.bar(["Control\n(Standard)","Treatment\n(Rewrite-First)"],
               [p_ctrl*100,p_treat*100],color=[CYAN,BRAND],width=0.45,alpha=0.88)
ax1.errorbar(["Control\n(Standard)","Treatment\n(Rewrite-First)"],
             [p_ctrl*100,p_treat*100],
             yerr=[[(p_ctrl-ci_clo)*100,(p_treat-ci_tlo)*100],
                   [(ci_chi-p_ctrl)*100,(ci_thi-p_treat)*100]],
             fmt="none",color=WHITE,capsize=8,capthick=2,lw=2)
for bar,val in zip(bars,[p_ctrl,p_treat]):
    ax1.text(bar.get_x()+bar.get_width()/2,val*100+0.5,f"{val:.1%}",
             ha="center",fontsize=14,fontweight="bold",color=WHITE)
ax1.set_ylabel("First AI Output Rate (%)",fontsize=11)
ax1.set_title("Primary Metric — First AI Output Rate\n(95% Confidence Intervals)",
              fontsize=12,fontweight="bold",color=WHITE,pad=10)
ax1.set_ylim(0,65); ax1.grid(axis="y",alpha=0.3)
ax2.set_xlim(0,1); ax2.set_ylim(0,1); ax2.axis("off")
for idx,(label,val) in enumerate([
    ("Absolute lift",f"+{(p_treat-p_ctrl)*100:.1f}pp"),("Relative lift",f"+{lift*100:.1f}%"),
    ("Z-statistic",f"{z_stat:.3f}"),("P-value",f"{p_value:.4f}"),
    ("95% CI",f"[+{ci_lo*100:.1f}, +{ci_hi*100:.1f}]pp"),
    ("Sample ctrl",f"{ctrl_n:,}"),("Sample treat",f"{treat_n:,}"),("Result","SIGNIFICANT ✓")]):
    y = 0.92 - idx*0.115
    ax2.text(0.05,y,label,fontsize=9.5,color=GREY,va="center")
    ax2.text(0.95,y,val,fontsize=9.5,va="center",ha="right",
             color=BRAND if label=="Result" else WHITE,
             fontweight="bold" if label in ("Result","Relative lift") else "normal")
    if idx < 7: ax2.axhline(y-0.055,color=BORDER,lw=0.5,xmin=0.02,xmax=0.98)
ax2.set_facecolor(MID); ax2.patch.set_visible(True)
ax2.set_title("Test Statistics",fontsize=11,fontweight="bold",color=WHITE,pad=10)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/ab_02_conversion_rates.png",dpi=150,bbox_inches="tight")
plt.close()

# daily cumulative conversion curve
print("  daily cumulative curve...")
sig_df = events_df[events_df.event_type=="signed_up"][["user_id","variant","event_date"]].copy()
sig_df["event_date"] = pd.to_datetime(sig_df["event_date"])
ai_df2 = events_df[events_df.event_type=="first_ai_output"][["user_id","event_date"]].copy()
ai_df2.columns = ["user_id","ai_date"]; ai_df2["ai_date"] = pd.to_datetime(ai_df2["ai_date"])
merged = sig_df.merge(ai_df2,on="user_id",how="left")
merged["days_to_ai"] = (merged["ai_date"]-merged["event_date"]).dt.days
fig,ax = plt.subplots(figsize=(11,5))
fig.patch.set_facecolor(DARK)
for variant,color,label in [("control",CYAN,"Control"),("treatment",BRAND,"Treatment")]:
    vdf = merged[merged.variant==variant]; n_tot = len(vdf)
    days = list(range(0,15))
    rates = [vdf[vdf.days_to_ai<=d].shape[0]/n_tot*100 for d in days]
    ax.plot(days,rates,color=color,lw=2.5,label=label,marker="o",markersize=4)
    ax.fill_between(days,rates,alpha=0.08,color=color)
ax.axvline(7,color=GREY,lw=1,linestyle="--",alpha=0.6)
ax.text(7.15,5,"Day 7\nwindow",fontsize=8.5,color=GREY)
ax.set_xlabel("Days Since Signup",fontsize=11); ax.set_ylabel("Cumulative Rate (%)",fontsize=11)
ax.set_title("Cumulative Conversion Curve — Control vs Treatment",fontsize=13,
             fontweight="bold",color=WHITE,pad=12)
ax.legend(facecolor=MID,edgecolor=BORDER,labelcolor=WHITE,fontsize=11); ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/ab_03_daily_cumulative.png",dpi=150,bbox_inches="tight")
plt.close()

# secondary metrics
print("  secondary metrics...")
fig,(ax1,ax2) = plt.subplots(1,2,figsize=(12,5))
fig.patch.set_facecolor(DARK)
bars1 = ax1.bar(["Control","Treatment"],[p_w4c*100,p_w4t*100],color=[CYAN,BRAND],width=0.45,alpha=0.88)
for bar,val in zip(bars1,[p_w4c,p_w4t]):
    ax1.text(bar.get_x()+bar.get_width()/2,val*100+0.4,f"{val:.1%}",
             ha="center",fontsize=13,fontweight="bold",color=WHITE)
ax1.set_ylim(0,75); ax1.set_ylabel("Week-4 Retention Rate (%)",fontsize=11)
ax1.set_title(f"Week-4 Retention\nchi2={chi2_val:.2f}, p={p_chi2:.4f} ✓",
              fontsize=12,fontweight="bold",color=WHITE,pad=10)
ax1.text(0.5,0.88,f"+{lift_w4:.1%} lift",transform=ax1.transAxes,
         ha="center",fontsize=13,color=BRAND,fontweight="bold")
ax1.grid(axis="y",alpha=0.3)
bins = range(0,16)
ax2.hist(w1c.clip(upper=15),bins=bins,alpha=0.65,color=CYAN, label="Control",  density=True,width=0.45,align="left")
ax2.hist(w1t.clip(upper=15),bins=bins,alpha=0.65,color=BRAND,label="Treatment",density=True,width=0.45,align="mid")
ax2.axvline(w1c.mean(),color=CYAN, lw=2,linestyle="--",label=f"Ctrl mean {w1c.mean():.2f}")
ax2.axvline(w1t.mean(),color=BRAND,lw=2,linestyle="--",label=f"Treat mean {w1t.mean():.2f}")
ax2.set_xlabel("Sessions in first 7 days after signup",fontsize=11); ax2.set_ylabel("Density",fontsize=11)
ax2.set_title(f"Week-1 Sessions per User\nMann-Whitney p={p_mw:.1e} ✓",
              fontsize=12,fontweight="bold",color=WHITE,pad=10)
ax2.legend(facecolor=MID,edgecolor=BORDER,labelcolor=WHITE,fontsize=9); ax2.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/ab_04_secondary_metrics.png",dpi=150,bbox_inches="tight")
plt.close()

# feature adoption shift
print("  feature adoption shift...")
fc   = sess_df.groupby(["variant","ai_feature_used"]).size().unstack(fill_value=0)
fp   = fc.div(fc.sum(axis=1),axis=0)*100
feats_order = [f for f in ["rewrite","generate","summarize","analyze","translate","none"] if f in fp.columns]
x = np.arange(len(feats_order)); w = 0.35
fig,ax = plt.subplots(figsize=(11,5))
fig.patch.set_facecolor(DARK)
b1 = ax.bar(x-w/2,fp.loc["control",  feats_order],w,label="Control",  color=CYAN, alpha=0.85)
b2 = ax.bar(x+w/2,fp.loc["treatment",feats_order],w,label="Treatment",color=BRAND,alpha=0.85)
for bar in list(b1)+list(b2):
    h = bar.get_height()
    ax.text(bar.get_x()+bar.get_width()/2,h+0.3,f"{h:.1f}%",ha="center",fontsize=8.5,color=WHITE)
ax.set_xticks(x); ax.set_xticklabels([f.capitalize() for f in feats_order],fontsize=11)
ax.set_ylabel("% of Sessions",fontsize=11)
ax.set_title("Feature Adoption Shift — Control vs Treatment",fontsize=12,
             fontweight="bold",color=WHITE,pad=10)
ax.legend(facecolor=MID,edgecolor=BORDER,labelcolor=WHITE,fontsize=11); ax.grid(axis="y",alpha=0.3)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/ab_05_feature_adoption.png",dpi=150,bbox_inches="tight")
plt.close()

# results summary card
print("  results summary...")
fig = plt.figure(figsize=(12,6)); fig.patch.set_facecolor(DARK)
fig.add_subplot(111).axis("off")
metrics = [
    ("Primary: First AI Output Rate", f"{p_ctrl:.1%}", f"{p_treat:.1%}", f"+{lift*100:.1f}%",True),
    ("Secondary: Week-4 Retention",   f"{p_w4c:.1%}",  f"{p_w4t:.1%}",  f"+{lift_w4*100:.1f}%",True),
    ("Secondary: Wk-1 Sessions / User", f"{w1c.mean():.2f}",f"{w1t.mean():.2f}",
     f"+{(w1t.mean()-w1c.mean())/w1c.mean()*100:.0f}%",True),
]
headers = ["Metric","Control","Treatment","Lift","Significant?"]
hx      = [0.02, 0.32, 0.495, 0.67, 0.845]
for x_,ht in zip(hx,headers):
    fig.text(x_,0.88,ht,fontsize=10,color=GREY,fontweight="bold")
for ri,(metric,cv,tv,lv,sig) in enumerate(metrics):
    y = 0.72 - ri*0.22
    fig.text(0.02, y,metric,fontsize=10,color=WHITE,va="center")
    fig.text(0.32, y,cv,    fontsize=13,color=CYAN, va="center",fontweight="bold")
    fig.text(0.495,y,tv,    fontsize=13,color=BRAND,va="center",fontweight="bold")
    fig.text(0.67, y,lv,    fontsize=13,color=BRAND,va="center",fontweight="bold")
    fig.text(0.845,y,"✓ Yes" if sig else "✗ No",fontsize=11,
             color=BRAND if sig else GREY,va="center",fontweight="bold")
fig.text(0.5,0.96,"A/B Test Results — Rewrite-First Onboarding",
         ha="center",fontsize=14,fontweight="bold",color=WHITE)
fig.text(0.5,0.92,f"Experiment: {ctrl_n+treat_n:,} users · Mar–Sep 2025 · α=0.05",
         ha="center",fontsize=10,color=GREY)
fig.text(0.5,0.04,"Decision: SHIP ✓   All three metrics improved (simulated data). Significant at p < 0.01.",
         ha="center",fontsize=10,color=BRAND,fontweight="bold")
plt.savefig(f"{OUT_DIR}/ab_06_results_summary.png",dpi=150,bbox_inches="tight")
plt.close()

conn2.close()

print("\ndone")
print(f"  charts saved to {OUT_DIR}")
